# -*- coding: utf-8 -*-
{
    "name": "Neon MIS Reports",
    "version": "17.0.1.0.0",
    "summary": "P&L / Balance Sheet / Cash Flow (OCA mis_builder) under the Reporting launcher",
    "description": """
Surfaces the three OCA mis_builder financial reports under Neon's "Reporting"
launcher (Build 1 Part 3) alongside the account_financial_report working-papers:
  - Profit & Loss   (mis_template_financial_report.report_pl)
  - Balance Sheet   (mis_template_financial_report.report_bs)
  - Cash Flow       (mis_builder_cash_flow)

Reporting only -- read-only over the ledger. Adds two report INSTANCES (P&L, BS;
the Cash Flow instance ships with mis_builder_cash_flow) and one menu entry that
opens the MIS report list. No posting/account/guard/SCH-/security change.

⚠️ The report LINE MAPPINGS are the OCA templates' account_type expressions and
the period configs here are a sensible default -- both need Robin/the
bookkeeper's accounting sign-off (Claude verifies render + arithmetic tie-out,
not accounting-correctness for Neon).
""",
    "category": "Neon/Finance",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    "depends": [
        "mis_template_financial_report",
        "mis_builder_cash_flow",
        "neon_banking_labels",
    ],
    "data": [
        "data/mis_instances.xml",
        "data/reporting_menu_mis.xml",
    ],
    "installable": True,
    "application": False,
}
