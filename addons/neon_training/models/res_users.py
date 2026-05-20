# -*- coding: utf-8 -*-
"""
P7a.M2 -- res.users extension for Training tab.

Adds a One2many to certifications + two computed counts for the
form-view badges. The Training tab itself is rendered via view
inheritance in views/res_users_views.xml; the model side here
just exposes the reverse relation and the counts.
"""
from odoo import _, api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    training_certification_ids = fields.One2many(
        "neon.training.certification",
        "user_id",
        string="Training Certifications",
    )
    active_certifications_count = fields.Integer(
        string="Active Certifications",
        compute="_compute_certification_counts",
    )
    expiring_soon_count = fields.Integer(
        string="Expiring Soon (90 days)",
        compute="_compute_certification_counts",
        help="Active certifications whose date_expires falls in "
        "the next 90 days. Drives the warning badge on the user "
        "form Training tab.",
    )

    @api.depends(
        "training_certification_ids.state",
        "training_certification_ids.date_expires",
    )
    def _compute_certification_counts(self):
        from datetime import timedelta
        today = fields.Date.context_today(self)
        horizon = today + timedelta(days=90)
        for rec in self:
            active = rec.training_certification_ids.filtered(
                lambda c: c.state == "active")
            rec.active_certifications_count = len(active)
            rec.expiring_soon_count = len(active.filtered(
                lambda c: c.date_expires
                and today <= c.date_expires <= horizon))
