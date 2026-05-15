#!/bin/bash
# P5.M2 hotfix regression — run all smoke suites end-to-end.
# Each smoke is invoked in its own odoo shell so registry state stays
# clean and rollback() at end of each smoke isolates side-effects.
set -u
DB="${1:-neon_crm}"
SMOKES=(
  p2m2 p2m3 p2m4 p2m5 p2m6
  p2m7 p2m7_5 p2m7_6 p2m7_7 p2m7_7_3 p2m7_8
  p2m8
  p3m1 p3m2 p3m3 p3m4 p3m5 p3m6 p3m7 p3m8
  p4m1 p4m2 p4m3 p4m4 p4m5_m6 p4m7 p4m8
  p5m1 p5m1_subtask_a p5m2 p5m3 p5m4 p5m5 p5m6 p5m7 p5m8 p5m9
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
