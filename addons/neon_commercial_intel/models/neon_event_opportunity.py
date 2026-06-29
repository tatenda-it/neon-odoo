# -*- coding: utf-8 -*-
from odoo import fields, models


class NeonEventOpportunity(models.Model):
    """Pre-sales pursuit-stage Event object (§7.2).

    Deliberately DISTINCT from neon_jobs' operational `commercial.event.job`
    (which is the confirmed/operational job, §6.8 / sub-phase 2E). This object
    captures opportunities as they FORM in the market, before they are won.
    """

    _name = "neon.event.opportunity"
    _description = "Neon Event Opportunity (Pursuit Stage)"
    _order = "expected_date, name"

    name = fields.Char(string="Event Name", required=True)
    active = fields.Boolean(default=True)

    event_type = fields.Selection(
        [
            ("conference", "Conference"),
            ("awards_dinner", "Awards Dinner"),
            ("launch", "Product Launch"),
            ("expo", "Expo"),
            ("gala", "Gala"),
            ("church", "Church Event"),
            ("roadshow", "Roadshow"),
            ("summit", "Summit"),
            ("agm", "AGM"),
        ],
        string="Event Type",
    )
    sector = fields.Selection(
        [
            ("corporate", "Corporate"),
            ("ngo", "NGO"),
            ("government", "Government"),
            ("social", "High-End Social"),
            ("religious", "Religious"),
            ("education", "Education"),
            ("other", "Other"),
        ],
        string="Sector",
    )

    event_month = fields.Selection(
        [
            ("01", "January"), ("02", "February"), ("03", "March"),
            ("04", "April"), ("05", "May"), ("06", "June"),
            ("07", "July"), ("08", "August"), ("09", "September"),
            ("10", "October"), ("11", "November"), ("12", "December"),
        ],
        string="Event Month",
    )
    frequency = fields.Selection(
        [
            ("one_off", "One-off"),
            ("annual", "Annual"),
            ("biannual", "Biannual"),
            ("quarterly", "Quarterly"),
            ("monthly", "Monthly"),
            ("ad_hoc", "Ad hoc"),
        ],
        string="Frequency",
        default="one_off",
    )
    expected_date = fields.Date(string="Expected Date")

    partner_id = fields.Many2one("res.partner", string="Client / Account")
    venue_id = fields.Many2one("res.partner", string="Venue")
    organiser_id = fields.Many2one("res.partner", string="Organiser")
    sponsor_ids = fields.Many2many(
        "res.partner",
        "neon_event_sponsor_rel",
        "event_id",
        "partner_id",
        string="Sponsors",
    )

    strategic_value = fields.Selection(
        [
            ("normal", "Normal"),
            ("high_profile", "High-Profile"),
            ("repeat_potential", "Repeat-Potential"),
            ("relationship_building", "Relationship-Building"),
        ],
        string="Strategic Value",
        default="normal",
    )
    confidence_score = fields.Integer(
        string="Confidence Score", help="Signal quality, 0-100."
    )
    pursuit_stage = fields.Selection(
        [
            ("observe", "Observe"),
            ("qualify", "Qualify"),
            ("approach", "Approach"),
            ("quote", "Quote"),
            ("service", "Service"),
            ("recycle", "Recycle"),
        ],
        string="Pursuit Stage",
        default="observe",
    )

    # Recurrence / predictive triggers.
    recurrence_group = fields.Char(
        string="Recurrence Group",
        help="Free tag linking instances of the same recurring event.",
    )
    next_planning_window = fields.Date(string="Next Expected Planning Window")

    # Graph links (§6.3 Event Opportunity Graph).
    competitor_id = fields.Many2one(
        "neon.competitor", string="Competitor Presence", ondelete="set null"
    )
    play_id = fields.Many2one("neon.play", string="Play", ondelete="set null")
    account_plan_id = fields.Many2one(
        "neon.strategic.account.plan",
        string="Strategic Account Plan",
        ondelete="set null",
    )
    lead_id = fields.Many2one("crm.lead", string="Linked Lead/Opportunity")
