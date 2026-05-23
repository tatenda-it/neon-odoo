# -*- coding: utf-8 -*-
"""
P7a.M6 + P7a.M8 + P7a.M11 -- commercial.event.job extension.

M6: cross-competency TODO surface (state='completed' write override).
M8: training_gate_status roll-up + _action_check_training_gate
helper for M9-M11 layered gating.
M11: action_move_to_in_progress BLOCK gate -- pre-check the
gate; if any role line is unqualified or needs_cross_competency
AND no recent tier_3 override exists within 24h, return the
event-start override wizard instead of transitioning.

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
from datetime import timedelta

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
    # P7e M10 -- required operating authorities for the
    # event_job. Admin sets per event_job; M10 gate engine
    # checks crew users' granted authorities (via neon.lms.
    # enrollment) against this list. Defensive comodel
    # string -- field declaration safe even when neon_lms
    # is not installed (Odoo accepts string comodel refs
    # for fields that may not exist yet; failure surfaces
    # only on actual read of a non-empty value).
    required_authority_ids = fields.Many2many(
        "neon.lms.operating.authority",
        "commercial_event_job_required_authority_rel",
        "event_job_id",
        "authority_id",
        string="Required Operating Authorities",
        help="Operating authorities the crew must hold to "
             "work this event. Managed by admin; the M10 "
             "gate engine fires tier_3 logs when crew user_"
             "id lacks any required authority.",
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
    # P7a.M11 -- tier-3 (BLOCK) gate on action_move_to_in_progress
    # ============================================================
    # The set of crew gate_status values that fire the tier-3
    # block. Pending passes through (DP6: empty slots are not the
    # block target). Qualified passes trivially.
    _M11_TIER_3_FIRING_STATUSES = (
        "unqualified", "needs_cross_competency",
    )

    # Freshness window for recent tier-3 overrides (DP4). An
    # override logged within this window suppresses wizard re-fire
    # on retry. 24h is the locked spec; bumping requires gate-1
    # re-approval.
    _M11_OVERRIDE_FRESHNESS_HOURS = 24

    def _m11_has_recent_tier_3_override(self):
        """Return True if a tier_3 override was logged on this
        event_job within the last _M11_OVERRIDE_FRESHNESS_HOURS
        and the operator can therefore skip the wizard. Otherwise
        False.

        Uses overridden_at (set by the wizard's confirm) rather
        than fired_at -- the audit semantic is "was the human
        decision recent", not "was the fire entry recent".
        """
        self.ensure_one()
        cutoff = fields.Datetime.now() - timedelta(
            hours=self._M11_OVERRIDE_FRESHNESS_HOURS)
        recent = self.env[
            "neon.training.assignment_gate_log"].sudo().search([
            ("event_job_id",   "=", self.id),
            ("gate_tier",      "=", "tier_3_event_start"),
            ("overridden_at",  ">=", cutoff),
        ], limit=1)
        return bool(recent)

    def _evaluate_event_start_gate(self):
        """Return the recordset of commercial.job.crew rows on
        this event_job's parent commercial.job whose gate_status
        indicates a tier-3 fire. Empty result means the event
        can start cleanly.

        Pending crew (no user_id) pass through per DP6. M11 does
        NOT fire on empty slots -- M12 dashboard surfaces those
        separately.

        Sudo defensively per DP11 (M9 reference doc) -- the gate
        compute traverses M8's cert-type inference. Crew Leaders
        carry training_user via implied_ids, but the defensive
        sudo is robust to ACL drift.
        """
        self.ensure_one()
        Crew = self.env["commercial.job.crew"]
        if not self.commercial_job_id:
            return Crew
        crew = self.commercial_job_id.crew_assignment_ids.sudo()
        return crew.filtered(
            lambda c: c.gate_status
            in self._M11_TIER_3_FIRING_STATUSES)

    def action_move_to_in_progress(self):
        """Inherited. Tier-3 BLOCK: when a Crew Leader or Manager
        clicks "Event Started", evaluate the gate. If any role
        line is unqualified or needs_cross_competency AND no
        recent (< 24h) tier_3 override exists, return the
        override wizard instead of transitioning.

        The wizard's confirm path re-calls this method with
        m11_skip_gate_evaluation=True so the gate check is
        bypassed on re-entry.

        Discovery confirmed (gate-1, DP2): action_move_to_in
        _progress is the only user-facing path; the write()
        override on commercial.event.job (neon_jobs line 2349)
        locks down direct state writes. Hooking this method
        catches all real-world transitions.

        DP1 (gate-1): return ir.actions.act_window to open the
        wizard inline -- same pattern as M10's action_accept.
        """
        if self.env.context.get("m11_skip_gate_evaluation"):
            return super().action_move_to_in_progress()

        for rec in self:
            # 24h window check first -- cheaper than the gate
            # evaluation, and if it passes we don't need to read
            # M8 computes at all.
            if rec._m11_has_recent_tier_3_override():
                continue
            affected = rec._evaluate_event_start_gate()
            if affected:
                # Block: return the wizard. Subsequent records
                # in the batch are NOT processed -- multi-record
                # in_progress transitions are not a real user
                # flow (the button operates one event_job at a
                # time per dashboard UX).
                return {
                    "type":      "ir.actions.act_window",
                    "name": _("Event Start Blocked -- "
                              "Training Gate Override"),
                    "res_model": "neon.training."
                                 "event_start_gate_override_wizard",
                    "view_mode": "form",
                    "target":    "new",
                    "context":   {
                        "default_event_job_id":   rec.id,
                        "default_target_state":   "in_progress",
                        "default_override_reason": "",
                    },
                }
        # No affected crew on any record (or all had recent
        # overrides) -> delegate to super for the actual
        # transition.
        return super().action_move_to_in_progress()

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
