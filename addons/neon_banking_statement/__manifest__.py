# -*- coding: utf-8 -*-
{
    "name": "Neon Banking Statement",
    "version": "17.0.1.0.0",
    "summary": "Per-account running-ledger statement view (matches Neon's Petty Cash spreadsheet)",
    "description": """
A READ/VIEW over the existing ledger (account.move.line) presenting a per-
account running-balance statement in Neon's words: Date | Details | Acc Code |
Dr | Cr | Balance. READ-ONLY -- no new posting, no transaction creation, no
write-path change (Stage 2 handles entry). Petty Cash first; reusable for
CABS (USD), CABS (ZWG), Suspense via per-account actions over the shared view.
""",
    "category": "Neon/Finance",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    # neon_finance -> account + neon_core groups; neon_banking_labels -> the
    # "Statements" menu we nest under.
    "depends": ["neon_finance", "neon_banking_labels"],
    "data": [
        "views/neon_banking_statement_views.xml",
    ],
    "installable": True,
    "application": False,
}
