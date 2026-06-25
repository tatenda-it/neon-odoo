# -*- coding: utf-8 -*-
{
    "name": "Neon Weekly Budget",
    "version": "17.0.1.0.0",
    "summary": "Weekly cash-planning sheet (replaces the Excel 'Weekly Budget' tabs)",
    "description": """
A standalone planning model that replaces Neon's "Weekly Budget" Excel sheet:
weeks holding planned/paid lines in the business's own words. PLANNING ONLY --
no link to the accounting ledger, payments, or the SCH- engine (planned-vs-
actual reconciliation is a deferred v2).
""",
    "category": "Neon/Finance",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    # neon_finance pulls account + neon_core -> gives us the finance/superuser
    # groups used for the menu + ACL gating.
    "depends": ["neon_finance"],
    "data": [
        "security/ir.model.access.csv",
        "views/neon_weekly_budget_views.xml",
    ],
    "installable": True,
    "application": False,
}
