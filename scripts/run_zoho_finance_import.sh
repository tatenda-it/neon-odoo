#!/usr/bin/env bash
# One-command Zoho finance-history import runner — run on the PROD host from the
# repo dir. Wraps stage + dry-run / apply for invoices + expenses. The only
# difference between dry-run and the single write is the explicit `apply` arg.
#
# Usage:
#   scripts/run_zoho_finance_import.sh           # stage + DRY-RUN (zero writes)
#   scripts/run_zoho_finance_import.sh apply     # stage + APPLY (the single write)
#
# Source files (the Zoho-side export — produced by export_zoho_to_json.py with
# ZOHO_FINANCE=1 and the BETTER-ACCESS read-only creds):
#   $ZOHO_SRC/zoho_invoices.json   $ZOHO_SRC/zoho_expenses.json
# ZOHO_SRC defaults to the current dir; staged into the running container at
# /tmp/zoho/ (the loader's ZOHO_DIR default).
set -euo pipefail

MODE="${1:-dry}"
ZOHO_SRC="${ZOHO_SRC:-.}"
INV="${ZOHO_SRC}/zoho_invoices.json"
EXP="${ZOHO_SRC}/zoho_expenses.json"
LOADER="scripts/import_zoho_finance.py"

if [[ "${MODE}" != "dry" && "${MODE}" != "apply" ]]; then
  echo "ERROR: argument must be 'dry' (default) or 'apply', got '${MODE}'." >&2
  exit 2
fi

for f in "${INV}" "${EXP}"; do
  if [[ ! -s "${f}" ]]; then
    echo "ERROR: missing or empty '${f}'." >&2
    echo "  Produce the Zoho export first: ZOHO_FINANCE=1 python3" >&2
    echo "  scripts/export_zoho_to_json.py (BETTER-ACCESS read-only creds)." >&2
    exit 1
  fi
done

echo "== stage into the container =="
docker compose exec -T odoo mkdir -p /tmp/zoho
docker compose cp "${INV}" odoo:/tmp/zoho/zoho_invoices.json
docker compose cp "${EXP}" odoo:/tmp/zoho/zoho_expenses.json
docker compose exec -T odoo ls -la /tmp/zoho/

if [[ "${MODE}" == "apply" ]]; then
  echo "== APPLY (the single write) =="
  docker compose exec -T -e ZOHO_FINANCE_APPLY=1 odoo \
    odoo shell -d neon_crm --no-http < "${LOADER}"
  echo "== APPLY done — ping the assistant for read-only verification =="
else
  echo "== DRY-RUN (zero writes) =="
  docker compose exec -T odoo \
    odoo shell -d neon_crm --no-http < "${LOADER}"
  echo "== DRY-RUN done — paste the counts; gate before APPLY =="
fi
