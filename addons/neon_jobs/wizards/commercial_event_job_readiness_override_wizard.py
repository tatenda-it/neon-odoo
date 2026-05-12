# -*- coding: utf-8 -*-
"""
P3.M4 — Override the Readiness Score hard gate at the prep →
ready_for_dispatch transition. Manager or Crew Leader only;
written reason is required and persists to the Event Job's
chatter (see action_move_to_ready_for_dispatch_with_override).
"""
from odoo import fields, models


class CommercialEventJobReadinessOverrideWizard(models.TransientModel):
    _name = "commercial.event.job.readiness.override.wizard"
    _description = "Override the Readiness Score gate for an Event Job"

    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        required=True,
    )
    readiness_score = fields.Float(
        related="event_job_id.readiness_score",
        string="Current Score",
        readonly=True,
    )
    readiness_breakdown = fields.Text(
        related="event_job_id.readiness_breakdown",
        string="Current Breakdown",
        readonly=True,
    )
    override_reason = fields.Text(
        string="Override Reason",
        required=True,
        help="Why is moving to Ready for Dispatch justified despite "
        "the low Readiness Score? Persisted to the Event Job's "
        "audit trail.",
    )

    def action_confirm(self):
        self.ensure_one()
        self.event_job_id.action_move_to_ready_for_dispatch_with_override(
            self.override_reason
        )
        return {"type": "ir.actions.act_window_close"}
