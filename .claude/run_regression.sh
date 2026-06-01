#!/bin/bash
# P5.M2 hotfix regression — run all smoke suites end-to-end.
# Each smoke is invoked in its own odoo shell so registry state stays
# clean and rollback() at end of each smoke isolates side-effects.
set -u
DB="${1:-neon_crm}"
SMOKES=(
  p8a_xml_lint
  p2m2 p2m3 p2m4 p2m5 p2m6
  p2m7 p2m7_5 p2m7_6 p2m7_7 p2m7_7_3 p2m7_8
  p2m8
  p3m1 p3m2 p3m3 p3m4 p3m5 p3m6 p3m7 p3m8
  p4m1 p4m2 p4m3 p4m4 p4m5_m6 p4m7 p4m8
  p5m1 p5m1_subtask_a p5m2 p5m3 p5m4 p5m5 p5m6 p5m7 p5m8 p5m9 p5m10
  p6m1 p6m2 p6m3 p6m4 p6m5 p6m6 p6m7 p6m8 p6m9 p6m10 p6m11
  p7a_m1 p7a_m2 p7a_m3 p7a_m4 p7a_m5 p7a_m6 p7a_m7 p7a_m8 p7a_m9 p7a_m10 p7a_m11 p7a_m12 p7a_m12_1
  p7b_m1 p7b_m2 p7b_m3 p7b_m4 p7b_m5 p7b_m6 p7b_m7 p7b_m8 p7b_m9 p7b_m10 p7b_m11 p7b_m12
  p7b_integration
  p7e_m1 p7e_m2 p7e_m3 p7e_m4 p7e_m5 p7e_m6 p7e_m7 p7e_m8 p7e_m9 p7e_m10 p7e_m11 p7e_m12 p7e_m13
  p7e_integration
  p7c_m1 p7c_m2 p7c_m3 p7c_m4 p7c_m5 p7c_m6 p7c_m7
  p7c_integration
  p7d_m1 p7d_m2 p7d_m3 p7d_m4 p7d_m5 p7d_m6 p7d_m7
  p7d_integration
  p8a_m1 p8a_m2 p8a_m3 p8a_m4 p8a_m5_targets p8a_m5_sales
  p8a_hygiene_tz p8a_m6_finance p8a_m6_zig_rate
  p8a_m7_alerts p8a_m7_dismissal
  p8a_m8_tasks
  p8a_m9_digest
  p8a_m10_exports
  p8a_m11_insights
  p8b_m1_sales p8b_m2_bookkeeper p8b_m3_lead_tech
  p8b_m4_edit_layout p8b_m5_brand_separator
  p9m1_venue_geocode p9m1_1_drop_pin
  p9m2_pin_modal
  p9m3_multi_map
  p12m1_chat
  p12m1_1_chat
  p12m1_1_1_chat
  p12m2_write
  pb1_datamodel
  pb2_conflict
  pb13_docgen
  pb3_deployment_plan
  pb14_inventory_load
  pb14b_legacy_migration
  pb4_subhire
  phr_r1a
  phr_r1b_1
  phr_r1b_2
  phr_r2
  phr_r3a
)
SCRIPT_DIR="$(dirname "$0")"
TOTAL_PASSED=0
TOTAL=0
FAILED_SUITES=()
for s in "${SMOKES[@]}"; do
  SF="${SCRIPT_DIR}/${s}_smoke.py"
  [[ -f "$SF" ]] || { echo "MISSING: $SF"; continue; }
  RAW=$(docker compose --project-directory C:/Users/Neon/neon-odoo \
      exec -T odoo odoo shell -d "$DB" --no-http < "$SF" 2>&1)
  LINE=$(echo "$RAW" | grep -E "^Total: [0-9]+/[0-9]+ passed" | tail -1)
  if [[ -z "$LINE" ]]; then
    echo "[$s] NO SUMMARY LINE — output tail:"
    echo "$RAW" | tail -5
    FAILED_SUITES+=("$s")
    continue
  fi
  PASSED=$(echo "$LINE" | awk '{print $2}' | cut -d/ -f1)
  TOTAL_S=$(echo "$LINE" | awk '{print $2}' | cut -d/ -f2)
  TOTAL_PASSED=$((TOTAL_PASSED + PASSED))
  TOTAL=$((TOTAL + TOTAL_S))
  if [[ "$PASSED" != "$TOTAL_S" ]]; then
    FAILED_SUITES+=("$s ($PASSED/$TOTAL_S)")
    echo "[$s] $PASSED/$TOTAL_S FAIL"
  else
    echo "[$s] $PASSED/$TOTAL_S PASS"
  fi
done
echo
echo "================================================="
echo "REGRESSION TOTAL: $TOTAL_PASSED/$TOTAL"
if [[ ${#FAILED_SUITES[@]} -gt 0 ]]; then
  echo "FAILED SUITES:"
  printf '  - %s\n' "${FAILED_SUITES[@]}"
  exit 1
fi

# -------------------------------------------------------------------
# Browser-smoke gate -- runs AFTER all in-process Python smokes pass.
# Hits the live HTTP surface (http://localhost:8069) with headless
# Chromium via Playwright, exercising menu visibility + action depth
# for each milestone's relevant role tiers.
#
# Failure aborts the pipeline with the same exit-1 discipline as the
# Python smokes above; screenshots + DOM snippets + diagnosis for
# any failing assertion land in .claude/smoke-output/<smoke>/
# <YYYY-MM-DD_HHMMSS>/. See .claude/README.md "Browser smokes".
# -------------------------------------------------------------------
echo
echo "================================================="
echo "BROWSER SMOKES (Playwright, headless)"
echo "================================================="
BROWSER_SMOKES=(p6m1 p6m2 p6m3 p6m4 p6m5 p6m6 p6m7 p6m8 p6m9 p6m10 p6m11 p6_predeploy_fixes p7a_m1 p7a_m2 p7a_m3 p7a_m4 p7a_m5 p7a_m6 p7a_m7 p7a_m8 p7a_m9 p7a_m10 p7a_m11 p7a_m12 p7a_m12_1 p8a_m1m3 p8a_m4m5 p8a_m6 p8a_m7 p8a_m8 p8a_m9 p8a_m10 p8a_m11 p8a_m12 p8b p8b_m4 p9m1 p9m1_1 p9m2_pin_modal p9m3_multi_map p12m1_chat p12m1_1_chat p12m2_write pb1_datamodel pb2_conflict pb13_docgen pb3_deployment_plan pb4_subhire pb14b_legacy_migration phr_r1a phr_r1b phr_r2 phr_r3a)
VENV_PY="${SCRIPT_DIR}/.venv-browser/Scripts/python.exe"
if [[ ! -x "$VENV_PY" ]] && [[ ! -f "$VENV_PY" ]]; then
  echo "MISSING venv: $VENV_PY"
  echo "  Set up per .claude/README.md 'Browser smokes / one-time install'."
  exit 1
fi
BROWSER_FAILED=()
for s in "${BROWSER_SMOKES[@]}"; do
  SF="${SCRIPT_DIR}/${s}_browser_smoke.py"
  [[ -f "$SF" ]] || { echo "MISSING: $SF"; BROWSER_FAILED+=("$s (missing)"); continue; }
  if "$VENV_PY" "$SF"; then
    echo "[$s] browser PASS"
  else
    echo "[$s] browser FAIL"
    BROWSER_FAILED+=("$s")
  fi
done
if [[ ${#BROWSER_FAILED[@]} -gt 0 ]]; then
  echo
  echo "FAILED BROWSER SMOKES:"
  printf '  - %s\n' "${BROWSER_FAILED[@]}"
  echo "Inspect screenshots and DOM snippets under .claude/smoke-output/"
  exit 1
fi
echo
echo "ALL GATES PASSED."
