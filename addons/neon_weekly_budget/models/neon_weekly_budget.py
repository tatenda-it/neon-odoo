# -*- coding: utf-8 -*-
"""Weekly Budget -- a standalone cash-planning sheet (replaces the Excel
'Weekly Budget' tabs). Planning only: NO link to account.move / payments /
the SCH- invoice engine. Labels are Neon's words.
"""
from odoo import api, fields, models


class NeonWeeklyBudget(models.Model):
    _name = "neon.weekly.budget"
    _description = "Weekly Budget"
    _order = "week_start desc"
    _rec_name = "name"

    week_start = fields.Date(string="Week Starting", required=True, index=True)
    name = fields.Char(string="Week", compute="_compute_name", store=True)
    currency_id = fields.Many2one(
        "res.currency", string="Currency",
        default=lambda self: self.env.company.currency_id.id)
    line_ids = fields.One2many(
        "neon.weekly.budget.line", "week_id", string="Lines")
    total_planned = fields.Monetary(
        string="Total Planned", compute="_compute_totals", store=True,
        currency_field="currency_id")
    total_paid = fields.Monetary(
        string="Total Paid", compute="_compute_totals", store=True,
        currency_field="currency_id")
    note = fields.Text(string="Notes")

    @api.depends("week_start")
    def _compute_name(self):
        for rec in self:
            rec.name = ("Week of %s" % rec.week_start) if rec.week_start else "New Week"

    @api.depends("line_ids.amount", "line_ids.paid")
    def _compute_totals(self):
        # NB v1: a nominal sum of line amounts (the Excel "Amount" column).
        # Mixed-currency weeks sum nominally; a per-currency split is a v2 item.
        for rec in self:
            rec.total_planned = sum(rec.line_ids.mapped("amount"))
            rec.total_paid = sum(rec.line_ids.mapped("paid"))


class NeonWeeklyBudgetLine(models.Model):
    _name = "neon.weekly.budget.line"
    _description = "Weekly Budget Line"
    _order = "date, id"

    week_id = fields.Many2one(
        "neon.weekly.budget", string="Week", required=True,
        ondelete="cascade", index=True)
    date = fields.Date(string="Date")
    details = fields.Char(string="Details", required=True)
    amount = fields.Monetary(string="Amount", currency_field="currency_id")
    paid = fields.Monetary(string="Paid", currency_field="currency_id")
    status = fields.Selection(
        [("planned", "Planned"), ("pending", "Pending"), ("paid", "Paid")],
        string="Status", default="planned", required=True)
    due_date = fields.Date(string="Due Date")
    notes = fields.Char(string="Notes")
    currency_id = fields.Many2one(
        "res.currency", string="Currency", required=True,
        default=lambda self: self.env.company.currency_id.id)
