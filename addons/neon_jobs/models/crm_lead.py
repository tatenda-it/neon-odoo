# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    commercial_job_ids = fields.One2many(
        "commercial.job",
        "crm_lead_id",
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
