# -*- coding: utf-8 -*-
from odoo import _, fields, models


class UtmCampaign(models.Model):
    """Campaign planning layer (2C) on the native utm.campaign (no parallel
    model, per the brief). Adds planning metadata + a manual 'propose' action
    that drops a proposal into the 2B review queue. Approval -> action is 2D."""

    _inherit = "utm.campaign"

    neon_play_id = fields.Many2one("neon.play", string="Play", ondelete="set null")
    neon_offer_angle = fields.Text(string="Offer Angle")
    neon_target_count = fields.Integer(string="Target Account Count")
    neon_owner_id = fields.Many2one("res.users", string="Campaign Owner")
    neon_rationale = fields.Text(string="Rationale")
    neon_is_ai_proposed = fields.Boolean(string="AI-Proposed", default=False)
    neon_plan_status = fields.Selection(
        [
            ("draft", "Draft"),
            ("proposed", "Proposed"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("running", "Running"),
            ("closed", "Closed"),
        ],
        string="Plan Status",
        default="draft",
    )

    def action_propose_campaign(self):
        """Propose this campaign plan -> review queue (propose-only)."""
        Rec = self.env["neon.shadow.recommendation"]
        for camp in self:
            camp.neon_plan_status = "proposed"
            Rec.create({
                "name": _("Campaign proposal: %s") % camp.name,
                "rec_type": "campaign",
                "campaign_id": camp.id,
                "play_id": camp.neon_play_id.id or False,
                "recommendation": camp.neon_offer_angle or _("Run campaign %s") % camp.name,
                "rationale": camp.neon_rationale or _("Manual campaign proposal."),
                "confidence": "low",
            })
        return True
