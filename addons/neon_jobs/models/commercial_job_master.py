# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class CommercialJobMaster(models.Model):
    _name = "commercial.job.master"
    _description = "Master Contract — multi-event corporate commitment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "start_date desc, name"

    name = fields.Char(
        string="Contract Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        tracking=True,
    )
    title = fields.Char(
        string="Contract Title",
        required=True,
        tracking=True,
        help='e.g. "C Suite 2026 Events Programme"',
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Client",
        required=True,
        tracking=True,
        domain=[("is_company", "=", True)],
    )
    start_date = fields.Date(string="Period Start", tracking=True)
    end_date = fields.Date(string="Period End", tracking=True)
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    value_target = fields.Monetary(
        string="Target Value",
        currency_field="currency_id",
        help="Total committed annual value, if any.",
    )
    value_realised = fields.Monetary(
        string="Realised Value",
        currency_field="currency_id",
        compute="_compute_value_realised",
        store=False,
    )
    description = fields.Text(string="Notes")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )
    job_ids = fields.One2many(
        "commercial.job",
        "master_contract_id",
        string="Commercial Jobs",
    )
    job_count = fields.Integer(
        string="Job Count",
        compute="_compute_job_count",
    )

    @api.depends("job_ids")
    def _compute_job_count(self):
        for rec in self:
            rec.job_count = len(rec.job_ids)

    @api.depends("job_ids.quoted_value", "job_ids.state")
    def _compute_value_realised(self):
        for rec in self:
            rec.value_realised = sum(
                j.quoted_value for j in rec.job_ids if j.state == "completed"
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("commercial.job.master")
                    or _("New")
                )
        return super().create(vals_list)
