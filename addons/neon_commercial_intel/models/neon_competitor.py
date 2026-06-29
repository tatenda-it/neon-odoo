# -*- coding: utf-8 -*-
from odoo import fields, models


class NeonCompetitor(models.Model):
    _name = "neon.competitor"
    _description = "Neon Competitor Intelligence"
    _order = "name"

    name = fields.Char(string="Competitor Name", required=True)
    active = fields.Boolean(default=True)
    service_focus = fields.Text(string="Service Focus")

    sector_strength = fields.Char(string="Sector Strength")
    event_type_strength = fields.Char(string="Event-Type Strength")
    venue_strength = fields.Char(string="Venue Strength")

    pricing_posture = fields.Selection(
        [
            ("premium", "Premium"),
            ("value", "Value"),
            ("bundled", "Bundled"),
            ("undercutting", "Undercutting"),
            ("unknown", "Unknown"),
        ],
        string="Pricing Posture",
        default="unknown",
    )
    relationship_advantage = fields.Text(string="Relationship Advantage")
    known_client_ids = fields.Many2many(
        "res.partner",
        "neon_competitor_known_client_rel",
        "competitor_id",
        "partner_id",
        string="Known / Suspected Clients",
    )
    positioning_note = fields.Text(string="Positioning Note")
    last_intel_update = fields.Date(string="Last Intelligence Update")

    # §25 — source-confidence levels for competitor intelligence.
    intel_confidence = fields.Selection(
        [
            ("confirmed", "Confirmed"),
            ("likely", "Likely"),
            ("suspected", "Suspected"),
            ("anecdotal", "Anecdotal"),
        ],
        string="Intel Confidence",
        default="suspected",
        help="Competitor mapping is intelligence, not assumed fact. "
             "Record how strongly the data is supported.",
    )
