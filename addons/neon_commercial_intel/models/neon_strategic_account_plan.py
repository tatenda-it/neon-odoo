# -*- coding: utf-8 -*-
from odoo import fields, models


class NeonStrategicAccountPlan(models.Model):
    _name = "neon.strategic.account.plan"
    _description = "Neon Strategic Account Plan"
    _order = "tier, name"

    name = fields.Char(string="Plan Name", required=True)
    active = fields.Boolean(default=True)
    account_id = fields.Many2one(
        "res.partner", string="Account", required=True, ondelete="cascade"
    )
    tier = fields.Selection(
        [("tier_1", "Tier 1"), ("tier_2", "Tier 2"), ("tier_3", "Tier 3")],
        string="Tier",
        default="tier_2",
    )

    current_supplier = fields.Char(string="Current Supplier")
    current_competitor_id = fields.Many2one(
        "neon.competitor", string="Current Competitor", ondelete="set null"
    )
    contact_ids = fields.Many2many(
        "res.partner",
        "neon_sap_contact_rel",
        "plan_id",
        "partner_id",
        string="Known Contacts",
    )
    entry_point = fields.Selection(
        [
            ("hr", "HR"),
            ("procurement", "Procurement"),
            ("pa", "PA"),
            ("marketing", "Marketing"),
            ("ceo", "CEO / Exec"),
            ("organiser", "Event Organiser"),
            ("venue", "Venue"),
            ("partner", "Partner"),
            ("linkedin", "LinkedIn"),
            ("tender", "Tender Route"),
        ],
        string="Relationship Entry Point",
    )
    event_ids = fields.One2many(
        "neon.event.opportunity", "account_plan_id", string="Event Calendar"
    )
    target_play_id = fields.Many2one(
        "neon.play", string="Target Play", ondelete="set null"
    )
    next_move = fields.Text(string="Next Move")
    owner_id = fields.Many2one(
        "res.users", string="Owner", default=lambda self: self.env.user
    )
    goal_90day = fields.Text(string="90-Day Goal")
    last_review_date = fields.Date(string="Last Review Date")
