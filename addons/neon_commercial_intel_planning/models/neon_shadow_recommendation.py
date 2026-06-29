# -*- coding: utf-8 -*-
from odoo import fields, models


class NeonShadowRecommendation(models.Model):
    """Extend the 2B review queue with 2C planning recommendation types so all
    proposals flow through the same human-review surface."""

    _inherit = "neon.shadow.recommendation"

    rec_type = fields.Selection(
        selection_add=[
            ("campaign", "Campaign Proposal"),
            ("play_reco", "Play Recommendation"),
            ("recycle", "Recycle / Reactivation"),
            ("product_demand", "Product Demand Signal"),
            ("account_target", "Competitor Account Target"),
            ("planning_pack", "Monthly Planning Pack Item"),
        ],
        ondelete={
            "campaign": "cascade",
            "play_reco": "cascade",
            "recycle": "cascade",
            "product_demand": "cascade",
            "account_target": "cascade",
            "planning_pack": "cascade",
        },
    )
    campaign_id = fields.Many2one("utm.campaign", ondelete="set null")
