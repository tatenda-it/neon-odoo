# -*- coding: utf-8 -*-
from odoo import fields, models


class NeonPlay(models.Model):
    _name = "neon.play"
    _description = "Neon Commercial Play (Go-to-Market Motion)"
    _order = "name"

    name = fields.Char(string="Play Name", required=True)
    active = fields.Boolean(default=True)

    trigger_signal = fields.Text(string="Trigger Signal")
    timing_window = fields.Char(string="Timing Window")

    product_focus = fields.Selection(
        [
            ("sound", "Sound"),
            ("wireless", "Wireless"),
            ("led", "LED"),
            ("staging", "Staging"),
            ("full_production", "Full Production"),
            ("package", "Package Bundle"),
        ],
        string="Primary Product Focus",
    )
    offer_angle = fields.Text(string="Offer Angle")
    contact_path = fields.Text(string="Contact Path")
    message_sequence = fields.Text(string="Message Sequence")

    success_metric = fields.Selection(
        [
            ("meetings", "Meetings"),
            ("quotes", "Quotes"),
            ("wins", "Wins"),
            ("referrals", "Referrals"),
            ("partner_intros", "Partner Intros"),
        ],
        string="Success Metric",
    )
    historical_performance = fields.Text(string="Historical Performance")
    recommended_changes = fields.Text(string="Recommended Changes")
    competitive_use_case = fields.Text(string="Competitive Use Case")
    competitor_id = fields.Many2one(
        "neon.competitor",
        string="Best Against Competitor",
        ondelete="set null",
    )
