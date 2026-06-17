# -*- coding: utf-8 -*-
"""Petty-cash cashbook REFERENCE records (historical import).

Same inert posture as the Zoho archives: NOT account.move, no ledger/AR/VAT,
no recompute, no side effects. The monthly cashbook is stored VERBATIM as
historical reference. Amounts/balances are kept exactly as the sheet has them;
the parser's reconciliation checks are assertions, never corrections.

Sensitive (wages/loans/commissions/directors' drawings) -> ACL restricts to
finance (bookkeeper) + director (superuser); the sales-rep lens never sees it
(see security/ir.model.access.csv + the finance-gated menu).

Reversible/cleanable (superuser unlink) like the other reference archives —
exempt from the live append-only rule (that protects the ledger, not migration
data).
"""
from odoo import api, fields, models


class NeonPettyCashStatement(models.Model):
    _name = "neon.petty.cash.statement"
    _description = "Petty Cash Statement (Reference / Historical Import)"
    _order = "period_month desc, id desc"
    _rec_name = "name"

    name = fields.Char(string="Statement", required=True)  # "January 2026"
    # First-of-month; the import idempotency key (one statement per month).
    period_month = fields.Date(string="Month", required=True, index=True)
    currency_code = fields.Char(string="Currency", default="USD")
    opening_balance = fields.Float(string="Opening Balance")
    closing_balance = fields.Float(string="Closing Balance")
    # The month's Cr-total row where the sheet carries one (reconciliation
    # reference); null for tabs without an explicit total row.
    cr_total = fields.Float(string="Cr Total (reference)")
    source_tab = fields.Char(string="Source Tab")
    active = fields.Boolean(default=True)  # reversible: archive to retire
    note = fields.Text(string="Import Note")

    line_ids = fields.One2many(
        "neon.petty.cash.line", "statement_id", string="Lines")
    line_count = fields.Integer(
        string="Lines", compute="_compute_line_count", store=True)

    _sql_constraints = [
        ("period_month_uniq", "unique(period_month)",
         "There is already a petty-cash statement for this month."),
    ]

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)


class NeonPettyCashLine(models.Model):
    _name = "neon.petty.cash.line"
    _description = "Petty Cash Line (Reference)"
    _order = "statement_id, sequence, id"

    statement_id = fields.Many2one(
        "neon.petty.cash.statement", string="Statement", required=True,
        ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)  # PRESERVES cashbook row order
    # The ORIGINAL date cell, verbatim, so nothing is lost to the date mess.
    date_raw = fields.Char(string="Date (raw)")
    # Best-effort decoded date; NULLABLE — left empty where a cell fits no
    # known encoding (never fabricated).
    date_parsed = fields.Date(string="Date")
    details = fields.Char(string="Details")
    acc_code = fields.Char(string="Acc Code")
    debit = fields.Float(string="Dr")
    credit = fields.Float(string="Cr")
    balance = fields.Float(string="Balance")
