# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    neon_partner_type = fields.Selection(
        [
            ("venue", "Venue"),
            ("planner", "Planner"),
            ("caterer", "Caterer"),
            ("decor", "Decor"),
            ("photographer", "Photographer"),
            ("agency", "Agency"),
            ("sponsor", "Sponsor"),
            ("media", "Media"),
            ("association", "Association"),
        ],
        string="Partner Type",
    )
    neon_relationship_owner_id = fields.Many2one(
        "res.users", string="Relationship Owner"
    )
    neon_relationship_strength = fields.Selection(
        [
            ("weak", "Weak"),
            ("developing", "Developing"),
            ("strong", "Strong"),
            ("strategic", "Strategic"),
        ],
        string="Relationship Strength",
    )
    neon_referral_history = fields.Text(string="Referral History")
    neon_quality_score = fields.Integer(
        string="Partner Quality Score", help="0-100."
    )
    neon_last_interaction_date = fields.Date(string="Last Interaction")
    neon_relationship_velocity = fields.Selection(
        [
            ("improving", "Improving"),
            ("stable", "Stable"),
            ("declining", "Declining"),
        ],
        string="Relationship Velocity",
    )
    neon_strategic_value = fields.Selection(
        [
            ("normal", "Normal"),
            ("high_profile", "High-Profile"),
            ("repeat_potential", "Repeat-Potential"),
            ("relationship_building", "Relationship-Building"),
        ],
        string="Strategic Value",
    )
    neon_next_move = fields.Text(string="Suggested Next Move")
    neon_competitor_overlap_id = fields.Many2one(
        "neon.competitor", string="Competitor Overlap", ondelete="set null"
    )
    neon_competitor_overlap_note = fields.Text(string="Competitor Overlap Note")
