# -*- coding: utf-8 -*-
"""
ZOHO -> ODOO reference import (gated one-shot, run at the human gate by Tatenda).

Thin wrapper: reads two JSON files exported Zoho-side and calls the import
service (neon.zoho.importer.run). ALL logic + the file schema live in
addons/neon_migration/models/zoho_import.py. Dry-run by default (ZERO writes);
ZOHO_IMPORT_APPLY=1 to apply. Idempotent (get-or-create on the Zoho estimate
number / customer source id); reversible (archive rows are archivable).

Files (default dir /tmp/zoho, override with ZOHO_DIR):
  zoho_customers.json   — list per the customers schema
  zoho_estimates.json   — list per the estimates schema (line-item level)

Run (two-step, gated; use `exec` so the dir is reachable in the running box):
  # land the files on prod first, e.g.:
  #   docker compose cp ./zoho_customers.json odoo:/tmp/zoho/zoho_customers.json
  #   docker compose cp ./zoho_estimates.json odoo:/tmp/zoho/zoho_estimates.json
  # 1) DRY-RUN (default) — counts only, no writes:
  docker compose exec -T odoo odoo shell -d neon_crm --no-http < scripts/import_zoho_reference.py
  # 2) APPLY (after the human gate on the printed counts):
  docker compose exec -T -e ZOHO_IMPORT_APPLY=1 odoo odoo shell -d neon_crm --no-http < scripts/import_zoho_reference.py

Re-run safe: a second dry-run after APPLY reports all-matched / zero-new.
Constraints: NO ledger / invoices / VAT / balances; NO QUO-sequence consumption;
NO approval / WhatsApp / cron side effects (the archive model touches none).
"""
import json
import os

APPLY = os.environ.get("ZOHO_IMPORT_APPLY") == "1"
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


customers = _load("zoho_customers.json")
estimates = _load("zoho_estimates.json")

print("=" * 70)
print("ZOHO REFERENCE IMPORT  (APPLY=%s, dir=%s)" % (APPLY, ZOHO_DIR))
print("source: %d customers, %d estimates" % (len(customers), len(estimates)))
print("=" * 70)

report = env["neon.zoho.importer"].sudo().run(customers, estimates, apply=APPLY)

if APPLY:
    env.cr.commit()

p, q = report["partners"], report["quotes"]
print("\nPARTNERS (pass A):")
print("  matched=%d  created=%d  flagged-for-review=%d  enriched=%d"
      % (p["matched"], p["created"], p["flagged_review"], p["enriched"]))
print("\nQUOTES (pass B):  created=%d  skipped-existing=%d"
      % (q["created"], q["skipped_existing"]))
print("  buckets: open=%d  historical=%d  won=%d  lost=%d"
      % (q["open"], q["historical"], q["won"], q["lost"]))
print("  currency: %s" % ", ".join(
    "%s=%d" % (k, v) for k, v in sorted(report["currency"].items())))

if report["unmatched_customers"]:
    print("\n⚠️  estimates referencing an UNKNOWN customer id (%d): %s%s"
          % (len(report["unmatched_customers"]),
             ", ".join(report["unmatched_customers"][:10]),
             " …" if len(report["unmatched_customers"]) > 10 else ""))
if report["unmatched_salespeople"]:
    print("⚠️  salesperson labels stored as free-text (no Odoo user): %s"
          % ", ".join(report["unmatched_salespeople"]))
if report["unknown_status"]:
    print("⚠️  unknown Zoho statuses -> bucketed 'historical': %s"
          % ", ".join(report["unknown_status"]))
for w in report["warnings"]:
    print("⚠️  %s" % w)

print("\n" + ("APPLIED + committed." if APPLY
              else "DRY-RUN — no writes. Re-run with ZOHO_IMPORT_APPLY=1."))
