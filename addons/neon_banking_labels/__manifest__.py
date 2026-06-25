# -*- coding: utf-8 -*-
{
    "name": "Neon Banking Labels",
    "version": "17.0.1.1.0",
    "summary": "Cosmetic relabels of Odoo accounting jargon to Neon's words (labels only)",
    "description": """
STAGE 0 of the Zoho-banking-UX project: relabel Odoo accounting/banking
terminology to the bookkeeper's words. COSMETIC ONLY -- no models, no fields,
no routing, no security, no workflow. Pure label overrides:
  - action name + view field/button `string=` overrides, scoped to the
    accounting/banking screens.

Reversible: the inherited VIEWS are this module's own records, so uninstalling
reverts those labels. (The one action-name override re-applies the original on a
later `-u account`.) xml-id based, additive.
""",
    "category": "Neon/UI",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    # account_statement_base owns the bank-statement-line views (the register
    # entry surface) -> depend on it so our inheriting views load after.
    "depends": ["account", "account_statement_base", "account_reconcile_oca"],
    "data": [
        "data/banking_labels.xml",
    ],
    "installable": True,
    "application": False,
}
