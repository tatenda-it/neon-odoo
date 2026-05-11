# -*- coding: utf-8 -*-
"""
P2.M7 — Crew decline wizard.

Captures decline_reason on commercial.job.crew. Required field — crew
declines must explain why so MD/OD can reassign with context.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError


class CommercialJobCrewDeclineWizard(models.TransientModel):
    _name = "commercial.job.crew.decline.wizard"
    _description = "Decline a Crew Assignment with a reason"

    crew_id = fields.Many2one(
        "commercial.job.crew",
        string="Crew Assignment",
        required=True,
    )
    decline_reason = fields.Text(
        string="Decline Reason",
        required=True,
        help="Why are you declining? Visible to MD/OD when they reassign.",
    )

    def action_confirm(self):
        self.ensure_one()
        if self.crew_id.state != "pending":
            raise UserError(_(
                "This assignment is no longer pending (current state: %s)."
            ) % self.crew_id.state)
        self.crew_id.write({
            "state": "declined",
            "responded_on": fields.Datetime.now(),
            "decline_reason": self.decline_reason,
        })
        return {"type": "ir.actions.act_window_close"}
