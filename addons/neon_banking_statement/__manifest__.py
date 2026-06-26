# -*- coding: utf-8 -*-
{
    "name": "Neon Banking Statement",
    "version": "17.0.1.4.0",
    "summary": "Per-account running-ledger statement view + Add-Transaction quick entry",
    "description": """
A READ/VIEW over the existing ledger (account.move.line) presenting a per-
account running-balance statement in Neon's words: Date | Details | Acc Code |
Dr | Cr | Balance. Petty Cash first; reusable for CABS (USD), CABS (ZWG),
Suspense via per-account actions over the shared view.

STAGE 2 adds "Add Transaction" Zoho-style quick-entry wizards on cash/bank
accounts -- Add Expense (money out) and Add Replenishment (money in). Each posts
a normal Odoo journal entry underneath (native account.move), with NO suspense,
NO reconcile step and NO debit/credit/journal jargon shown to the bookkeeper.
The posted move appears immediately in the running-ledger statement above.

STAGE 3 completes the typed quick-entry set, all reusing the Stage-2 pattern
(on-view header buttons -> short dialog -> native posting, no jargon):
  Money out: Pay a Bill (Vendor Payment), Vendor Advance, Owner/Directors
             Drawings, Commission.
  Money in:  Receive a Payment (Customer Receipt), Owner Contribution / Money In.
  Both ways: Transfer / Deposit (same-currency).
Vendor Payment + Customer Receipt route through Odoo's native
account.payment.register so the SCH- cross-currency guard stays active.
""",
    "category": "Neon/Finance",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    # neon_finance -> account + neon_core groups; neon_banking_labels -> the
    # "Statements" menu we nest under.
    "depends": ["neon_finance", "neon_banking_labels"],
    "data": [
        "security/ir.model.access.csv",
        "data/stage3_accounts.xml",
        "views/neon_banking_statement_views.xml",
        "views/neon_banking_frontdoor.xml",
        "wizards/neon_cash_wizards_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "neon_banking_statement/static/src/views/neon_statement_addtxn.js",
            "neon_banking_statement/static/src/views/neon_statement_addtxn.xml",
        ],
    },
    "installable": True,
    "application": False,
}
