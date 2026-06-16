# -*- coding: utf-8 -*-
"""
ZOHO FINANCE-HISTORY -> Odoo reference archives (gated; Tatenda runs at the gate).

Thin wrapper: reads two JSON files and calls neon.zoho.importer.run_finance.
ALL logic + schema live in addons/neon_migration/models/zoho_import.py +
finance_archive.py. Dry-run by default (ZERO writes); ZOHO_FINANCE_APPLY=1 to
apply. Idempotent (zoho_invoice_number / zoho_expense_id); reversible
(archivable). Partners are LINK-ONLY (already imported) — a missing customer is
reported, never created. Also populates quote.archive.zoho_invoice_number from
the invoice->estimate links (the parked won-link patch, folded in).

INERT: invoices are NOT account.move, expenses are NOT vendor bills; NO ledger /
AR / AP / VAT posting. VAT is stored as reference data only.

Files (default dir /tmp/zoho, override with ZOHO_DIR):
  zoho_invoices.json   zoho_expenses.json

Run (two-step, gated; `exec` so /tmp/zoho is reachable):
  # land the files: docker compose cp ./zoho_invoices.json odoo:/tmp/zoho/...
  # 1) DRY-RUN (default):
  docker compose exec -T odoo odoo shell -d neon_crm --no-http < scripts/import_zoho_finance.py
  # 2) APPLY (after the human gate on the printed counts):
  docker compose exec -T -e ZOHO_FINANCE_APPLY=1 odoo odoo shell -d neon_crm --no-http < scripts/import_zoho_finance.py
"""
import json
import os

APPLY = os.environ.get("ZOHO_FINANCE_APPLY") == "1"
ZOHO_DIR = os.environ.get("ZOHO_DIR", "/tmp/zoho")


def _load(fname):
    path = os.path.join(ZOHO_DIR, fname)
    if not os.path.exists(path):
        print("MISSING: %s (skipping — provide it to import)" % path)
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("%s must be a JSON list" % fname)
    return data


invoices = _load("zoho_invoices.json")
expenses = _load("zoho_expenses.json")

print("=" * 70)
print("ZOHO FINANCE-HISTORY IMPORT  (APPLY=%s, dir=%s)" % (APPLY, ZOHO_DIR))
print("source: %d invoices, %d expenses" % (len(invoices), len(expenses)))
print("=" * 70)

report = env["neon.zoho.importer"].sudo().run_finance(
    invoices, expenses, apply=APPLY)

if APPLY:
    env.cr.commit()

iv, ex = report["invoices"], report["expenses"]
print("\nINVOICES:  created=%d  skipped-existing=%d" % (
    iv["created"], iv["skipped_existing"]))
print("  buckets: paid=%d  unpaid=%d  void=%d" % (
    iv["paid"], iv["unpaid"], iv["void"]))
print("  skipped-UNMATCHED-customer=%d  (the GATE — review before APPLY)"
      % iv["skipped_unmatched_customer"])
print("  no-customer-id=%d (imported unlinked)" % iv["no_customer_id"])
print("\nEXPENSES:  created=%d  skipped-existing=%d  billable=%d  "
      "billable-customer-not-found=%d" % (
          ex["created"], ex["skipped_existing"], ex["billable"],
          ex["billable_customer_not_found"]))
print("\nWON-LINK: quote.archive.zoho_invoice_number %s = %d"
      % ("populated" if APPLY else "WOULD populate", report["won_links_populated"]))
print("currency: %s" % ", ".join(
    "%s=%d" % (k, v) for k, v in sorted(report["currency"].items())))

if report["unmatched_customers"]:
    print("\n⚠️  invoices referencing an UNKNOWN customer id (%d): %s%s"
          % (len(report["unmatched_customers"]),
             ", ".join(report["unmatched_customers"][:10]),
             " …" if len(report["unmatched_customers"]) > 10 else ""))
if report["unmatched_salespeople"]:
    print("⚠️  salesperson labels stored as free-text: %s"
          % ", ".join(report["unmatched_salespeople"]))
if report["unknown_status"]:
    print("⚠️  unknown invoice statuses -> bucketed 'unpaid': %s"
          % ", ".join(report["unknown_status"]))
for w in report["warnings"]:
    print("⚠️  %s" % w)

print("\n" + ("APPLIED + committed." if APPLY
              else "DRY-RUN — no writes. Re-run with ZOHO_FINANCE_APPLY=1."))
