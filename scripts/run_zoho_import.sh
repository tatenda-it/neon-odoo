#!/usr/bin/env bash
# One-command Zoho reference import runner — run on the PROD host from the repo
# dir (where docker-compose.yml lives). Wraps STEP 1 (stage) + STEP 2 (dry-run)
# / STEP 4 (apply) of the runbook so the only difference between dry-run and the
# single write is one explicit argument.
#
# Usage:
#   scripts/run_zoho_import.sh           # stage + DRY-RUN (zero writes; re-run freely)
#   scripts/run_zoho_import.sh apply     # stage + APPLY (the single write)
#
# Source files (the Zoho-side export — Tatenda produces these; Claude Code/this
# script cannot reach Zoho):
#   $ZOHO_SRC/zoho_customers.json   (ALL Books customers, contact_type=customer, NO balances)
#   $ZOHO_SRC/zoho_estimates.json   (line-item level)
# ZOHO_SRC defaults to the current directory. They are staged into the running
# container at /tmp/zoho/ (the loader's ZOHO_DIR default), then the loader runs
# via `docker compose exec` (running container, so /tmp/zoho is reachable).
set -euo pipefail

MODE="${1:-dry}"
ZOHO_SRC="${ZOHO_SRC:-.}"
CUST="${ZOHO_SRC}/zoho_customers.json"
EST="${ZOHO_SRC}/zoho_estimates.json"
LOADER="scripts/import_zoho_reference.py"

if [[ "${MODE}" != "dry" && "${MODE}" != "apply" ]]; then
  echo "ERROR: argument must be 'dry' (default) or 'apply', got '${MODE}'." >&2
  exit 2
fi

for f in "${CUST}" "${EST}"; do
  if [[ ! -s "${f}" ]]; then
    echo "ERROR: missing or empty '${f}'." >&2
    echo "  Produce the Zoho export first (Books API get_estimate / line-item" >&2
    echo "  export + Books customers), in the agreed schema, then set ZOHO_SRC" >&2
    echo "  to its directory (or run from there)." >&2
    exit 1
  fi
done

echo "== STEP 1: stage into the container =="
docker compose exec -T odoo mkdir -p /tmp/zoho
docker compose cp "${CUST}" odoo:/tmp/zoho/zoho_customers.json
docker compose cp "${EST}"  odoo:/tmp/zoho/zoho_estimates.json
docker compose exec -T odoo ls -la /tmp/zoho/

if [[ "${MODE}" == "apply" ]]; then
  echo "== STEP 4: APPLY (the single write) =="
  docker compose exec -T -e ZOHO_IMPORT_APPLY=1 odoo \
    odoo shell -d neon_crm --no-http < "${LOADER}"
  echo "== APPLY done — ping the assistant for read-only verification vs baseline =="
else
  echo "== STEP 2: DRY-RUN (zero writes) =="
  docker compose exec -T odoo \
    odoo shell -d neon_crm --no-http < "${LOADER}"
  echo "== DRY-RUN done — paste the counts; gate before APPLY =="
fi
