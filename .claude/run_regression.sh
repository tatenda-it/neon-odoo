#!/bin/bash
# P5.M2 hotfix regression — run all smoke suites end-to-end.
# Each smoke is invoked in its own odoo shell so registry state stays
# clean and rollback() at end of each smoke isolates side-effects.
set -u
DB="${1:-neon_crm}"

# ===================================================================
# CONCURRENCY GUARD (baked in 2026-06-22 — retires the 5-corruption class).
# See reference_regression_concurrency_quiescence. The shared resource two
# Claude sessions both hit is the neon-odoo-app CONTAINER; the ONLY reliable
# idle/foreign signal is the count of `odoo shell` PROCESSES inside it (host
# ps + pg state='active' are both blind across Git Bash sessions on Windows).
#   (1) edit-immunity : re-exec from a stable /tmp snapshot so a mid-run edit
#                       of THIS file can't shift bash's read offsets + crash it
#   (2) preflight     : refuse to launch unless the container has ZERO odoo
#                       shells, sustained (a single 0 can be a between-suites gap)
#   (3) watchdog      : background poll; a regression uses at most ONE shell at
#                       a time, so >=2 (sustained) = a FOREIGN run overlapped ->
#                       kill this run + write ABORTED_FOREIGN_SHELL (verdict VOID)
#   (4) cleanup       : EXIT trap kills the watchdog + removes the snapshot, so
#                       no orphaned poll process / temp file is left behind
# ===================================================================
PROJECT_DIR="C:/Users/Neon/neon-odoo"

# (1) edit-immunity: snapshot self to /tmp and re-exec the COPY -----
if [[ -z "${_REGRESSION_STABLE:-}" ]]; then
  _REGRESSION_ORIG_DIR="$(cd "$(dirname "$0")" && pwd)"
  _stable="$(mktemp "${TMPDIR:-/tmp}/run_regression_stable.XXXXXX.sh" 2>/dev/null \
            || echo "${TMPDIR:-/tmp}/run_regression_stable_$$.sh")"
  cp "$0" "$_stable"
  export _REGRESSION_STABLE="$_stable"
  export _REGRESSION_ORIG_DIR
  exec bash "$_stable" "$@"
fi

# count of odoo-shell processes in the container (THE reliable signal).
# `docker compose top` lists CONTAINER processes only; the persistent HTTP
# server is `odoo --db_host ...` (no "shell"), so this matches only the
# `odoo shell -d ...` smoke invocations. The `top`/grep run on the host, so
# there is no self-match to filter.
shell_count() {
  docker compose --project-directory "$PROJECT_DIR" top odoo 2>/dev/null \
    | grep -E "odoo[[:space:]]+shell|[[:space:]]shell[[:space:]]+-d" \
    | wc -l | tr -d '[:space:]'
}

# (4) self-cleanup on ANY exit — set EARLY (before the preflight) so even a
#     preflight refusal removes the /tmp snapshot. WATCHDOG_PID is guarded so
#     the trap is safe before the watchdog is started.
_cleanup() {
  [[ -n "${WATCHDOG_PID:-}" ]] && kill "${WATCHDOG_PID}" 2>/dev/null
  [[ -n "${_REGRESSION_STABLE:-}" && -f "${_REGRESSION_STABLE}" ]] \
    && rm -f "${_REGRESSION_STABLE}" 2>/dev/null
}
trap _cleanup EXIT

# (2) preflight idle gate ------------------------------------------
echo "[guard] preflight: requiring ZERO container odoo shells, sustained ..."
for _t in 1 2 3 4; do
  _c="$(shell_count)"
  if [[ "${_c:-0}" != "0" ]]; then
    echo "ABORT: ${_c} odoo shell(s) already running in the container."
    echo "       A regression is in progress or the container is not idle —"
    echo "       refusing to start, to avoid concurrent-run corruption."
    echo "       (Reliable idle signal = ZERO container odoo shells, sustained;"
    echo "        wait for the other run to finish, then relaunch.)"
    exit 3
  fi
  sleep 3
done
echo "[guard] preflight PASSED — container idle (0 odoo shells over 4 ticks)."

# (3) foreign-shell watchdog (background) --------------------------
MAIN_PID=$$
_watchdog() {
  local hits=0 c
  while true; do
    sleep 4
    c="$(shell_count)"
    if [[ "${c:-0}" -ge 2 ]]; then
      hits=$((hits + 1))                       # require 2 sustained ticks so a
      if [[ "$hits" -ge 2 ]]; then             # sub-second suite handoff can't
        echo ""                                # false-trip the abort
        echo "ABORTED_FOREIGN_SHELL: ${c} concurrent container odoo shells detected"
        echo "  -> a second regression overlapped this run. VERDICT VOID."
        echo "  (no REGRESSION TOTAL emitted; re-run solo in a clean window.)"
        kill -9 "$MAIN_PID" 2>/dev/null
        rm -f "${_REGRESSION_STABLE}" 2>/dev/null
        exit 99
      fi
    else
      hits=0
    fi
  done
}
_watchdog &
WATCHDOG_PID=$!

SMOKES=(
  p8a_xml_lint
  p2m2 p2m3 p2m4 p2m5 p2m6
  p2m7 p2m7_5 p2m7_6 p2m7_7 p2m7_7_3 p2m7_8
  p2m8
  p3m1 p3m2 p3m3 p3m4 p3m5 p3m6 p3m7 p3m8
  p4m1 p4m2 p4m3 p4m4 p4m4_escfix p4m5_m6 p4m7 p4m8
  p5m1 p5m1_subtask_a p5m2 p5m3 p5m4 p5m5 p5m6 p5m7 p5m8 p5m9 p5m10
  p5m11_quantity_reservation
  p6m1 p6m2 p6m3 p6m4 p6m5 p6m6 p6m7 p6m8 p6m9 p6m10 p6m11
  fixs1_quote_picker
  quoteux1
  quoteux1b
  quoteux2
  quoteux3
  quoteux3b
  reppriced_pdf
  wa12cold_pick
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
  dash_dualrole
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
  pb14c_quantity_on_hand
  pb14d_maintenance_tile
  pb4_subhire
  phr_r1a
  phr_r1b_1
  phr_r1b_2
  phr_r2
  phr_r3a
  phr_r3b_c1_dashboard_hr_lens
  phr_r3b_c1_1_hr_panels
  phr_r3b_c2_performance_reviews
  phr_r3b_c3_licence_class
  phr_r3b_c4_housekeeping
  phr_hr_render
  p7f
  p7g
  p7i
  p7j
  p7k
  p7m
  p7l
  pb11_status
  pwa1_interactive
  pwa2_crew_ops
  pwa3_readiness
  pwa4_dual_role
  pwa5_client_lane
  pwa6_equipment
  pwa6_1_face3_dispatch
  pwa6_2_finalize_dispatch
  pwa7_crew_selection
  pwa8_availability
  pwa9_crm_matching
  pwa10_feedback
  pwa11_insights
  pwa12_quote
  pwa12_6_structured
  pwa12_7_template
  pwa_copilot_resilience
  pneon_library
  pimport_zoho_reference
  pimport_finance
  pimport_rollup
  phist_intel
  ppetty_cash
  psusp_undep
  pfamcal
  pcrew
  pwages
  pcollections
  pclient_intel
  pdemand_intel
  pwinloss_intel
)

# Test hook (default off): SMOKES_OVERRIDE="a b c" runs only those Python
# suites and skips the browser gate — used to prove the concurrency guard
# without a full 30-min run. Production runs (no override) are unchanged.
if [[ -n "${SMOKES_OVERRIDE:-}" ]]; then
  read -ra SMOKES <<< "${SMOKES_OVERRIDE}"
  echo "[guard] SMOKES_OVERRIDE active (${#SMOKES[@]} suite(s)): ${SMOKES[*]}"
fi

# Pinned to the ORIGINAL .claude dir (we re-exec from a /tmp snapshot, so $0
# is the snapshot path, not where the *_smoke.py files live).
SCRIPT_DIR="${_REGRESSION_ORIG_DIR:-$(cd "$(dirname "$0")" && pwd)}"
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

# Test hook: in SMOKES_OVERRIDE mode, skip the browser gate (the guard proof
# doesn't need it) and exit clean now that the Python suites passed.
if [[ -n "${SMOKES_OVERRIDE:-}" ]]; then
  echo "[guard] SMOKES_OVERRIDE set — skipping browser gate (test mode); done."
  exit 0
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
BROWSER_SMOKES=(p6m1 p6m2 p6m3 p6m4 p6m5 p6m6 p6m7 p6m8 p6m9 p6m10 p6m11 p6_predeploy_fixes p7a_m1 p7a_m2 p7a_m3 p7a_m4 p7a_m5 p7a_m6 p7a_m7 p7a_m8 p7a_m9 p7a_m10 p7a_m11 p7a_m12 p7a_m12_1 p8a_m1m3 p8a_m4m5 p8a_m6 p8a_m7 p8a_m8 p8a_m9 p8a_m10 p8a_m11 p8a_m12 p8b p8b_m4 p9m1 p9m1_1 p9m2_pin_modal p9m3_multi_map p12m1_chat p12m1_1_chat p12m2_write pb1_datamodel pb2_conflict pb13_docgen pb3_deployment_plan pb14c_quantity_on_hand pb14d_maintenance_tile pb4_subhire phr_r1a phr_r1b phr_r2 phr_r3a phr_r3b phr_hr_render p7f p7g p7h p7i p7j p7k p7m p7l pb11_status phist_intel ppetty_cash psusp_undep pfamcal pcrew pwages pcollections pclient_intel pdemand_intel pwinloss_intel fixs1_quote_picker quoteux1 quoteux1b quoteux2 quoteux3 quoteux3b dash_dualrole dash_scroll product_saleprice_hide)

# P7i: ensure the committed browser fixture (enrolled p7i_blearner +
# deterministic MC questions on M01 + reset completion) before the
# learner-facing quiz browser smoke logs in. Idempotent; commits.
docker compose --project-directory C:/Users/Neon/neon-odoo \
    exec -T odoo odoo shell -d "$DB" --no-http \
    < "${SCRIPT_DIR}/p7i_browser_setup.py" >/dev/null 2>&1 || true

# P7k: reset the dedicated P7K lesson to the broken document state then
# run it through the real document->article transform (apply=True) so the
# render smoke renders a genuinely-converted lesson. Idempotent; commits.
docker compose --project-directory C:/Users/Neon/neon-odoo \
    exec -T odoo odoo shell -d "$DB" --no-http \
    < "${SCRIPT_DIR}/p7k_browser_setup.py" >/dev/null 2>&1 || true

# P7m: seed two lessons + apply the real transform ops (Quick Reference:
# prefix + the source-brief find/replace) so the render smoke checks
# genuinely-transformed content. Idempotent; commits.
docker compose --project-directory C:/Users/Neon/neon-odoo \
    exec -T odoo odoo shell -d "$DB" --no-http \
    < "${SCRIPT_DIR}/p7m_browser_setup.py" >/dev/null 2>&1 || true

# P7l: seed two dedicated lessons in the dead-iframe state then run them
# through the real video->search-prompt transform (convert_html, scoped
# to each lesson) so the smoke renders genuinely-converted lessons.
# Idempotent; commits. Real-data-safe (only the P7L lessons are touched).
docker compose --project-directory C:/Users/Neon/neon-odoo \
    exec -T odoo odoo shell -d "$DB" --no-http \
    < "${SCRIPT_DIR}/p7l_browser_setup.py" >/dev/null 2>&1 || true

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
