# -*- coding: utf-8 -*-
"""res.users extension -- preferred_dashboard_type override.

Lets a user pick a default landing dashboard that overrides their
tier-derived default. Useful for Tatenda (superuser by tier but
mostly works as Sales day-to-day) without touching tier groups.

The field is optional; ``_default_dashboard_type_for_user`` honours
it when set and falls back to tier-walk when blank. Edit via
Settings -> Users (no dedicated dashboard menu in this phase).
"""
from odoo import fields, models


_DASHBOARD_TYPES = [
    ("director", "Director"),
    ("sales", "Sales"),
    ("bookkeeper", "Bookkeeper"),
    ("lead_tech", "Lead Tech"),
    ("tech", "Tech"),
]


class ResUsersDashboard(models.Model):
    _inherit = "res.users"

    preferred_dashboard_type = fields.Selection(
        _DASHBOARD_TYPES,
        string="Preferred Dashboard",
        help="Overrides the group-derived default landing dashboard. "
        "Leave blank to fall back to the tier-mapped default.",
    )
