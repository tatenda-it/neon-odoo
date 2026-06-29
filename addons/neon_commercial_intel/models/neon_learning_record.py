# -*- coding: utf-8 -*-
from odoo import fields, models


class NeonLearningRecord(models.Model):
    """Skeleton only (2A). The learning LOOPS that populate it are 2F and are
    blocked on post-cutover live data. Built now so the structure exists and
    other 2A objects can reference it; no compute/automation here yet.
    """

    _name = "neon.learning.record"
    _description = "Neon Learning Record"
    _order = "date desc, id desc"

    name = fields.Char(string="Summary", required=True)
    active = fields.Boolean(default=True)
    date = fields.Date(string="Date", default=fields.Date.context_today)

    loop_type = fields.Selection(
        [
            ("win_loss", "Win/Loss"),
            ("campaign", "Campaign"),
            ("partner", "Partner"),
            ("play", "Play"),
            ("event", "Event"),
            ("product_demand", "Product Demand"),
            ("competitor", "Competitor"),
        ],
        string="Loop Type",
    )

    captured = fields.Text(string="What It Captures")
    improvement = fields.Text(string="What It Improves")

    # Optional source links (any may be set depending on loop_type).
    lead_id = fields.Many2one("crm.lead", string="Lead", ondelete="set null")
    event_id = fields.Many2one(
        "neon.event.opportunity", string="Event", ondelete="set null"
    )
    play_id = fields.Many2one("neon.play", string="Play", ondelete="set null")
    partner_id = fields.Many2one(
        "res.partner", string="Partner", ondelete="set null"
    )
    competitor_id = fields.Many2one(
        "neon.competitor", string="Competitor", ondelete="set null"
    )
    campaign_id = fields.Many2one(
        "utm.campaign", string="Campaign", ondelete="set null"
    )
