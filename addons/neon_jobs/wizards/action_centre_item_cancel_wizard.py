# -*- coding: utf-8 -*-
"""P4.M1.1 — Capture the required closure_reason when cancelling an
Action Centre item. Manager-only; the model-level _user_can_cancel
gate runs on action_cancel(). The wizard exists only to surface a
text input — without it, the form's Cancel button raised because
there was no UI to collect the reason.
"""
from odoo import fields, models


class ActionCentreItemCancelWizard(models.TransientModel):
    _name = "action.centre.item.cancel.wizard"
    _description = "Cancel Action Centre Item"

    item_id = fields.Many2one(
        "action.centre.item", required=True,
    )
    closure_reason = fields.Text(
        required=True,
        help="Why is this item being cancelled? Persisted to the "
        "item's audit trail.",
    )

    def action_confirm(self):
        self.ensure_one()
        self.item_id.action_cancel(reason=self.closure_reason)
        return {"type": "ir.actions.act_window_close"}
