# -*- coding: utf-8 -*-
"""Read-only SQL-view report models over the INERT Zoho archive.

These are ``_auto=False`` database views (the sale.report / purchase.report
pattern): zero stored rows, computed at query time, so the underlying
neon.finance.quote.archive(.line) + neon.finance.invoice.archive(.line)
models stay byte-unchanged (no new columns, no stored recompute on -u).

Why a view at all: the archive LINE carries ``category_prefix`` but NOT the
parent's currency / salesperson / status / date. A pivot grouped by category
and filtered/grouped by currency (the never-blend guard) needs those parent
fields as REAL columns on each line row. The view flattens them.

Purpose:
  * neon.finance.quote.line.report  — one row per quote-archive line, parent
    fields flattened. Powers the DEMAND pivot (category x count/qty) and the
    WIN/LOSS pivot (category|rep x status_bucket x value), and the director
    dashboard's historical block reads (category demand + win-rate-by-category).
  * neon.finance.realisation.report — UNION of quote lines (quoted / won) and
    invoice lines (invoiced) by category. Powers the REALISATION pivot
    (quoted vs won vs invoiced value per category) and the block's realisation
    read. Label is "Realised revenue", NOT margin — Neon expenses are not
    item-linked, so cost-per-category cannot be computed.

INERTNESS: these read ONLY the archive tables. They are NEVER joined to or
unioned with the LIVE neon.finance.quote / account.move. Currency is the
archive's free Char (USD/ZWG/ZAR); every consumer defaults to USD and groups
by currency so no cell ever blends currencies.

DESIGN-FOR-LATER (do NOT build now): to show past + present in one view, add a
``source`` column ('archive' | 'live') and UNION ALL a parallel SELECT over the
live neon_finance_quote(_line) tables (mapping state -> bucket, currency_id ->
code). The consumers already default-group by currency, so a live UNION drops
in without reworking the never-blend guard. Kept a clean extension by NOT
baking 'archive' assumptions into field names.
"""
from odoo import fields, models, tools

from .quote_archive import STATUS_BUCKETS


class NeonFinanceQuoteLineReport(models.Model):
    _name = "neon.finance.quote.line.report"
    _description = "Zoho Quote Line — Analytics (Reference / Historical)"
    _auto = False
    _order = "category_prefix"
    _rec_name = "item_name"

    # All fields readonly — this is a database VIEW, not a writable table.
    category_prefix = fields.Char(string="Category", readonly=True)
    item_name = fields.Char(string="Item", readonly=True)
    quantity = fields.Float(string="Qty", readonly=True)
    line_total = fields.Float(string="Line Total", readonly=True)
    currency_code = fields.Char(string="Currency", readonly=True)
    salesperson_display = fields.Char(string="Salesperson", readonly=True)
    status_bucket = fields.Selection(
        STATUS_BUCKETS, string="Status", readonly=True)
    quotation_date = fields.Date(string="Quotation Date", readonly=True)
    partner_id = fields.Many2one(
        "res.partner", string="Customer", readonly=True)
    archive_id = fields.Many2one(
        "neon.finance.quote.archive", string="Quote", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # l.id is unique per line -> use it as the view id (1:1, stable).
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    l.id                                AS id,
                    COALESCE(NULLIF(TRIM(l.category_prefix), ''),
                             'Uncategorised')            AS category_prefix,
                    l.name                              AS item_name,
                    l.quantity                          AS quantity,
                    l.line_total                        AS line_total,
                    q.currency_code                     AS currency_code,
                    q.salesperson_display               AS salesperson_display,
                    q.status_bucket                     AS status_bucket,
                    q.quotation_date                    AS quotation_date,
                    q.partner_id                        AS partner_id,
                    l.archive_id                        AS archive_id
                FROM neon_finance_quote_archive_line l
                JOIN neon_finance_quote_archive q ON q.id = l.archive_id
                WHERE COALESCE(q.active, TRUE) = TRUE
            )
            """ % (self._table,)
        )


class NeonFinanceRealisationReport(models.Model):
    _name = "neon.finance.realisation.report"
    _description = "Quoted vs Realised by Category (Reference / Historical)"
    _auto = False
    _order = "category_prefix"
    _rec_name = "category_prefix"

    # ⚠️ The same quote line appears under BOTH 'quoted' and (if its parent is
    # won) 'won' — intentional: 'quoted' is the full book, 'won' the subset.
    # Because every consumer pivots/filters BY kind (a column), the kinds never
    # cross-add; do NOT sum across kinds expecting a meaningful total.
    KINDS = [
        ("quoted", "Quoted"),
        ("won", "Won"),
        ("invoiced", "Invoiced (realised)"),
    ]

    category_prefix = fields.Char(string="Category", readonly=True)
    currency_code = fields.Char(string="Currency", readonly=True)
    kind = fields.Selection(KINDS, string="Measure", readonly=True)
    value = fields.Float(string="Value", readonly=True)
    quantity = fields.Float(string="Qty", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW %s AS (
                SELECT row_number() OVER () AS id, t.* FROM (
                    -- quoted: every quote-archive line
                    SELECT
                        COALESCE(NULLIF(TRIM(l.category_prefix), ''),
                                 'Uncategorised')   AS category_prefix,
                        q.currency_code             AS currency_code,
                        'quoted'::varchar           AS kind,
                        l.line_total                AS value,
                        l.quantity                  AS quantity
                    FROM neon_finance_quote_archive_line l
                    JOIN neon_finance_quote_archive q ON q.id = l.archive_id
                    WHERE COALESCE(q.active, TRUE) = TRUE

                    UNION ALL

                    -- won: quote-archive lines whose parent landed 'won'
                    SELECT
                        COALESCE(NULLIF(TRIM(l.category_prefix), ''),
                                 'Uncategorised'),
                        q.currency_code,
                        'won'::varchar,
                        l.line_total,
                        l.quantity
                    FROM neon_finance_quote_archive_line l
                    JOIN neon_finance_quote_archive q ON q.id = l.archive_id
                    WHERE COALESCE(q.active, TRUE) = TRUE
                      AND q.status_bucket = 'won'

                    UNION ALL

                    -- invoiced: every invoice-archive line (realised revenue)
                    SELECT
                        COALESCE(NULLIF(TRIM(il.category_prefix), ''),
                                 'Uncategorised'),
                        iv.currency_code,
                        'invoiced'::varchar,
                        il.line_total,
                        il.quantity
                    FROM neon_finance_invoice_archive_line il
                    JOIN neon_finance_invoice_archive iv ON iv.id = il.archive_id
                    WHERE COALESCE(iv.active, TRUE) = TRUE
                ) t
            )
            """ % (self._table,)
        )
