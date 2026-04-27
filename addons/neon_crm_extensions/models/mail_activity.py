# -*- coding: utf-8 -*-
"""Mail activity inheritance — Section 7 alert tier classification.

Adds an x_alert_tier field to every mail.activity so we can classify
notifications by urgency. Used by Section 6 rules to tag what they
create, and by future M2 work to drive AMBER daily digest and GREEN
weekly digest deliveries.
"""

from odoo import fields, models


class MailActivity(models.Model):
    _inherit = "mail.activity"

    x_alert_tier = fields.Selection(
        selection=[
            ("red", "Red — immediate action"),
            ("amber", "Amber — daily digest"),
            ("green", "Green — weekly digest"),
        ],
        string="Alert Tier",
        default="red",
        help=(
            "Urgency classification for Neon-generated activities. "
            "Red surfaces in the bell icon and 'My Activities' immediately. "
            "Amber rolls up into a daily email digest (M2 build). "
            "Green rolls up into a weekly email digest (M2 build)."
        ),
    )