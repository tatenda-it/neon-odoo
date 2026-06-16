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
    "version": "17.0.1.0.1",
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

The loader is scripts/import_zoho_reference.py (gated dry-run / apply).
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
        "views/res_partner_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
