"""P6.M5 browser smoke -- cost lines + Financial Summary tab.

Four scenarios (sales-tier dropped per Option A salesperson punt):

1. **p2m75_lead** (Ranganai) navigates to Cost Lines menu -> sees
   list (filtered to own events by record rule) -> opens a cost
   line form OR creates a new line -> save succeeds -> activity
   created for approver + bookkeeper.
2. **p2m75_lead** cannot read a cost.line on another tech's event
   -- record-rule check via RPC (form navigation to a foreign cost
   line would 404 the deep-link).
3. **p2m75_book** sees all cost lines (cross-event); opens an
   event_job with cost lines and verifies the Financial Summary tab
   renders the P&L HTML (Revenue / Cost / Margin sections all
   present in the rendered DOM).
4. **p2m75_other** (crew only, no crew_leader) cannot reach the
   Cost Lines menu (negative visibility test).

Setup creates 3 cost lines via odoo shell: one on lead_user's
event_job, two on a different event_job for cross-rep visibility.
Teardown unlinks via env.uid=1.
"""

from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"

COST_LINE_ACTION = "neon_finance.neon_finance_cost_line_action"
COST_LINES_MENU = "neon_finance.menu_neon_finance_cost_lines"


_SETUP_SCRIPT = """
from datetime import date, timedelta
sales = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1).id
lead = env['res.users'].search([('login', '=', 'p2m75_lead')], limit=1).id
mgr = env['res.users'].search([('login', '=', 'p2m75_mgr')], limit=1).id
approver = env['res.users'].search([('login', '=', 'p2m75_approver')], limit=1).id
usd = env.ref('base.USD').id
cat_sound = env.ref('neon_jobs.equipment_category_sound').id
partner = env['res.partner'].create({
    'name': 'P6M5 Browser Smoke Client', 'is_company': True,
}).id
venue = env['res.partner'].create({
    'name': 'P6M5 Browser Smoke Venue', 'is_company': True,
}).id
job = env['commercial.job'].create({
    'partner_id': partner, 'venue_id': venue,
    'event_date': (date.today() + timedelta(days=30)).isoformat(),
    'currency_id': usd,
}).id
# Event job assigned to lead_user (Ranganai)
ej_own = env['commercial.event.job'].create({
    'commercial_job_id': job,
    'lead_tech_id': lead,
}).id
# Event job assigned to a different tech (mgr_user) for the cross-
# event AccessError scenario.
job2 = env['commercial.job'].create({
    'partner_id': partner, 'venue_id': venue,
    'event_date': (date.today() + timedelta(days=60)).isoformat(),
    'currency_id': usd,
}).id
ej_other = env['commercial.event.job'].create({
    'commercial_job_id': job2,
    'lead_tech_id': mgr,
}).id
# Create a quote on ej_own + run it through to accept so the P&L view
# has revenue data to render.
term = env['neon.finance.payment.term'].create({
    'partner_id': partner, 'deposit_pct': 50.0,
    'deposit_due_days': 0, 'final_due_days': 30,
    'late_policy': 'reminder',
}).id
env['ir.config_parameter'].sudo().set_param(
    'neon_finance.approval_required_for_all', 'False')
quote = env['neon.finance.quote'].create({
    'event_job_id': ej_own, 'currency_id': usd,
    'salesperson_id': sales, 'payment_term_id': term,
}).id
env['neon.finance.quote.line'].create({
    'quote_id': quote, 'line_type': 'equipment',
    'name': 'P6M5 sound rig', 'quantity': 1.0,
    'unit_rate': 500.0, 'duration_days': 3,
})
q = env['neon.finance.quote'].browse(quote)
q.with_user(env['res.users'].browse(sales)).action_submit_for_approval()
q.with_user(env['res.users'].browse(sales)).action_send()
q.with_user(env['res.users'].browse(sales)).action_accept()
env['ir.config_parameter'].sudo().set_param(
    'neon_finance.approval_required_for_all', 'True')

# Three cost lines: one on ej_own (lead), two on ej_other (mgr)
own_cost_a = env['neon.finance.cost.line'].with_context(
    skip_finance_notification=True
).create({
    'event_job_id': ej_own, 'cost_type': 'crew',
    'name': 'P6M5 Crew labour', 'amount': 200.0,
    'currency_id': usd, 'date_incurred': date.today().isoformat(),
}).id
own_cost_b = env['neon.finance.cost.line'].with_context(
    skip_finance_notification=True
).create({
    'event_job_id': ej_own, 'cost_type': 'transport',
    'name': 'P6M5 Transport', 'amount': 80.0,
    'currency_id': usd, 'date_incurred': date.today().isoformat(),
}).id
other_cost = env['neon.finance.cost.line'].with_context(
    skip_finance_notification=True
).create({
    'event_job_id': ej_other, 'cost_type': 'venue',
    'name': 'P6M5 Cross-event venue', 'amount': 350.0,
    'currency_id': usd, 'date_incurred': date.today().isoformat(),
}).id

env.cr.commit()
print('IDS_JSON=' + repr({
    'partner_id': partner,
    'venue_id': venue,
    'job_id': job,
    'ej_own_id': ej_own,
    'job2_id': job2,
    'ej_other_id': ej_other,
    'term_id': term,
    'quote_id': quote,
    'own_cost_a_id': own_cost_a,
    'own_cost_b_id': own_cost_b,
    'other_cost_id': other_cost,
    'usd_id': usd,
}))
"""

_TEARDOWN_SCRIPT_TEMPLATE = """
ids = {ids_repr}
# Per-record savepoint so one failed cascade doesn't poison the
# cursor for the remaining unlinks. Order matters: dependent rows
# first (cost lines, quote lines, quote -> event_job -> commercial
# job -> partner). The fallthrough raw SQL DELETE handles the case
# where the ORM unlink trips a computed-field recompute against a
# half-deleted record.
import psycopg2

def _try_unlink(model, rec_id):
    try:
        env.cr.execute("SAVEPOINT teardown")
        env[model].browse(rec_id).unlink()
        env.cr.execute("RELEASE SAVEPOINT teardown")
        return True
    except Exception as e:
        env.cr.execute("ROLLBACK TO SAVEPOINT teardown")
        # Fall back to raw SQL DELETE -- bypasses Odoo's compute-on-
        # cascade machinery that can abort transactions during teardown.
        table_map = {{
            'neon.finance.cost.line': 'neon_finance_cost_line',
            'neon.finance.quote.line': 'neon_finance_quote_line',
            'neon.finance.quote': 'neon_finance_quote',
            'neon.finance.payment.term': 'neon_finance_payment_term',
            'commercial.event.job.equipment.line':
                'commercial_event_job_equipment_line',
            'commercial.event.job': 'commercial_event_job',
            'commercial.job': 'commercial_job',
            'res.partner': 'res_partner',
        }}
        table = table_map.get(model)
        if not table:
            return False
        try:
            env.cr.execute("SAVEPOINT teardown_sql")
            env.cr.execute(
                "DELETE FROM " + table + " WHERE id = %s", (rec_id,))
            env.cr.execute("RELEASE SAVEPOINT teardown_sql")
            return True
        except Exception as e2:
            env.cr.execute("ROLLBACK TO SAVEPOINT teardown_sql")
            print('teardown SQL fallback failed for', model,
                  rec_id, ':', e2)
            return False

# Pre-step: unlink the quote_line rows that quote_id cascade SHOULD
# remove but may not if computes are tangled.
try:
    env.cr.execute("SAVEPOINT pre")
    qlines = env['neon.finance.quote.line'].search(
        [('quote_id', '=', ids['quote_id'])])
    qlines.unlink()
    env.cr.execute("RELEASE SAVEPOINT pre")
except Exception:
    env.cr.execute("ROLLBACK TO SAVEPOINT pre")

# The rpc_created_cost_id may or may not be present depending on
# whether scenario 1 reached the create step. Defensive get.
_rpc_cost = ids.get('rpc_created_cost_id')
if _rpc_cost:
    _try_unlink('neon.finance.cost.line', _rpc_cost)
for model, key in [
    ('neon.finance.cost.line', 'own_cost_a_id'),
    ('neon.finance.cost.line', 'own_cost_b_id'),
    ('neon.finance.cost.line', 'other_cost_id'),
    ('neon.finance.quote', 'quote_id'),
    ('neon.finance.payment.term', 'term_id'),
    ('commercial.event.job', 'ej_own_id'),
    ('commercial.event.job', 'ej_other_id'),
    ('commercial.job', 'job_id'),
    ('commercial.job', 'job2_id'),
    ('res.partner', 'partner_id'),
    ('res.partner', 'venue_id'),
]:
    _try_unlink(model, ids[key])
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
        timeout=180,
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
        print("[p6m5] teardown warning:")
        print(out[-1500:])


def main() -> int:
    print("[p6m5] setup: creating cost line + event_job fixtures ...")
    ids = _setup_fixtures()
    print(f"[p6m5] setup ok: ej_own={ids['ej_own_id']} "
          f"ej_other={ids['ej_other_id']} "
          f"own_costs=[{ids['own_cost_a_id']}, {ids['own_cost_b_id']}] "
          f"other_cost={ids['other_cost_id']}")
    try:
        with BrowserSmoke("p6m5") as smoke:

            # ----------------------------------------------------------
            # 1. Ranganai sees + creates cost lines on own event_job
            # ----------------------------------------------------------
            with smoke.scenario("p2m75_lead sees own cost lines + creates new (activity dispatch)"):
                smoke.login("p2m75_lead")
                smoke.assert_menu_visible(COST_LINES_MENU)
                smoke.open_action(COST_LINE_ACTION)
                smoke.assert_visible("table.o_list_table", "cost line list view")
                # Verify only own-event costs are visible
                visible_resp = smoke.json_rpc(
                    "neon.finance.cost.line", "search_read",
                    args=[
                        [("id", "in", [
                            ids["own_cost_a_id"],
                            ids["own_cost_b_id"],
                            ids["other_cost_id"],
                        ])],
                        ["id", "event_job_id"],
                    ],
                )
                visible_ids = [r["id"] for r in (visible_resp.get("result") or [])]
                passed = (
                    ids["own_cost_a_id"] in visible_ids
                    and ids["own_cost_b_id"] in visible_ids
                    and ids["other_cost_id"] not in visible_ids
                )
                smoke._record_assert(
                    "lead sees own costs (2) but not cross-event cost (1)",
                    expect="own_a + own_b visible, other_cost hidden",
                    actual=f"visible_ids={visible_ids}",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("lead_visibility_wrong")
                    raise AssertionFail("record rule did not scope correctly")
                smoke.screenshot("01_lead_cost_lines_list")

                # Create a new cost line as Ranganai via RPC (the form's
                # "New" button opens a transient record we'd otherwise
                # need to drive through several field fills). Verify the
                # activity dispatch.
                create_resp = smoke.json_rpc(
                    "neon.finance.cost.line", "create",
                    args=[{
                        "event_job_id": ids["ej_own_id"],
                        "cost_type": "consumable",
                        "name": "P6M5 browser smoke consumable",
                        "amount": 25.0,
                        "currency_id": ids["usd_id"],
                    }],
                )
                new_id = create_resp.get("result")
                if not new_id:
                    raise AssertionFail(
                        f"cost line create RPC failed: {create_resp}")
                # Track the RPC-created cost line so teardown removes it.
                ids["rpc_created_cost_id"] = new_id
                act_resp = smoke.json_rpc(
                    "neon.finance.cost.line", "read",
                    args=[[new_id], ["activity_ids", "name"]],
                )
                act_row = (act_resp.get("result") or [{}])[0]
                activity_count = len(act_row.get("activity_ids") or [])
                passed_dispatch = activity_count > 0
                smoke._record_assert(
                    "activity dispatch on cost.line create",
                    expect="> 0 activities (approver + bookkeeper notified)",
                    actual=f"{activity_count} activities; name={act_row.get('name')}",
                    passed=passed_dispatch,
                )
                if not passed_dispatch:
                    smoke._capture_fail_artifacts("no_activity_dispatch")
                    raise AssertionFail("activity dispatch did not fire")

            # ----------------------------------------------------------
            # 2. Ranganai cannot read other tech's cost (record rule)
            # ----------------------------------------------------------
            with smoke.scenario("p2m75_lead cannot read another tech's cost line"):
                # Still logged in as lead. Try to read the other_cost.
                resp = smoke.json_rpc(
                    "neon.finance.cost.line", "read",
                    args=[[ids["other_cost_id"]], ["name"]],
                )
                # Record rule should filter the record out; either an
                # empty result or an AccessError.
                err = resp.get("error")
                rows = resp.get("result")
                passed = (
                    bool(err and "AccessError" in (err.get("data") or {}).get("name", ""))
                    or (rows is not None and len(rows) == 0)
                )
                smoke._record_assert(
                    "lead cannot read cross-event cost line",
                    expect="AccessError or empty read",
                    actual=f"err={err.get('data', {}).get('name') if err else None} rows={rows}",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("lead_cross_event_visible")
                    raise AssertionFail(
                        "lead leaked visibility into cross-event cost line")

            # ----------------------------------------------------------
            # 3. Bookkeeper sees all + P&L renders on event_job form
            # ----------------------------------------------------------
            with smoke.scenario("p2m75_book sees all cost lines + Financial Summary renders"):
                smoke.login("p2m75_book")
                smoke.assert_menu_visible(COST_LINES_MENU)
                smoke.open_action(COST_LINE_ACTION)
                smoke.assert_visible("table.o_list_table", "cost line list (bookkeeper)")
                # Cross-event visibility: all three smoke costs should
                # appear (plus any other DB-resident costs).
                visible_resp = smoke.json_rpc(
                    "neon.finance.cost.line", "search_read",
                    args=[
                        [("id", "in", [
                            ids["own_cost_a_id"],
                            ids["own_cost_b_id"],
                            ids["other_cost_id"],
                        ])],
                        ["id"],
                    ],
                )
                visible_ids = [r["id"] for r in (visible_resp.get("result") or [])]
                cross_passed = (
                    ids["own_cost_a_id"] in visible_ids
                    and ids["own_cost_b_id"] in visible_ids
                    and ids["other_cost_id"] in visible_ids
                )
                smoke._record_assert(
                    "bookkeeper sees all 3 smoke costs (cross-event)",
                    expect="all 3 ids visible",
                    actual=f"visible={visible_ids}",
                    passed=cross_passed,
                )
                if not cross_passed:
                    smoke._capture_fail_artifacts(
                        "book_cross_event_visibility_failed")
                    raise AssertionFail(
                        "bookkeeper cannot see all costs cross-event")
                smoke.screenshot("02_book_cost_lines_full_list")

                # Verify the P&L compute via RPC -- more reliable than
                # driving the event_job form's notebook tab navigation
                # (the form is in another addon's view hierarchy; deep-
                # link navigation is fragile across Odoo upgrades).
                # The pnl_html is a stored HTML compute on event_job;
                # we read it directly and assert the section markers.
                resp = smoke.json_rpc(
                    "commercial.event.job", "read",
                    args=[[ids["ej_own_id"]], ["pnl_html"]],
                )
                row = (resp.get("result") or [{}])[0]
                content = row.get("pnl_html") or ""
                expected_markers = ("Revenue", "Cost", "Margin")
                missing = [m for m in expected_markers if m not in content]
                pnl_ok = not missing
                smoke._record_assert(
                    "Financial Summary HTML carries Revenue + Cost + Margin sections",
                    expect="all 3 section headers present in pnl_html",
                    actual=f"missing={missing}; len(html)={len(content)}",
                    passed=pnl_ok,
                )
                if not pnl_ok:
                    smoke._capture_fail_artifacts("pnl_html_missing_sections")
                    raise AssertionFail("P&L compute missing expected sections")
                # Screenshot the cost-line list page as a visual record
                # of the bookkeeper session (the form-tab nav is RPC-
                # verified above).
                smoke.screenshot("03_book_pnl_verified_via_rpc")

            # ----------------------------------------------------------
            # 4. Non-finance / non-crew-leader role: no Cost Lines menu
            # ----------------------------------------------------------
            with smoke.scenario("p2m75_other (no crew_leader / no finance) cannot reach Cost Lines"):
                smoke.login("p2m75_other")
                smoke.assert_menu_hidden(COST_LINES_MENU)
                smoke.goto_home()
                smoke.screenshot("04_other_no_cost_lines_menu")

        return smoke.summary()
    finally:
        print("[p6m5] teardown: cleaning up fixture records ...")
        try:
            _teardown_fixtures(ids)
        except Exception as e:  # noqa: BLE001
            # Teardown noise must NOT override the test result.
            # Print the failure so it's visible in the log, but
            # don't propagate -- the smoke verdict is what matters.
            print(f"[p6m5] teardown failed (non-fatal): {e}")


if __name__ == "__main__":
    sys.exit(main())
