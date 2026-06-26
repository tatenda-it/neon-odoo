# -*- coding: utf-8 -*-
{
    "name": "Neon Bank Statement Import (CABS CSV)",
    "version": "17.0.1.0.0",
    "summary": "Import CABS bank statement CSV into the CABS journals for reconciliation",
    "description": """
A small custom CSV importer for CABS bank statements (USD + ZWG), since the OCA
account_statement_import modules are not ported to Odoo 17.0. Parses the CABS
export layout (one mapping, both currencies) and creates a native
account.bank.statement + statement lines that land in the Reconciliation view.

CSV only (the bookkeeper exports the bank file as CSV; CABS provides CSV).
NOT PDF (OCR too fragile). .xlsx would need openpyxl in the image (deferred).

Mapping (validated against the real CABS files):
  header row located dynamically by signature
  (Post date,Reference,Narrative,Value Date,Debit,Credit,Closing Balance);
  Post date->date; Reference->ref; Narrative->payment_ref; Value Date->narration
  (no native value_date field); signed amount = Credit - Debit; allow negatives;
  comma-thousands + quotes stripped; "Balance at Period Start/End" set the
  statement opening/closing (not lines). Currency from the metadata row routes
  USD->CABS(USD) journal (acct 101401), ZWG->CABS(ZWG) journal (acct 101405).

Imported lines reconcile via account_reconcile_oca; the SCH- cross-currency
guard still applies on register. No posting-logic change.
""",
    "category": "Neon/Finance",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    "depends": ["account_statement_base", "neon_banking_labels", "neon_banking_statement"],
    "data": [
        "security/ir.model.access.csv",
        "wizards/neon_bank_statement_import_views.xml",
        "report/account_statement_report.xml",
    ],
    "installable": True,
    "application": False,
}
