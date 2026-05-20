# -*- coding: utf-8 -*-
"""
P7a.M6 + P7a.M8 -- commercial.event.job extension.

M6: cross-competency TODO surface (state='completed' write override).
M8: training_gate_status roll-up + _action_check_training_gate
helper for M9-M11 layered gating.

When an event_job's state transitions to 'completed' (the
operational "event is over" moment, before admin closeout to
'closed'), surface a TODO to Lead Tech: 'Record any cross-
competency demonstrations from this event.' Robin's A4 framing
in action; schema sketch section 4.3.

Cross-cutting enumeration per CLAUDE.md amendment from M4
(gate-1 explicit list):
  - Fields added to commercial.event.job: 0
  - Methods added to commercial.event.job: 2 (write override +
    _create_cross_competency_todo helper)
  - Buttons added to event_job views: 0
  - View XML modifications to event_job views: 0

Intentionally surgical. M8 will add fields, methods, and views
for the training_gate_status / assignment_gate_log_ids surface;
M9-M11 wire the actual gating. M6 stays narrow.
"""
import logging

from odoo import _, api, fields, models


_logger = logging.getLogger(__name__)


class CommercialEventJob(models.Model):
    _inherit = "commercial.event.job"

    # ============================================================
    # P7a.M8 -- training gate roll-up
    # ============================================================
    # P7a.M9 -- reverse o2m to assignment_gate_log records.
    # Drives the gate-log notebook tab on the event_job form
    # and lets M10/M11 hooks read prior tier-1 fires when
    # deciding whether to escalate.
    assignment_gate_log_ids = fields.One2many(
        "neon.training.assignment_gate_log",
        "event_job_id",
        string="Assignment Gate Log",
    )

    training_gate_status = fields.Selection(
        [
            ("no_crew",                "No Crew Assigned"),
            ("qualified",              "Qualified"),
            ("pending",                "Pending (crew without user)"),
            ("needs_cross_competency", "Needs Cross-Competency"),
            ("unqualified",            "Unqualified"),
        ],
        string="Training Gate",
        compute="_compute_training_gate_status",
        store=False,
        help="Worst-status-wins roll-up of "
        "commercial_job_id.crew_assignment_ids.gate_status across "
        "all crew on the parent job. M8 ships the data only -- "
        "M9 (info tier) surfaces this in dispatch banner, M10 "
        "(warn tier) gates ready_for_dispatch -> dispatched, "
        "M11 (block tier) gates draft -> planning when not "
        "softened by cross-competency.",
    )

    @api.depends(
        "commercial_job_id",
        "commercial_job_id.crew_assignment_ids",
        "commercial_job_id.crew_assignment_ids.gate_status",
    )
    def _compute_training_gate_status(self):
        """Roll up per-crew gate_status into a single event-level
        verdict. Precedence (worst wins): unqualified > needs_
        cross_competency > pending > qualified. Empty crew ->
        'no_crew'.

        Note: the per-crew gate_status itself is non-stored, so
        the dependency on it is best-effort; Odoo recomputes
        roll-ups whenever the underlying compute trigger
        (cert state, role, etc.) updates the inner compute. M12
        dashboard reads will demand stored=True; defer until then.
        """
        for rec in self:
            crew = rec.commercial_job_id.crew_assignment_ids
            if not crew:
                rec.training_gate_status = "no_crew"
                continue
            statuses = set(crew.mapped("gate_status"))
            if "unqualified" in statuses:
                rec.training_gate_status = "unqualified"
            elif "needs_cross_competency" in statuses:
                rec.training_gate_status = "needs_cross_competency"
            elif "pending" in statuses:
                rec.training_gate_status = "pending"
            else:
                rec.training_gate_status = "qualified"

    def _action_check_training_gate(self, tier="info"):
        """M9-M11 entrypoint: returns a structured dict describing
        whether the event_job's crew gate passes for the given
        tier.

        tier:
          'info'  -- always returns ok=True; populates the
                     human-readable message + crew breakdown for
                     M9's dispatch banner.
          'warn'  -- ok=False when training_gate_status is
                     'unqualified' OR 'needs_cross_competency'
                     OR 'pending' OR 'no_crew'. M10 may
                     downgrade warn -> info per Approver override
                     (Approver UX in M10).
          'block' -- ok=False when training_gate_status is
                     'unqualified'. 'needs_cross_competency'
                     passes block (the softener applied). 'pending'
                     and 'no_crew' do not block draft transitions
                     (crew may be assigned later).

        Returns:
          {
            'ok':        bool,
            'tier':      str,
            'status':    training_gate_status value,
            'message':   human-readable summary,
            'unqualified_crew_ids':  list of crew_id,
            'needs_cc_crew_ids':     list of crew_id,
            'pending_crew_ids':      list of crew_id,
            'softening_used':        bool (any crew softened),
          }

        M8 ships the helper; M9-M11 call it. No state writes here
        -- the layered-gate decision logic lives in M9-M11.
        """
        self.ensure_one()
        crew = self.commercial_job_id.crew_assignment_ids
        unqualified = crew.filtered(
            lambda c: c.gate_status == "unqualified")
        needs_cc = crew.filtered(
            lambda c: c.gate_status == "needs_cross_competency")
        pending = crew.filtered(
            lambda c: c.gate_status == "pending")
        softening_used = any(c.gate_softening_used for c in crew)

        status = self.training_gate_status
        if tier == "block":
            ok = (status != "unqualified")
        elif tier == "warn":
            ok = (status in ("qualified",))
        else:  # info
            ok = True

        if status == "qualified":
            message = _("All crew qualified.")
        elif status == "unqualified":
            names = ", ".join(
                (c.user_id.name or c.partner_id.name or _("(unnamed)"))
                for c in unqualified)
            message = _("Unqualified crew: %s") % names
        elif status == "needs_cross_competency":
            names = ", ".join(
                (c.user_id.name or c.partner_id.name or _("(unnamed)"))
                for c in needs_cc)
            message = _("Needs cross-competency: %s") % names
        elif status == "pending":
            names = ", ".join(
                (c.user_id.name or c.partner_id.name or _("(unnamed)"))
                for c in pending)
            message = _("Pending (no user assigned): %s") % names
        else:  # no_crew
            message = _("No crew assigned yet.")

        return {
            "ok":                     ok,
            "tier":                   tier,
            "status":                 status,
            "message":                message,
            "unqualified_crew_ids":   unqualified.ids,
            "needs_cc_crew_ids":      needs_cc.ids,
            "pending_crew_ids":       pending.ids,
            "softening_used":         softening_used,
        }

    # ============================================================
    # P7a.M6 -- cross-competency TODO on state='completed'
    # ============================================================
    def write(self, vals):
        """Detect transition INTO state='completed' (the first time)
        and surface a cross-competency TODO to Lead Tech for each
        such record in the batch. Idempotency handled inside the
        helper (mail.activity dedup by summary).

        Why 'completed' not 'closed': operationally the event is
        over at 'completed' (returned -> completed). 'closed' is
        later admin reconciliation; the cross-competency
        observation window is fresh-memory-while-event-recent,
        not post-admin. Schema sketch section 4.3 text reads
        'closed' which is a sketch inaccuracy logged as polish.

        Why write override not _do_transition override: write() is
        the single funnel for state changes in this codebase (per
        P3.M3 transition discipline in neon_jobs). Inheriting at
        the funnel point catches every transition, including any
        future neon_jobs refactor that bypasses _do_transition.
        """
        # Capture prior state per record BEFORE the write applies.
        # Bulk transitions are rare on this model (transitions are
        # gated per-record via _do_transition) but the loop is
        # defensive: a context-flagged sudo() write could batch.
        prior_states = {rec.id: rec.state for rec in self}
        result = super().write(vals)
        if vals.get("state") == "completed":
            for rec in self:
                if prior_states.get(rec.id) != "completed":
                    rec._create_cross_competency_todo()
        return result

    def _create_cross_competency_todo(self):
        """Schedule a mail.activity TODO on the Lead Tech for this
        event_job, asking them to record cross-competency
        observations from the event.

        Idempotency: searches existing mail.activity records for
        the same (res_model, res_id) with a summary matching the
        cross-competency prefix; skips creation if found. Avoids
        needing a new field on commercial.event.job.

        Recipient: prefers event_job.lead_tech_id; falls back to
        any user in neon_jobs.group_neon_jobs_crew_leader.
        Returns False silently when no Lead Tech exists in the
        system (early-deploy state; smoke handles this case).
        """
        self.ensure_one()
        # Dedup: skip if a cross-competency TODO already exists.
        existing = self.env["mail.activity"].sudo().search([
            ("res_model", "=", "commercial.event.job"),
            ("res_id", "=", self.id),
            ("summary", "=ilike", "Record cross-competency%"),
        ], limit=1)
        if existing:
            return False

        # Resolve recipient.
        target_user = self.lead_tech_id
        if not target_user:
            group = self.env.ref(
                "neon_jobs.group_neon_jobs_crew_leader",
                raise_if_not_found=False)
            if group and group.users:
                target_user = group.users[0]
        if not target_user:
            _logger.info(
                "commercial.event.job: no Lead Tech to receive "
                "cross-competency TODO for event %s.", self.display_name)
            return False

        # Build the note with the crew roster for quick reference.
        crew = self.commercial_job_id.crew_assignment_ids
        crew_names = ", ".join(
            (a.user_id.name or a.partner_id.name)
            for a in crew
            if a.user_id or a.partner_id
        ) or _("(no crew assignments on this event)")
        note = _(
            "Crew on this event: %(crew)s. Record any out-of-cert "
            "competencies demonstrated -- run the Training > "
            "Cross-Competencies action to log them while the "
            "event is fresh."
        ) % {"crew": crew_names}

        # Schedule the TODO via mail.activity.mixin helper. Deadline
        # is today + 14 days (Robin's framing: capture while memory
        # is fresh).
        from datetime import timedelta
        deadline = fields.Date.context_today(self) + timedelta(days=14)
        self.sudo().activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=target_user.id,
            summary=_("Record cross-competency observations for %s"
                      ) % self.display_name,
            note=note,
            date_deadline=deadline,
        )
        return True
