# -*- coding: utf-8 -*-
"""Suspense + Undeposited ledger REFERENCE records (historical import).

Same inert posture as the Zoho / petty-cash archives: NOT account.move, no
ledger/AR/VAT, no recompute, no side effects. Stored VERBATIM as historical
reference. Sensitive -> ACL restricts to finance (bookkeeper) + director
(superuser); the sales/operational lens never sees them.

SUSPENSE: a multi-month clearing account (income in -> transfers out, nets to 0).
  6-col running-balance cashbook; the running balance is the integrity proof.
UNDEPOSITED: per-month receipts/expenses in several layouts (two_table /
  dr_cr / amount); a flexible line carries section / currency (USD/ZWG) /
  invoice_no / note alongside dr/cr/amount.

Reversible/cleanable (superuser unlink) like the other reference archives.
"""
from odoo import api, fields, models


# ----------------------------------------------------------------------
# SUSPENSE
# ----------------------------------------------------------------------
class NeonSuspenseStatement(models.Model):
    _name = "neon.suspense.statement"
    _description = "Suspense Account (Reference / Historical Import)"
    _order = "period_month desc, id desc"
    _rec_name = "name"

    name = fields.Char(string="Statement", required=True)  # "Suspense Account 2025"
    period_month = fields.Date(string="Period", required=True, index=True)  # year anchor
    currency_code = fields.Char(string="Currency", default="USD")
    opening_balance = fields.Float(string="Opening Balance")
    closing_balance = fields.Float(string="Closing Balance")
    source_tab = fields.Char(string="Source Tab")
    active = fields.Boolean(default=True)
    note = fields.Text(string="Import Note")
    line_ids = fields.One2many(
        "neon.suspense.line", "statement_id", string="Lines")
    line_count = fields.Integer(
        string="Lines", compute="_compute_line_count", store=True)

    _sql_constraints = [
        ("period_month_uniq", "unique(period_month)",
         "There is already a suspense statement for this period."),
    ]

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)


class NeonSuspenseLine(models.Model):
    _name = "neon.suspense.line"
    _description = "Suspense Account Line (Reference)"
    _order = "statement_id, sequence, id"

    statement_id = fields.Many2one(
        "neon.suspense.statement", string="Statement", required=True,
        ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    date_raw = fields.Char(string="Date (raw)")
    date_parsed = fields.Date(string="Date")  # nullable; multi-month -> often empty
    details = fields.Char(string="Details")
    acc_code = fields.Char(string="Acc Code")
    debit = fields.Float(string="Dr")
    credit = fields.Float(string="Cr")
    balance = fields.Float(string="Balance")


# ----------------------------------------------------------------------
# UNDEPOSITED
# ----------------------------------------------------------------------
class NeonUndepositedStatement(models.Model):
    _name = "neon.undeposited.statement"
    _description = "Undeposited Funds (Reference / Historical Import)"
    _order = "period_month desc, id desc"
    _rec_name = "name"

    name = fields.Char(string="Statement", required=True)
    period_month = fields.Date(string="Month", required=True, index=True)
    statement_format = fields.Selection(
        [("two_table", "Receipts + Expenses"), ("dr_cr", "Dr/Cr"),
         ("amount", "Amount"), ("empty", "Empty"), ("unknown", "Unknown")],
        string="Format", default="amount")
    currency_default = fields.Char(string="Default Currency", default="USD")
    source_tab = fields.Char(string="Source Tab")
    active = fields.Boolean(default=True)
    note = fields.Text(string="Import Note")
    line_ids = fields.One2many(
        "neon.undeposited.line", "statement_id", string="Lines")
    line_count = fields.Integer(
        string="Lines", compute="_compute_line_count", store=True)

    _sql_constraints = [
        ("period_month_uniq", "unique(period_month)",
         "There is already an undeposited statement for this month."),
    ]

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)


class NeonUndepositedLine(models.Model):
    _name = "neon.undeposited.line"
    _description = "Undeposited Funds Line (Reference)"
    _order = "statement_id, sequence, id"

    statement_id = fields.Many2one(
        "neon.undeposited.statement", string="Statement", required=True,
        ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    date_raw = fields.Char(string="Date (raw)")
    date_parsed = fields.Date(string="Date")  # nullable
    details = fields.Char(string="Details")
    acc_code = fields.Char(string="Acc Code")
    section = fields.Selection(
        [("receipt", "Receipt"), ("expense", "Expense"),
         ("statement", "Statement")], string="Section", default="statement")
    invoice_no = fields.Char(string="Invoice No")
    debit = fields.Float(string="Dr")
    credit = fields.Float(string="Cr")
    amount = fields.Float(string="Amount")
    currency = fields.Char(string="Currency", default="USD")  # USD or ZWG
    note = fields.Char(string="Note")  # method / annotations (450??, transfer?)
