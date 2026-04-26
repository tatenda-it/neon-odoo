# -*- coding: utf-8 -*-
"""
Neon CRM Extensions — crm.lead inheritance.

Adds Phase 1 custom fields to leads/opportunities. Field names are
prefixed `x_` so they are easy to identify as custom and won't collide
with future Odoo upstream fields.
"""

from datetime import timedelta
from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    # ────────────────────────────────────────────────────────────────
    # Round A — Simple stored fields (no computation)
    # ────────────────────────────────────────────────────────────────

    x_brand = fields.Selection(
        selection=[
            ("neonhiring", "Neon Hiring (equipment hire)"),
            ("neonevents", "Neon Events (full production)"),
        ],
        string="Brand",
        tracking=True,
        help="Which Neon brand this lead belongs to. Set during qualifying.",
    )

    x_consent_given = fields.Boolean(
        string="Marketing Consent (GDPR)",
        default=False,
        tracking=True,
        help="Has the contact given explicit consent for marketing communications?",
    )

    x_equipment_required = fields.Text(
        string="Equipment Required",
        help=(
            "Free-text list of equipment the client is asking about. "
            "Phase 1 hook for Phase 3's structured equipment allocation."
        ),
    )

    x_annual_event_month = fields.Selection(
        selection=[
            ("01", "January"),  ("02", "February"), ("03", "March"),
            ("04", "April"),    ("05", "May"),      ("06", "June"),
            ("07", "July"),     ("08", "August"),   ("09", "September"),
            ("10", "October"),  ("11", "November"), ("12", "December"),
        ],
        string="Annual Event Month",
        help=(
            "For Annual Client tagged contacts — the month their event "
            "typically happens. Drives the 9-month re-engagement check."
        ),
    )

    # ────────────────────────────────────────────────────────────────
    # Round B — SLA tracking datetime (set by message_post hook in §4)
    # ────────────────────────────────────────────────────────────────

    x_first_response_time = fields.Datetime(
        string="First Response Time",
        readonly=True,
        copy=False,
        help=(
            "Timestamp of the first outbound message from a Neon team member "
            "after the lead was created. Used by SLA breach computation."
        ),
    )
    # ────────────────────────────────────────────────────────────────
    # Round C — Computed fields (auto-derived, never set manually)
    # ────────────────────────────────────────────────────────────────

    x_sla_breached = fields.Boolean(
        string="SLA Breached",
        compute="_compute_sla_breached",
        store=True,
        help=(
            "True when the first response took longer than 2 hours after "
            "the lead was created. Auto-computed; do not set manually."
        ),
    )

    x_lead_score = fields.Integer(
        string="Lead Score",
        compute="_compute_lead_score",
        store=True,
        help=(
            "1-5 score auto-computed from expected_revenue x probability. "
            "Higher = more probable, higher value lead. Tune thresholds "
            "in the _compute_lead_score method when real data is available."
        ),
    )

    # ────────────────────────────────────────────────────────────────
    # Compute methods for Round C
    # ────────────────────────────────────────────────────────────────

    @api.depends("create_date", "x_first_response_time")
    def _compute_sla_breached(self):
        """Flag the lead as breaching SLA if first response > 2 hours."""
        sla_window = timedelta(hours=2)
        for lead in self:
            if lead.create_date and lead.x_first_response_time:
                elapsed = lead.x_first_response_time - lead.create_date
                lead.x_sla_breached = elapsed > sla_window
            else:
                lead.x_sla_breached = False

    @api.depends("expected_revenue", "probability")
    def _compute_lead_score(self):
        """Map probable revenue (revenue x probability) to a 1-5 score."""
        for lead in self:
            revenue = lead.expected_revenue or 0.0
            prob = lead.probability or 0.0
            probable_value = revenue * prob / 100.0
            if probable_value >= 10000:
                lead.x_lead_score = 5
            elif probable_value >= 5000:
                lead.x_lead_score = 4
            elif probable_value >= 2000:
                lead.x_lead_score = 3
            elif probable_value >= 500:
                lead.x_lead_score = 2
            else:
                lead.x_lead_score = 1