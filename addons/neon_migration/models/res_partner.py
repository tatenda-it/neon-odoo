# -*- coding: utf-8 -*-
"""res.partner — Zoho traceability + an archived-quotes link.

Two ADDITIVE fields (no constraint, no behaviour change on existing rows):
  * zoho_source_id  — the import idempotency key + traceability.
  * zoho_dedup_review — flags partners the import CREATED despite a fuzzy
    match to an existing contact, so a human can review/merge. (Beyond the
    specced single field; a filterable record state beats a log-only note for
    the "create + flag for manual review, never wrong-merge" rule.)
"""
from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    zoho_source_id = fields.Char(
        string="Zoho Source Id", index=True, copy=False,
        help="Books contact_id / CRM record id. Zoho-import idempotency key "
        "and traceability back to the source system.")
    zoho_dedup_review = fields.Boolean(
        string="Zoho Import — Review Dedup", default=False,
        help="Set when the Zoho import created this contact despite a fuzzy "
        "name/email/phone match to an existing one — flagged for manual "
        "merge review (the import never auto-merges when unsure).")

    archived_quote_ids = fields.One2many(
        "neon.finance.quote.archive", "partner_id",
        string="Archived Zoho Quotes")
    archived_quote_count = fields.Integer(
        compute="_compute_archived_quote_count",
        string="Archived Quotes")

    archived_invoice_ids = fields.One2many(
        "neon.finance.invoice.archive", "partner_id",
        string="Archived Zoho Invoices")
    archived_invoice_count = fields.Integer(
        compute="_compute_archived_invoice_count",
        string="Archived Invoices")
    # billable-to-customer expenses (no smart button; o2m for reference)
    archived_expense_ids = fields.One2many(
        "neon.finance.expense.archive", "partner_id",
        string="Billable Zoho Expenses")

    @api.depends("archived_quote_ids")
    def _compute_archived_quote_count(self):
        # @api.depends is REQUIRED: a non-stored computed field with no
        # dependencies is not reliably delivered in the web_read payload (the
        # client read returns 0 -> the smart button's invisible-when-0 hides
        # it). Depend on the o2m so the form read computes it. Renders only on
        # the partner form (one record) — per-record search_count is robust +
        # avoids read_group count-key ambiguity across Odoo versions.
        Archive = self.env["neon.finance.quote.archive"]
        for partner in self:
            partner.archived_quote_count = (
                Archive.search_count([("partner_id", "=", partner.id)])
                if partner.id else 0)

    def action_view_archived_quotes(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Archived Zoho Quotes"),
            "res_model": "neon.finance.quote.archive",
            "view_mode": "tree,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {"create": False, "default_partner_id": self.id},
        }

    @api.depends("archived_invoice_ids")
    def _compute_archived_invoice_count(self):
        Archive = self.env["neon.finance.invoice.archive"]
        for partner in self:
            partner.archived_invoice_count = (
                Archive.search_count([("partner_id", "=", partner.id)])
                if partner.id else 0)

    def action_view_archived_invoices(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Archived Zoho Invoices"),
            "res_model": "neon.finance.invoice.archive",
            "view_mode": "tree,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {"create": False, "default_partner_id": self.id},
        }
