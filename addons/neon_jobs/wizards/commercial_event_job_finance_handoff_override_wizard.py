# -*- coding: utf-8 -*-
"""
P3.M7 — Capture the written reason for a manual Finance Handoff
Complete override. Manager only (Finance role doesn't exist as
a separate group; Manager stands in). Reason persists to the
Event Job's audit fields and chatter.
"""
from odoo import fields, models


class CommercialEventJobFinanceHandoffOverrideWizard(models.TransientModel):
    _name = "commercial.event.job.finance.handoff.override.wizard"
    _description = "Override Finance Handoff Complete for an Event Job"

    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        required=True,
    )
    finance_handoff_auto = fields.Boolean(
        related="event_job_id.finance_handoff_auto",
        string="Auto compute current value",
        readonly=True,
    )
    override_reason = fields.Text(
        string="Override Reason",
        required=True,
        help="Why is Finance Handoff being marked complete manually "
        "despite the auto check (scope_changes terminal + no draft "
        "invoices) not passing? Persisted to the Event Job's audit "
        "trail.",
    )

    def action_confirm(self):
        self.ensure_one()
        self.event_job_id.action_override_finance_handoff(
            self.override_reason
        )
        return {"type": "ir.actions.act_window_close"}
