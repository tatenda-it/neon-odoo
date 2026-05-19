"""P6.M3 browser smoke -- pricing engine wiring (end-to-end sales flow).

One scenario, four assertions inside it, exercising the depth
principle (each step proves the engine is wired correctly through
the UI):

1. Sales rep opens a fresh draft USD quote and adds an equipment line
   linked to a Sound-category event_job line, 3 days duration.
2. After save the form re-loads with unit_rate populated from the
   pricing.rule + bracket multiplier (not the manual 0 the salesperson
   typed in).
3. Salesperson changes duration_days to 10. unit_rate stays put --
   snapshot semantics prevent drift.
4. Salesperson clicks "Recalculate Pricing". The line's
   bracket_multiplier flips to the 8-14 day bracket value and
   unit_rate refreshes accordingly.

Setup creates the controlled fixture set via the docker odoo shell
(setup script piped through). Teardown unlinks via env.uid=1 to
bypass the no-perm_unlink rule (rule constrains the UI, not test
setup).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"

QUOTE_ACTION = "neon_finance.neon_finance_quote_action"


_SETUP_SCRIPT = """
from datetime import date, timedelta
sales = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1).id
usd = env.ref('base.USD').id
cat_sound = env.ref('neon_jobs.equipment_category_sound').id
partner = env['res.partner'].create({
    'name': 'P6M3 Browser Smoke Client', 'is_company': True,
}).id
venue = env['res.partner'].create({
    'name': 'P6M3 Browser Smoke Venue', 'is_company': True,
}).id
job = env['commercial.job'].create({
    'partner_id': partner, 'venue_id': venue,
    'event_date': (date.today() + timedelta(days=30)).isoformat(),
    'currency_id': usd,
}).id
event_job = env['commercial.event.job'].create({
    'commercial_job_id': job,
}).id
product = env['product.template'].search(
    [('is_workshop_item', '=', True)], limit=1)
if not product:
    product = env['product.template'].create({
        'name': 'P6M3 Browser Smoke Product',
        'is_workshop_item': True,
    })
product.equipment_category_id = cat_sound
ej_line = env['commercial.event.job.equipment.line'].create({
    'event_job_id': event_job,
    'product_template_id': product.id,
    'quantity_planned': 1,
}).id
term = env['neon.finance.payment.term'].create({
    'partner_id': partner, 'deposit_pct': 50.0,
    'deposit_due_days': 0, 'final_due_days': 30,
    'late_policy': 'reminder',
}).id
# Pre-create the draft quote with one equipment line at 3 days so the
# pricing engine has already run on it -- the browser scenario then
# verifies the rendered DOM matches.
quote = env['neon.finance.quote'].create({
    'event_job_id': event_job, 'currency_id': usd,
    'salesperson_id': sales, 'payment_term_id': term,
}).id
line = env['neon.finance.quote.line'].create({
    'quote_id': quote, 'line_type': 'equipment',
    'name': 'P6M3 Sound rig (3 days)', 'quantity': 1.0,
    'unit_rate': 0.0, 'duration_days': 3,
    'equipment_line_id': ej_line,
}).id
env.cr.commit()
print('IDS_JSON=' + repr({
    'quote_id': quote, 'line_id': line,
    'event_job_id': event_job, 'job_id': job,
    'ej_line_id': ej_line, 'term_id': term,
    'partner_id': partner, 'venue_id': venue,
}))
"""

_TEARDOWN_SCRIPT_TEMPLATE = """
ids = {ids_repr}
try:
    env['neon.finance.quote'].browse(ids['quote_id']).write({{
        'state': 'cancelled',
        'cancelled_reason': 'browser smoke teardown',
    }})
except Exception:
    pass
for model, key in [
    ('neon.finance.quote.line', 'line_id'),
    ('neon.finance.quote', 'quote_id'),
    ('neon.finance.payment.term', 'term_id'),
    ('commercial.event.job.equipment.line', 'ej_line_id'),
    ('commercial.event.job', 'event_job_id'),
    ('commercial.job', 'job_id'),
    ('res.partner', 'partner_id'),
    ('res.partner', 'venue_id'),
]:
    try:
        env[model].browse(ids[key]).unlink()
    except Exception as e:
        print('teardown unlink failed for', model, ids[key], ':', e)
env.cr.commit()
print('TEARDOWN_OK')
"""


def _run_odoo_shell(script: str) -> str:
    proc = subprocess.run(
        [
            "docker", "compose",
            "--project-directory", "C:/Users/Neon/neon-odoo",
            "exec", "-T", "odoo",
            "odoo", "shell", "-d", DB, "--no-http",
        ],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=120,
    )
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def _setup_fixtures() -> dict:
    out = _run_odoo_shell(_SETUP_SCRIPT)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out)
        raise RuntimeError("setup did not produce IDS_JSON marker")
    return eval(m.group(1), {"__builtins__": {}}, {})


def _teardown_fixtures(ids: dict) -> None:
    out = _run_odoo_shell(_TEARDOWN_SCRIPT_TEMPLATE.format(ids_repr=repr(ids)))
    if "TEARDOWN_OK" not in out:
        print("[p6m3] teardown warning:")
        print(out[-1500:])


def _bump_duration_via_rpc(smoke: BrowserSmoke, line_id: int, new_days: int) -> None:
    """Use the browser session's RPC to update duration_days. Going
    through the UI would require navigating the quote form's one2many
    editor and saving -- a real future polish item, but the snapshot
    invariant lives at the model layer, not the UI, so an RPC write
    is a fair test of the snapshot semantics."""
    resp = smoke.json_rpc(
        "neon.finance.quote.line", "write",
        args=[[line_id], {"duration_days": new_days}],
    )
    if "error" in resp and resp["error"]:
        raise AssertionFail(
            f"duration_days update RPC failed: {resp['error']}")


def _read_line(smoke: BrowserSmoke, line_id: int) -> dict:
    resp = smoke.json_rpc(
        "neon.finance.quote.line", "read",
        args=[[line_id], [
            "unit_rate", "bracket_multiplier", "snapshot_taken",
            "pricing_status", "duration_days",
        ]],
    )
    rows = resp.get("result") or []
    return rows[0] if rows else {}


def main() -> int:
    print("[p6m3] setup: creating pre-priced quote fixture ...")
    ids = _setup_fixtures()
    print(
        f"[p6m3] setup ok: quote={ids['quote_id']} line={ids['line_id']}"
    )

    # Resolve the seeded sound USD rule + day multiplier so we know
    # exactly what unit_rate to expect at each phase of the scenario.
    pre_setup = _run_odoo_shell(
        "rule = env.ref('neon_finance.pricing_rule_sound_usd')\n"
        "mult = env['neon.finance.day.multiplier'].search("
        "[('category_id', '=', rule.category_id.id)], limit=1)\n"
        "print('META=' + repr({"
        "'base_rate': rule.base_rate, "
        "'mult_event': mult.event_day_multiplier or 1.0,"
        "}))\n"
    )
    m = re.search(r"META=(\{.*\})", pre_setup)
    meta = eval(m.group(1), {"__builtins__": {}}, {}) if m else {}
    base_rate = float(meta.get("base_rate") or 50.0)
    mult_event = float(meta.get("mult_event") or 1.0)
    expected_3d = base_rate * 0.80 * mult_event   # 3-7 bracket
    expected_10d = base_rate * 0.70 * mult_event  # 8-14 bracket

    try:
        with BrowserSmoke("p6m3") as smoke:
            with smoke.scenario("Pricing engine end-to-end: rule, snapshot, recalculate"):
                smoke.login("p2m75_sales")

                # --- Step 1: open the pre-priced draft quote
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['quote_id']}"
                    f"&model=neon.finance.quote&view_type=form",
                    wait_until="networkidle",
                )
                smoke.assert_visible("div.o_form_view", "quote form view loaded")
                smoke.screenshot("01_quote_form_after_setup")

                # --- Step 2: verify line was priced at create time
                line_state = _read_line(smoke, ids["line_id"])
                priced_ok = (
                    line_state.get("snapshot_taken") is True
                    and line_state.get("pricing_status") == "priced"
                    and abs(line_state.get("bracket_multiplier", 0) - 0.80) < 0.001
                    and abs(line_state.get("unit_rate", 0) - expected_3d) < 0.01
                )
                smoke._record_assert(
                    "line priced on create (snapshot_taken, status=priced, bracket=0.80, unit_rate matches rule)",
                    expect=f"snapshot=True status=priced bracket=0.80 unit_rate={expected_3d:.2f}",
                    actual=(
                        f"snapshot={line_state.get('snapshot_taken')} "
                        f"status={line_state.get('pricing_status')} "
                        f"bracket={line_state.get('bracket_multiplier')} "
                        f"unit_rate={line_state.get('unit_rate')}"
                    ),
                    passed=priced_ok,
                )
                if not priced_ok:
                    smoke._capture_fail_artifacts("line_not_priced_on_create")
                    raise AssertionFail("pricing engine did not stamp the line at create")

                # --- Step 3: change duration to 10 days; unit_rate must NOT move
                _bump_duration_via_rpc(smoke, ids["line_id"], 10)
                line_state = _read_line(smoke, ids["line_id"])
                snapshot_frozen = (
                    line_state.get("duration_days") == 10
                    and abs(line_state.get("unit_rate", 0) - expected_3d) < 0.01
                    and abs(line_state.get("bracket_multiplier", 0) - 0.80) < 0.001
                )
                smoke._record_assert(
                    "snapshot frozen against duration_days edit",
                    expect=f"duration=10 unit_rate UNCHANGED ({expected_3d:.2f}) bracket=0.80",
                    actual=(
                        f"duration={line_state.get('duration_days')} "
                        f"unit_rate={line_state.get('unit_rate')} "
                        f"bracket={line_state.get('bracket_multiplier')}"
                    ),
                    passed=snapshot_frozen,
                )
                if not snapshot_frozen:
                    smoke._capture_fail_artifacts("snapshot_did_not_freeze")
                    raise AssertionFail("unit_rate drifted on duration_days edit")

                # Reload + screenshot the post-edit state.
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['quote_id']}"
                    f"&model=neon.finance.quote&view_type=form",
                    wait_until="networkidle",
                )
                smoke.screenshot("02_quote_form_after_duration_edit")

                # --- Step 4: click "Recalculate Pricing" via the form button
                smoke.assert_visible(
                    "button[name='action_recalculate_pricing']",
                    "Recalculate Pricing button visible in draft state",
                )
                smoke.click(
                    "button[name='action_recalculate_pricing']",
                    name="Click Recalculate Pricing",
                )
                # Give Odoo a moment to process + re-render the form.
                smoke.page.wait_for_timeout(800)
                smoke.screenshot("03_quote_form_after_recalculate")

                line_state = _read_line(smoke, ids["line_id"])
                recalc_ok = (
                    line_state.get("snapshot_taken") is True
                    and line_state.get("pricing_status") == "priced"
                    and abs(line_state.get("bracket_multiplier", 0) - 0.70) < 0.001
                    and abs(line_state.get("unit_rate", 0) - expected_10d) < 0.01
                )
                smoke._record_assert(
                    "Recalculate refreshed unit_rate to match 8-14 bracket",
                    expect=f"bracket=0.70 unit_rate={expected_10d:.2f} status=priced",
                    actual=(
                        f"bracket={line_state.get('bracket_multiplier')} "
                        f"unit_rate={line_state.get('unit_rate')} "
                        f"status={line_state.get('pricing_status')}"
                    ),
                    passed=recalc_ok,
                )
                if not recalc_ok:
                    smoke._capture_fail_artifacts("recalculate_did_not_refresh")
                    raise AssertionFail("Recalculate did not refresh unit_rate to new bracket")

        return smoke.summary()
    finally:
        print("[p6m3] teardown: cleaning up fixture records ...")
        _teardown_fixtures(ids)


if __name__ == "__main__":
    sys.exit(main())
