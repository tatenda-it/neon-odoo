# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    commercial_job_ids = fields.One2many(
        "commercial.job",
        "sale_order_id",
        string="Commercial Jobs",
    )
    commercial_job_count = fields.Integer(
        string="Commercial Job Count",
        compute="_compute_commercial_job_count",
    )

    @api.depends("commercial_job_ids")
    def _compute_commercial_job_count(self):
        for rec in self:
            rec.commercial_job_count = len(rec.commercial_job_ids)
