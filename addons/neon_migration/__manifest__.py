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
    # 17.0.1.3.0 — HISTORICAL INTELLIGENCE pivots (Sales-Intel Layer-1, pivot
    # half): two read-only SQL-VIEW report models (_auto=False, sale.report
    # pattern — zero stored rows, existing archive models byte-unchanged) —
    # neon.finance.quote.line.report (line flattened with parent currency /
    # rep / status / date) + neon.finance.realisation.report (quoted/won/
    # invoiced UNION by category). Three standalone deep-dive pivots (Demand /
    # Win-Loss / Realisation) under the Zoho Archive menu, all USD-default +
    # group-by-currency (never blend). Internal-read ACL. Consumed by the
    # director-dashboard Historical band (neon_dashboard). No ledger touch, no
    # new write capability; archives stay inert.
    # 17.0.1.4.0 — PETTY CASH reference archive (operational-data plan step 1):
    # new inert models neon.petty.cash.statement(+line) — the monthly cashbook
    # stored VERBATIM (NOT account.move, no ledger/AR/VAT, no recompute). Loaded
    # from the local "Neon Expenses 2025/2026.xlsx" via parse_petty_cash.py
    # (xlsx->JSON, per-cell date decode + reconciliation asserts) + a JSON->prod
    # loader (idempotent per period_month). SENSITIVE (wages/loans/commissions)
    # -> ACL finance(bookkeeper)+director(superuser) ONLY, OFF the sales-rep
    # lens; reversible (superuser unlink). 18 statements (12x2025 + 6x2026).
    # 17.0.1.5.0 — SUSPENSE + UNDEPOSITED reference archives (op-data plan,
    # historical-reference): new inert models neon.suspense.statement(+line)
    # (multi-month clearing account, running-balance reconcile) +
    # neon.undeposited.statement(+line) (flexible: two_table/dr_cr/amount, ZWG
    # multi-currency, receipt/expense/statement sections). Same inert posture
    # (NOT account.move). Loaded from the same local xlsx (the tabs petty-cash
    # excluded). ACL finance(bookkeeper)+director(superuser) ONLY, off the
    # sales lens; reversible. 2 suspense + 5 undeposited (July empty skipped).
    # 17.0.1.6.0 — FAMCAL JOB-HISTORY reference (op-data plan step 2, wages
    # prerequisite/job spine): inert model neon.job.history loaded from the
    # FamCal scrape (726 events, clean ISO dates). Stores ALL events verbatim;
    # reminders/admin TAGGED is_job=False + default-hidden (never deleted);
    # conservative high-confidence title->res.partner match (else NULL, raw
    # title always kept). Readable by ALL internal users (no money); reversible.
    # 17.0.1.7.0 — CREW ROSTER reference (op-data step 3a, wages prerequisite):
    # inert model neon.crew.member — canonical crew list from the wages sheet,
    # every raw spelling preserved in aliases. De-dup resolved with Tatenda
    # (KK=Ranganai lead, Biriad=Kudzai Mushore, Anorld=Arnold Mutasa, Kevin=
    # Kelvin Maibeki, Danny=Kelvin Mushore [distinct], 9 former crew inactive).
    # NOT live hr.employee/wage/crew. All-internal read; reversible.
    # 17.0.1.8.0 — WAGES reference (op-data step 3b, final historical-ref lane):
    # inert model neon.wages.entry — WEEKLY-LUMP pay per technician (NO per-job
    # split). Loaded from the wages sheet (3 layouts); crew-FK resolved via the
    # crew-roster aliases; conservative job fuzzy-match to neon.job.history
    # (jobs_raw kept verbatim). PAY -> ACL finance(bookkeeper)+director only.
    # NOT live hr.employee/wage/crew. Reversible.
    "version": "17.0.1.8.0",
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
        # 17.0.1.3.0 — historical-intelligence deep-dive pivots over the two
        # new SQL-view report models. Loads after quote_archive_views.xml so
        # menu_neon_migration_root (its parent) already exists.
        "views/historical_pivots_views.xml",
        # 17.0.1.4.0 — petty-cash reference (finance/director-gated menu).
        "views/petty_cash_views.xml",
        # 17.0.1.5.0 — suspense + undeposited reference (finance-gated menus).
        "views/susp_undep_views.xml",
        # 17.0.1.6.0 — FamCal job-history reference (all-internal-read menu).
        "views/job_history_views.xml",
        # 17.0.1.7.0 — crew roster reference (all-internal-read menu).
        "views/crew_member_views.xml",
        # 17.0.1.8.0 — wages reference (finance/director-gated menu).
        "views/wages_entry_views.xml",
        "views/res_partner_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
