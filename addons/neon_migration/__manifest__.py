# -*- coding: utf-8 -*-
{
    "name": "Neon Migration — Zoho Reference Import",
    # 17.0.1.0.0 — Zoho client + quote HISTORY as REFERENCE records. A
    # DEDICATED, inert-by-construction model graph (neon.finance.quote.archive)
    # with NO link to the live neon.finance.quote / ledger / QUO sequence /
    # approval / WhatsApp / operational event-job graph. Max isolation: this
    # module depends only on base + neon_core and is NEVER read by live
    # finance aggregates (Cash-Flow tiles read neon.finance.quote, not this).
    # 17.0.1.0.1 — dedup hardening (post first-import review): an email-exact
    # partner match now requires NAME AGREEMENT (similarity-aware: variants like
    # "Imani Consultants"/"Imani Consulting" still merge; a wholly different name
    # on the same email -> create_flag, not a silent over-merge). Future imports
    # only — does not re-run or alter the committed first import.
    # 17.0.1.1.0 — FINANCE-HISTORY layer (Option A reference-only): new inert
    # models neon.finance.invoice.archive(+line) + neon.finance.expense.archive
    # (+line), same discipline (NOT account.move, no ledger/AR/VAT posting, VAT
    # stored never posted, NO balance_due, expenses have NO vendor). Loader
    # run_finance (link-only partners, idempotent) + the won-link populate
    # (invoice→estimate → quote.archive.zoho_invoice_number). Build + tests only;
    # extraction is a separate creds-gated run.
    # 17.0.1.2.0 — SALESPERSON ROLLUP: a read-only pivot/graph report over the
    # inert quote archive (count + value per rep × status bucket). Adds ONE
    # stored computed field quote.archive.salesperson_display (Odoo name /
    # former-rep Zoho label / 'Unassigned', so former-rep quotes don't collapse
    # into one empty group) + pivot/graph/search/action/menu. Defaults to
    # currency_code=USD (never sums across USD/ZWG/ZAR). No new write capability,
    # no ledger touch.
    "version": "17.0.1.2.0",
    "summary": "Read-only reference import of Zoho Books estimates + customers "
               "(historical), isolated from the live finance models.",
    "description": """
Neon Migration — Zoho Reference Import
======================================

One-time, idempotent, re-runnable import of Zoho client + quote history
(Jan 2025 -> present) into Odoo as REFERENCE / historical records.

* NO posting to the live finance ledger; Books stays the source of truth.
* A DEDICATED model (neon.finance.quote.archive + .line) — never the live
  neon.finance.quote. Fires NO side effects: no approval, no QUO sequence,
  no expiry cron, no WhatsApp, no operational event-job graph.
* Idempotent on the Zoho estimate number / Zoho customer source id;
  reversible (archivable, superuser-only unlink) — exempt from the live
  append-only rule (that protects the ledger, not migration data).

Loaders (gated dry-run / apply): scripts/import_zoho_reference.py (clients +
quotes) and scripts/import_zoho_finance.py (invoices + expenses, reference-only).
""",
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Technical",
    "license": "LGPL-3",
    "depends": [
        "base",
        "neon_core",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/quote_archive_views.xml",
        "views/finance_archive_views.xml",
        "views/quote_rollup_views.xml",
        "views/res_partner_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
