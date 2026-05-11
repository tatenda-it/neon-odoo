# -*- coding: utf-8 -*-
"""
P2.M4 — Capacity Acceptance Gate.

Eight checks per P2.M1 Schema Sketch §4. Aggregation: any reject → reject;
else any warning → warning; else pass.

Firing:
- commercial.job.action_activate evaluates the gate before the state move.
  Reject branches to UserError (regular users) or the override wizard
  (managers in group_neon_jobs_manager).
- write() re-fires the gate when any of _GATE_RETRIGGER_FIELDS changes on
  an already-active job. Re-evaluation on active jobs never reverts the
  state — only updates gate_result / gate_run_at / gate_check_log and
  posts a chatter note when aggregate changes.
- The crew model fires the parent's gate on create/write/unlink when the
  parent is active (parent's write() can't see O2m changes).
"""
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


_GATE_RETRIGGER_FIELDS = frozenset({
    "event_date", "event_end_date", "venue_id", "venue_room_id",
    "sub_hire_required", "logistics_flag",
})

_RESULT_RANK = {"pass": 0, "warning": 1, "reject": 2}


class CommercialJob(models.Model):
    _inherit = "commercial.job"

    gate_check_log_summary = fields.Text(
        string="Gate Check Summary",
        compute="_compute_gate_check_log_summary",
        store=False,
    )

    # ============================================================
    # === Public entry points
    # ============================================================
    def action_activate(self):
        """P2.M4 entry: evaluate gate, branch on result + group."""
        for rec in self:
            if rec.state != "pending":
                # Idempotent: already active or terminal. Existing transition
                # guard in commercial_job.write covers invalid jumps.
                continue
            result = rec._evaluate_capacity_gate()
            aggregate = result["aggregate"]
            if aggregate == "reject":
                rec._persist_gate_result(result, post_change_chatter=False)
                if self.env.user.has_group("neon_jobs.group_neon_jobs_manager"):
                    return rec._open_gate_override_wizard()
                raise UserError(rec._format_reject_error(result))
            rec._persist_gate_result(result, post_change_chatter=False)
            rec._do_activate_state()
        return True

    def action_rerun_capacity_gate(self):
        """Manual re-run from the form button. Available to all users."""
        for rec in self:
            result = rec._evaluate_capacity_gate()
            rec._persist_gate_result(result, post_change_chatter=True)
        return True

    def _do_activate_state(self):
        """Perform only the state transition. Called by action_activate after
        a passing gate, and by the override wizard after manager confirm."""
        self.ensure_one()
        self.write({"state": "active", "soft_hold_until": False})

    # ============================================================
    # === Evaluator
    # ============================================================
    def _evaluate_capacity_gate(self):
        self.ensure_one()
        checks = [
            self._gate_check_date_venue(),
            self._gate_check_crew(),
            self._gate_check_equipment(),
            self._gate_check_cashflow(),
            self._gate_check_subhire(),
            self._gate_check_logistics(),
            self._gate_check_strategic(),
            self._gate_check_master(),
        ]
        worst = max((_RESULT_RANK[c["result"]] for c in checks), default=0)
        aggregate = {0: "pass", 1: "warning", 2: "reject"}[worst]
        return {
            "aggregate": aggregate,
            "checks": checks,
            "evaluated_at": fields.Datetime.now(),
        }

    # ============================================================
    # === Individual checks
    # ============================================================
    def _other_overlapping_active_jobs(self):
        """Active jobs (excluding self) whose date range overlaps with this
        job's. event_end_date is treated as event_date when unset, so a
        single-day event only overlaps when its event_date sits inside our
        range."""
        self.ensure_one()
        if not self.event_date:
            return self.env["commercial.job"]
        my_end = self.event_end_date or self.event_date
        # SQL-level prefilter on the upper bound; lower bound handled in
        # Python so we can coalesce event_end_date to event_date cleanly.
        candidates = self.env["commercial.job"].search([
            ("id", "!=", self.id),
            ("state", "=", "active"),
            ("event_date", "<=", my_end),
        ])
        return candidates.filtered(
            lambda j: (j.event_end_date or j.event_date) >= self.event_date
        )

    def _gate_check_date_venue(self):
        """Check 1: Date/Venue/Room overlap (Q-S4).
        Same venue + same room → REJECT. Same venue, different/unset room →
        WARNING (logistics overlap)."""
        self.ensure_one()
        if not self.venue_id or not self.event_date:
            return {"name": "date_venue", "result": "pass",
                    "message": _("No venue or event date set; conflict check skipped.")}
        overlapping = self._other_overlapping_active_jobs().filtered(
            lambda j: j.venue_id == self.venue_id
        )
        if not overlapping:
            return {"name": "date_venue", "result": "pass",
                    "message": _("No venue or room conflict on this date.")}
        if self.venue_room_id:
            same_room = overlapping.filtered(
                lambda j: j.venue_room_id and j.venue_room_id == self.venue_room_id
            )
            if same_room:
                names = ", ".join(same_room.mapped("name"))
                return {"name": "date_venue", "result": "reject",
                        "message": _("Same venue + same room conflict with: %s.") % names}
        names = ", ".join(overlapping.mapped("name"))
        return {"name": "date_venue", "result": "warning",
                "message": _(
                    "Same venue same date as %s — logistics overlap "
                    "(parking, loading, sound, shared crew)."
                ) % names}

    def _gate_check_crew(self):
        """Check 2: Crew double-booking.
        Confirmed crew on this job that is also on overlapping active job →
        WARNING. Pending crew → WARNING with note."""
        self.ensure_one()
        if not self.event_date:
            return {"name": "crew", "result": "pass",
                    "message": _("No event date set; crew check skipped.")}
        my_users = self.crew_assignment_ids.mapped("user_id")
        if not my_users:
            return {"name": "crew", "result": "pass",
                    "message": _("No crew assigned to this job yet.")}
        overlapping = self._other_overlapping_active_jobs()
        if not overlapping:
            return {"name": "crew", "result": "pass",
                    "message": _("No overlapping active jobs.")}
        confirmed_clashes = []
        pending_clashes = []
        for other in overlapping:
            for assign in other.crew_assignment_ids:
                if assign.user_id in my_users and assign.state in ("confirmed", "pending"):
                    pair = "%s @ %s" % (assign.user_id.name, other.name)
                    if assign.state == "confirmed":
                        confirmed_clashes.append(pair)
                    else:
                        pending_clashes.append(pair)
        if not confirmed_clashes and not pending_clashes:
            return {"name": "crew", "result": "pass",
                    "message": _("No crew conflicts on overlapping active jobs.")}
        parts = []
        if confirmed_clashes:
            parts.append(_("confirmed on %s") % ", ".join(sorted(set(confirmed_clashes))))
        if pending_clashes:
            parts.append(_("pending confirmation on %s") % ", ".join(sorted(set(pending_clashes))))
        return {"name": "crew", "result": "warning",
                "message": _("Crew double-booked: %s.") % "; ".join(parts)}

    def _gate_check_equipment(self):
        return {"name": "equipment", "result": "pass",
                "message": _("Equipment-level booking deferred to Phase 5 (Workshop).")}

    def _gate_check_cashflow(self):
        """Check 4: count other active jobs in the next 14 days with
        unpaid/partial finance status. >= 3 → WARNING."""
        self.ensure_one()
        if not self.event_date:
            return {"name": "cashflow", "result": "pass",
                    "message": _("No event date set; cash-flow check skipped.")}
        window_end = fields.Date.add(self.event_date, days=14)
        count = self.env["commercial.job"].search_count([
            ("id", "!=", self.id),
            ("state", "=", "active"),
            ("event_date", ">=", self.event_date),
            ("event_date", "<=", window_end),
            ("finance_status", "in", ("quoted", "deposit_pending", "deposit_received")),
        ])
        if count >= 3:
            return {"name": "cashflow", "result": "warning",
                    "message": _(
                        "%d other active jobs awaiting deposit/payment in the "
                        "next 14 days — cash-flow stack risk."
                    ) % count}
        return {"name": "cashflow", "result": "pass",
                "message": _(
                    "%d other active jobs awaiting deposit/payment in the next "
                    "14 days (threshold 3)."
                ) % count}

    def _gate_check_subhire(self):
        self.ensure_one()
        if self.sub_hire_required:
            return {"name": "sub_hire", "result": "warning",
                    "message": _("Sub-hire required — confirm supplier lined up.")}
        return {"name": "sub_hire", "result": "pass",
                "message": _("No sub-hire required.")}

    def _gate_check_logistics(self):
        self.ensure_one()
        if self.logistics_flag:
            return {"name": "logistics", "result": "warning",
                    "message": _("Logistics flag set — confirm travel/recovery window.")}
        return {"name": "logistics", "result": "pass",
                "message": _("No logistics flag.")}

    def _gate_check_strategic(self):
        return {"name": "strategic", "result": "pass",
                "message": _("Strategic-value scoring is a Phase 8 placeholder.")}

    def _gate_check_master(self):
        self.ensure_one()
        if self.master_contract_id:
            return {"name": "master_contract", "result": "pass",
                    "message": _(
                        "Contributes toward master contract %s value target."
                    ) % self.master_contract_id.name}
        return {"name": "master_contract", "result": "pass",
                "message": _("No master contract linkage.")}

    # ============================================================
    # === Persistence + side effects
    # ============================================================
    def _persist_gate_result(self, result, post_change_chatter=False):
        """Write gate_result, gate_run_at, gate_check_log. Optionally chatter."""
        self.ensure_one()
        old_aggregate = self.gate_result
        new_aggregate = result["aggregate"]
        # Once overridden, never silently revert to a non-overridden state.
        # Re-runs on overridden jobs keep gate_result='overridden' but update
        # the log so the audit trail reflects current conditions.
        persisted = (
            "overridden"
            if self.gate_result == "overridden" and new_aggregate != "pass"
            else new_aggregate
        )
        log_payload = {
            "aggregate": new_aggregate,
            "persisted_as": persisted,
            "checks": result["checks"],
            "evaluated_at": fields.Datetime.to_string(result["evaluated_at"]),
        }
        self.write({
            "gate_result": persisted,
            "gate_run_at": result["evaluated_at"],
            "gate_check_log": json.dumps(log_payload, default=str),
        })
        if post_change_chatter and old_aggregate != persisted:
            failing = [c for c in result["checks"]
                       if c["result"] in ("warning", "reject")]
            summary = (
                "; ".join("%s: %s" % (c["name"], c["message"]) for c in failing)
                or _("all checks pass")
            )
            self.message_post(body=_(
                "Capacity Gate now %s: %s"
            ) % (persisted, summary))

    def _format_reject_error(self, result):
        failing = [c for c in result["checks"] if c["result"] == "reject"]
        lines = [_("Capacity Gate rejected activation. Failing checks:")]
        for c in failing:
            lines.append(" - %s: %s" % (c["name"], c["message"]))
        lines.append(_(
            "If this is justified, ask a manager (MD/OD) to activate — they "
            "will be shown the override wizard."
        ))
        return "\n".join(lines)

    def _open_gate_override_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Override Capacity Gate"),
            "res_model": "commercial.job.gate.override.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_job_id": self.id},
        }

    @api.depends("gate_check_log")
    def _compute_gate_check_log_summary(self):
        markers = {"pass": "[PASS]", "warning": "[WARN]", "reject": "[REJECT]"}
        for rec in self:
            if not rec.gate_check_log:
                rec.gate_check_log_summary = False
                continue
            try:
                data = json.loads(rec.gate_check_log)
            except (ValueError, TypeError):
                rec.gate_check_log_summary = rec.gate_check_log
                continue
            lines = []
            for c in data.get("checks", []):
                marker = markers.get(c.get("result"), "[?]")
                lines.append("%s %s — %s" % (
                    marker, c.get("name", ""), c.get("message", "")
                ))
            rec.gate_check_log_summary = "\n".join(lines)

    # ============================================================
    # === Re-trigger on write of dependency fields
    # ============================================================
    def write(self, vals):
        retrigger = bool(_GATE_RETRIGGER_FIELDS.intersection(vals.keys()))
        res = super().write(vals)
        if retrigger:
            for rec in self.filtered(lambda j: j.state == "active"):
                result = rec._evaluate_capacity_gate()
                rec._persist_gate_result(result, post_change_chatter=True)
        return res
