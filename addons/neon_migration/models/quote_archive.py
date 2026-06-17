# -*- coding: utf-8 -*-
"""Zoho quote (estimate) REFERENCE records.

A dedicated, inert model graph. It deliberately does NOT:
  * link to neon.finance.quote / commercial.event.job / commercial.job
  * consume the QUO- ir.sequence (name is the original Zoho number)
  * create approvals, invoice schedules, conversion-rate stamps
  * inherit mail.thread (no chatter/activity/notification side effects)
  * use res.currency Monetary (currency is a free char USD/ZWG/ZAR)

So importing 2,019 historical estimates touches NOTHING in the live finance
or operational surfaces. Reference / reporting only.
"""
from odoo import api, fields, models


# Zoho status -> bucket. The loader maps; unknown statuses fall to 'historical'
# (and are flagged in the loader report) rather than guessing won/lost.
STATUS_BUCKETS = [
    ("open", "Open — follow-up"),
    ("historical", "Historical"),
    ("won", "Won"),
    ("lost", "Lost"),
]


class NeonFinanceQuoteArchive(models.Model):
    _name = "neon.finance.quote.archive"
    _description = "Zoho Quote (Reference / Historical Import)"
    _order = "quotation_date desc, id desc"
    _rec_name = "zoho_estimate_number"

    # Idempotency key — the original Zoho QT- number. NOT the QUO- sequence.
    zoho_estimate_number = fields.Char(
        string="Zoho Estimate #", required=True, index=True, copy=False,
        help="Original Zoho estimate number (QT-...). The import's idempotency "
        "key — a re-run get-or-creates on this, never duplicates.")
    active = fields.Boolean(default=True)  # reversible: archive to retire

    partner_id = fields.Many2one(
        "res.partner", string="Customer", index=True, ondelete="restrict")
    zoho_customer_source_id = fields.Char(
        string="Zoho Customer Id", index=True,
        help="Books contact_id this estimate belonged to (kept even if the "
        "partner match is deferred for review).")

    quotation_date = fields.Date(string="Quotation Date", index=True)
    status_bucket = fields.Selection(
        STATUS_BUCKETS, string="Status", default="historical",
        required=True, index=True)
    zoho_status = fields.Char(
        string="Zoho Status", help="Raw Zoho status string, pre-mapping.")

    # Currency as a free char (USD/ZWG/ZAR) — NO res.currency dependency or
    # USD/ZWG-only constraint (the live model rejects ZAR; reference data keeps
    # the 1 ZAR quote faithfully).
    currency_code = fields.Char(string="Currency", default="USD")
    amount_untaxed = fields.Float(string="Untaxed")
    amount_tax = fields.Float(string="VAT (reference only)")
    amount_total = fields.Float(string="Total")

    salesperson_id = fields.Many2one(
        "res.users", string="Salesperson (user)",
        help="Mapped Odoo user for current reps (Lisa/Evrill/Munashe/Robin). "
        "Empty for former reps — see salesperson_name. The rollup groups on "
        "salesperson_display (labelled 'Salesperson'), not this.")
    salesperson_name = fields.Char(
        string="Salesperson (source)",
        help="Original Zoho salesperson label; the only record for former "
        "reps (Hamu Mutasa / Ruvimbo / Arnold) who are NOT created as users.")
    # Rollup grouping key: Odoo user name for current reps, raw Zoho label for
    # former reps, else 'Unassigned'. Stored+indexed so a pivot grouped on it
    # keeps the ~240 former-rep quotes (salesperson_name only, no id) split out
    # instead of collapsing into one empty 'None' row.
    salesperson_display = fields.Char(
        string="Salesperson", compute="_compute_salesperson_display",
        store=True, index=True)

    event_summary = fields.Char(
        string="Event", help="From the Zoho estimate subject_content "
        "(event name + date/time).")
    zoho_invoice_number = fields.Char(
        string="Zoho Invoice #",
        help="For won (invoiced) estimates — the downstream Zoho invoice that "
        "carried this estimate as its source.")

    line_ids = fields.One2many(
        "neon.finance.quote.archive.line", "archive_id", string="Lines")
    note = fields.Text(string="Import Note")

    _sql_constraints = [
        ("zoho_estimate_number_uniq", "unique(zoho_estimate_number)",
         "This Zoho estimate number has already been imported."),
    ]

    @api.depends("salesperson_id", "salesperson_name")
    def _compute_salesperson_display(self):
        for rec in self:
            rec.salesperson_display = (
                rec.salesperson_id.name if rec.salesperson_id
                else (rec.salesperson_name or "Unassigned"))


class NeonFinanceQuoteArchiveLine(models.Model):
    _name = "neon.finance.quote.archive.line"
    _description = "Zoho Quote Line (Reference)"
    _order = "sequence, id"

    archive_id = fields.Many2one(
        "neon.finance.quote.archive", string="Quote", required=True,
        ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    # Catalogue-linked, category-prefixed lines (LIGHTING/AUDIO/TRUSSING/
    # LOGISTICS) per the INV-000327 shape.
    category_prefix = fields.Char(string="Category")
    name = fields.Char(string="Item", required=True)
    description = fields.Text(string="Description")
    unit = fields.Char(string="Unit")
    quantity = fields.Float(string="Qty", default=1.0)
    unit_rate = fields.Float(string="Unit Rate")
    line_total = fields.Float(string="Line Total (excl. VAT)")
    zoho_item_id = fields.Char(string="Zoho Item Id")
