# -*- coding: utf-8 -*-
"""Zoho invoice + expense REFERENCE records (finance history).

Same inert pattern as neon.finance.quote.archive: NOT account.move, NOT readable
by live finance aggregates / Cash-Flow tiles, NO ledger/AR/AP/VAT posting. The VAT
figure is stored as plain reference data, NEVER posted. Zoho remains the system of
record for collections (AR worked in Zoho) — these carry NO balance_due/outstanding.
Expenses carry NO vendor field at all (Neon's expenses aren't vendor-linked).
"""
from odoo import fields, models

# Invoice status -> simple reference bucket (paid / unpaid / void). The loader
# maps the raw Zoho status; unknown -> 'unpaid' (conservative, flagged).
INVOICE_STATUS_BUCKETS = [
    ("paid", "Paid"),
    ("unpaid", "Unpaid"),
    ("void", "Void"),
]


class NeonFinanceInvoiceArchive(models.Model):
    _name = "neon.finance.invoice.archive"
    _description = "Zoho Invoice (Reference / Historical Import)"
    _order = "invoice_date desc, id desc"
    _rec_name = "zoho_invoice_number"

    zoho_invoice_number = fields.Char(
        string="Zoho Invoice #", required=True, index=True, copy=False,
        help="Original Zoho invoice number — the import idempotency key.")
    active = fields.Boolean(default=True)

    partner_id = fields.Many2one(
        "res.partner", string="Customer", index=True, ondelete="restrict")
    zoho_customer_source_id = fields.Char(string="Zoho Customer Id", index=True)
    zoho_estimate_number = fields.Char(
        string="Source Estimate #", index=True,
        help="The Zoho estimate this invoice came from (invoice-detail "
        "estimate_id → number); links to neon.finance.quote.archive. Null if none.")

    invoice_date = fields.Date(string="Invoice Date", index=True)
    status = fields.Char(string="Zoho Status", help="Raw Zoho status snapshot.")
    status_bucket = fields.Selection(
        INVOICE_STATUS_BUCKETS, string="Status", default="unpaid",
        required=True, index=True)

    currency_code = fields.Char(string="Currency", default="USD")
    amount_untaxed = fields.Float(string="Untaxed")
    amount_tax = fields.Float(string="VAT (reference only)")
    amount_total = fields.Float(string="Total")
    # NB: NO balance_due / outstanding — Zoho is the system of record for AR.

    salesperson_id = fields.Many2one("res.users", string="Salesperson")
    salesperson_name = fields.Char(string="Salesperson (source)")
    event_summary = fields.Char(string="Event")

    line_ids = fields.One2many(
        "neon.finance.invoice.archive.line", "archive_id", string="Lines")
    note = fields.Text(string="Import Note")

    _sql_constraints = [
        ("zoho_invoice_number_uniq", "unique(zoho_invoice_number)",
         "This Zoho invoice number has already been imported."),
    ]


class NeonFinanceInvoiceArchiveLine(models.Model):
    _name = "neon.finance.invoice.archive.line"
    _description = "Zoho Invoice Line (Reference)"
    _order = "sequence, id"

    archive_id = fields.Many2one(
        "neon.finance.invoice.archive", string="Invoice", required=True,
        ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    category_prefix = fields.Char(string="Category")
    name = fields.Char(string="Item", required=True)
    description = fields.Text(string="Description")
    unit = fields.Char(string="Unit")
    quantity = fields.Float(string="Qty", default=1.0)
    unit_rate = fields.Float(string="Unit Rate")
    line_total = fields.Float(string="Line Total (excl. VAT)")
    zoho_item_id = fields.Char(string="Zoho Item Id")


class NeonFinanceExpenseArchive(models.Model):
    _name = "neon.finance.expense.archive"
    _description = "Zoho Expense (Reference / Historical Import)"
    _order = "expense_date desc, id desc"
    _rec_name = "zoho_expense_id"

    zoho_expense_id = fields.Char(
        string="Zoho Expense Id", required=True, index=True, copy=False,
        help="Original Zoho expense id — the import idempotency key.")
    active = fields.Boolean(default=True)

    expense_date = fields.Date(string="Expense Date", index=True)
    account_name = fields.Char(string="Account / Category",
                               help="e.g. Fuel / Casual Labour.")
    description = fields.Char(string="Description")
    reference_number = fields.Char(string="Reference")
    status = fields.Char(string="Zoho Status")
    is_billable = fields.Boolean(string="Billable")

    # OPTIONAL billable-to CUSTOMER (never a vendor — Neon expenses aren't
    # vendor-linked, so there is NO vendor field at all).
    partner_id = fields.Many2one(
        "res.partner", string="Billable To (Customer)", index=True,
        ondelete="restrict")
    zoho_customer_source_id = fields.Char(string="Zoho Customer Id", index=True)

    currency_code = fields.Char(string="Currency", default="USD")
    amount = fields.Float(string="Amount")
    tax = fields.Float(string="VAT (reference only)")

    line_ids = fields.One2many(
        "neon.finance.expense.archive.line", "archive_id", string="Lines")
    note = fields.Text(string="Import Note")

    _sql_constraints = [
        ("zoho_expense_id_uniq", "unique(zoho_expense_id)",
         "This Zoho expense id has already been imported."),
    ]


class NeonFinanceExpenseArchiveLine(models.Model):
    _name = "neon.finance.expense.archive.line"
    _description = "Zoho Expense Line (Reference)"
    _order = "sequence, id"

    archive_id = fields.Many2one(
        "neon.finance.expense.archive", string="Expense", required=True,
        ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    description = fields.Char(string="Description")
    account_name = fields.Char(string="Account")
    amount = fields.Float(string="Amount")
