# -*- coding: utf-8 -*-
"""
P7a.M6 -- commercial.event.job extension for cross-competency
TODO surface.

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
