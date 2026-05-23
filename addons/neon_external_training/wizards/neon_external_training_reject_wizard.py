# -*- coding: utf-8 -*-
"""Reject Booking wizard -- Phase 7c M3.

Captures the rejection reason and delegates the actual
state transition + chatter post back to the booking
model's action_reject().
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class NeonExternalTrainingRejectWizard(models.TransientModel):
    _name = "neon.external.training.reject.wizard"
    _description = "Neon External Training - Reject Booking Wizard"

    booking_id = fields.Many2one(
        "neon.external.training.booking",
        string="Booking",
        required=True,
        readonly=True,
    )
    reason = fields.Text(
        string="Rejection Reason",
        required=True,
        help="Captured on the booking record and posted to "
             "the chatter so the requester can see why and "
             "edit + resubmit.",
    )

    def action_reject(self):
        self.ensure_one()
        if not self.booking_id:
            raise UserError(_(
                "Booking reference missing on the wizard."))
        self.booking_id.action_reject(self.reason)
        return {"type": "ir.actions.act_window_close"}
