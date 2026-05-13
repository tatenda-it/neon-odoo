# -*- coding: utf-8 -*-
"""
P3.M7 — Capture the written reason for a manual Gear Reconciled
override. Lead Tech / Manager only. Reason persists to the
Event Job's audit fields and chatter.
"""
from odoo import fields, models


class CommercialEventJobGearReconciledOverrideWizard(models.TransientModel):
    _name = "commercial.event.job.gear.reconciled.override.wizard"
    _description = "Override Gear Reconciled for an Event Job"

    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        required=True,
    )
    gear_reconciled_auto = fields.Boolean(
        related="event_job_id.gear_reconciled_auto",
        string="Auto compute current value",
        readonly=True,
    )
    override_reason = fields.Text(
        string="Override Reason",
        required=True,
        help="Why is Gear Reconciled being set manually despite the "
        "auto compute (Returned + Closeout checklists) not reporting "
        "complete? Persisted to the Event Job's audit trail.",
    )

    def action_confirm(self):
        self.ensure_one()
        self.event_job_id.action_override_gear_reconciled(
            self.override_reason
        )
        return {"type": "ir.actions.act_window_close"}
