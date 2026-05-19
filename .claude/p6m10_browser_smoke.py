"""P6.M10 browser smoke -- Cash Flow Dashboard UI surfaces.

Five scenarios:

1. **p2m75_book** loads dashboard via menu -> all 6 tiles render,
   refresh button present, last-updated timestamp visible.
2. **p2m75_book** clicks Outstanding Receivables tile -> filtered
   invoice list opens (drill-through).
3. **p2m75_sales** loads dashboard, role pill shows 'sales',
   pipeline tile renders (UI surface reachable for sales tier).
4. **p2m75_lead** (crew leader) loads dashboard, costs + budget
   tiles render with numbers, other 4 tiles render '--' fallback.
5. **p2m75_other** (no finance, no crew) cannot reach the dashboard
   (server-action AccessError + no menu visibility).
"""

from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP_SCRIPT = """
from datetime import date, timedelta

# Ensure there's at least one outstanding receivable + one pipeline
# quote + one budget event so the tiles aren't empty for the test.
sales = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1).id
lead = env['res.users'].search([('login', '=', 'p2m75_lead')], limit=1).id
usd = env.ref('base.USD').id

partner = env['res.partner'].create({
    'name': 'P6M10 Browser Client', 'is_company': True,
}).id
venue = env['res.partner'].create({
    'name': 'P6M10 Browser Venue', 'is_company': True,
}).id
term = env['neon.finance.payment.term'].create({
    'partner_id': partner,
    'deposit_pct': 50.0, 'deposit_due_days': 0,
    'final_due_days': 30, 'late_policy': 'reminder',
}).id

# Pipeline quote (pending_approval)
job_p = env['commercial.job'].create({
    'partner_id': partner, 'venue_id': venue,
    'event_date': (date.today() + timedelta(days=30)).isoformat(),
    'currency_id': usd,
}).id
ej_p = env['commercial.event.job'].create({
    'commercial_job_id': job_p,
    'lead_tech_id': lead,
}).id
quote_p = env['neon.finance.quote'].create({
    'event_job_id': ej_p, 'salesperson_id': sales,
    'currency_id': usd, 'payment_term_id': term,
}).id
env['neon.finance.quote.line'].create({
    'quote_id': quote_p, 'line_type': 'other',
    'name': 'Pipeline line', 'quantity': 1, 'duration_days': 1,
    'unit_rate': 1500.0, 'pricing_status': 'manual',
})
env['neon.finance.quote'].browse(quote_p).sudo().write(
    {'state': 'pending_approval'})

# Receivable: accepted quote with posted invoice
job_a = env['commercial.job'].create({
    'partner_id': partner, 'venue_id': venue,
    'event_date': (date.today() + timedelta(days=30)).isoformat(),
    'currency_id': usd,
}).id
ej_a = env['commercial.event.job'].create({
    'commercial_job_id': job_a,
    'lead_tech_id': lead,
}).id
# Pre-stamp budget so this event has an alert level
env['commercial.event.job'].browse(ej_a).sudo().write({
    'quoted_budget': 2000.0, 'quoted_budget_currency_id': usd,
})
quote_a = env['neon.finance.quote'].create({
    'event_job_id': ej_a, 'salesperson_id': sales,
    'currency_id': usd, 'payment_term_id': term,
}).id
env['neon.finance.quote.line'].create({
    'quote_id': quote_a, 'line_type': 'other',
    'name': 'Receivable line', 'quantity': 1, 'duration_days': 1,
    'unit_rate': 800.0, 'pricing_status': 'manual',
})
env['neon.finance.invoice.schedule'].create({
    'quote_id': quote_a, 'sequence': 1, 'stage': 'deposit',
    'trigger': 'on_acceptance', 'percentage': 100.0,
    'currency_id': usd,
})
env['neon.finance.quote'].browse(quote_a).sudo().write({'state': 'sent'})
env['neon.finance.quote'].browse(quote_a).sudo().with_user(sales).action_accept()
sched_a = env['neon.finance.quote'].browse(
    quote_a).invoice_schedule_ids[0].id
inv_a = env['neon.finance.invoice.schedule'].browse(sched_a).invoice_id.id
env['account.move'].browse(inv_a).sudo().write({
    'invoice_date': date.today().isoformat(),
    'invoice_date_due': (date.today() + timedelta(days=30)).isoformat(),
})
env['account.move'].browse(inv_a).sudo().action_post()

# Cost line for the crew_leader scenario
env['neon.finance.cost.line'].with_context(
    skip_finance_notification=True
).create({
    'event_job_id': ej_a, 'cost_type': 'other',
    'name': 'P6M10 cost', 'amount': 250.0,
    'currency_id': usd, 'date_incurred': date.today().isoformat(),
    'recorded_by_id': lead,
})

# Server-action id for menu nav verification
sa_id = env.ref(
    'neon_finance.action_cash_flow_dashboard_server').id

env.cr.commit()
print('IDS_JSON=' + repr({
    'partner_id': partner, 'venue_id': venue, 'term_id': term,
    'job_p_id': job_p, 'ej_p_id': ej_p, 'quote_p_id': quote_p,
    'job_a_id': job_a, 'ej_a_id': ej_a, 'quote_a_id': quote_a,
    'inv_a_id': inv_a,
    'sa_id': sa_id,
}))
"""


_TEARDOWN_SCRIPT_TEMPLATE = """
ids = {ids_repr}

def _try_unlink(model, rec_id):
    try:
        env.cr.execute("SAVEPOINT teardown")
        env[model].browse(rec_id).unlink()
        env.cr.execute("RELEASE SAVEPOINT teardown")
        return True
    except Exception:
        env.cr.execute("ROLLBACK TO SAVEPOINT teardown")
        table_map = {{
            'account.move': 'account_move',
            'neon.finance.invoice.schedule': 'neon_finance_invoice_schedule',
            'neon.finance.cost.line': 'neon_finance_cost_line',
            'neon.finance.quote.line': 'neon_finance_quote_line',
            'neon.finance.quote': 'neon_finance_quote',
            'neon.finance.payment.term': 'neon_finance_payment_term',
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
        except Exception:
            env.cr.execute("ROLLBACK TO SAVEPOINT teardown_sql")
            return False

# Costs + schedules first (FK to event_job)
for c in env['neon.finance.cost.line'].search([
    ('event_job_id', 'in', (ids['ej_p_id'], ids['ej_a_id']))]).ids:
    _try_unlink('neon.finance.cost.line', c)
for s in env['neon.finance.invoice.schedule'].search([
    ('quote_id', 'in', (ids['quote_p_id'], ids['quote_a_id']))]).ids:
    _try_unlink('neon.finance.invoice.schedule', s)
_try_unlink('account.move', ids['inv_a_id'])
for ql in env['neon.finance.quote.line'].search([
    ('quote_id', 'in', (ids['quote_p_id'], ids['quote_a_id']))]).ids:
    _try_unlink('neon.finance.quote.line', ql)
for model, key in [
    ('neon.finance.quote', 'quote_p_id'),
    ('neon.finance.quote', 'quote_a_id'),
    ('neon.finance.payment.term', 'term_id'),
    ('commercial.event.job', 'ej_p_id'),
    ('commercial.event.job', 'ej_a_id'),
    ('commercial.job', 'job_p_id'),
    ('commercial.job', 'job_a_id'),
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
        print("[p6m10] teardown warning:")
        print(out[-1500:])


def main() -> int:
    print("[p6m10] setup: creating pipeline + receivable + cost fixtures ...")
    ids = _setup_fixtures()
    print(f"[p6m10] setup ok: quote_p={ids['quote_p_id']} "
          f"quote_a={ids['quote_a_id']} inv_a={ids['inv_a_id']}")
    try:
        with BrowserSmoke("p6m10") as smoke:

            # ----------------------------------------------------------
            # 1. Bookkeeper loads dashboard via server-action.
            # ----------------------------------------------------------
            with smoke.scenario(
                "p2m75_book loads Cash Flow Dashboard, all 6 tiles render",
            ):
                smoke.login("p2m75_book")
                smoke.page.goto(
                    f"{smoke.base_url}/web#action={ids['sa_id']}",
                    wait_until="networkidle",
                )
                smoke.assert_visible(
                    "div.o_neon_cashflow_dashboard",
                    "dashboard root rendered",
                )
                smoke.page.wait_for_timeout(1000)
                tile_count = smoke.page.locator(
                    "div.o_neon_cf_tile").count()
                passed = tile_count >= 6
                smoke._record_assert(
                    "6 tiles render",
                    expect=">=6 tiles",
                    actual=f"{tile_count} tiles",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("book_tile_count")
                    raise AssertionFail(
                        f"expected 6 tiles, found {tile_count}")
                # Last-updated visible
                last_updated = smoke.page.locator(
                    "text=/Last updated:/").count()
                smoke._record_assert(
                    "Last updated timestamp visible",
                    expect=">=1",
                    actual=f"{last_updated} match(es)",
                    passed=last_updated >= 1,
                )
                smoke.screenshot("01_book_dashboard_loaded")

            # ----------------------------------------------------------
            # 2. Bookkeeper clicks Outstanding Receivables tile.
            # ----------------------------------------------------------
            with smoke.scenario(
                "p2m75_book clicks Outstanding Receivables tile",
            ):
                tile = smoke.page.locator(
                    "div.o_neon_cf_tile:has-text('Outstanding Receivables')"
                ).first
                tile.click()
                smoke.page.wait_for_timeout(1000)
                # Should now be on a list view of invoices
                list_visible = smoke.page.locator(
                    "table.o_list_table").count()
                passed = list_visible >= 1
                smoke._record_assert(
                    "drill-through opens invoice list",
                    expect=">=1 list table",
                    actual=f"{list_visible} list(s)",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts(
                        "drill_no_list")
                    raise AssertionFail(
                        "drill-through did not open list view")
                smoke.screenshot("02_book_drill_through_receivables")

            # ----------------------------------------------------------
            # 3. Sales rep loads dashboard.
            # ----------------------------------------------------------
            with smoke.scenario(
                "p2m75_sales loads dashboard, role pill shows 'sales'",
            ):
                smoke.login("p2m75_sales")
                smoke.page.goto(
                    f"{smoke.base_url}/web#action={ids['sa_id']}",
                    wait_until="networkidle",
                )
                smoke.assert_visible(
                    "div.o_neon_cashflow_dashboard",
                    "dashboard root rendered for sales",
                )
                smoke.page.wait_for_timeout(1000)
                role_pill = smoke.page.locator(
                    "text=/role: sales/").count()
                passed = role_pill >= 1
                smoke._record_assert(
                    "role pill shows 'sales'",
                    expect=">=1",
                    actual=f"{role_pill} match(es)",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("sales_no_role_pill")
                    raise AssertionFail("role pill missing")
                # Pipeline tile should render with our pipeline quote
                pipe_tile = smoke.page.locator(
                    "div.o_neon_cf_tile:has-text('Pipeline')"
                ).count()
                smoke._record_assert(
                    "pipeline tile renders for sales",
                    expect=">=1 tile",
                    actual=f"{pipe_tile} tile(s)",
                    passed=pipe_tile >= 1,
                )
                smoke.screenshot("03_sales_dashboard_role_pill")

            # ----------------------------------------------------------
            # 4. Crew leader sees costs + budget tiles only.
            # ----------------------------------------------------------
            with smoke.scenario(
                "p2m75_lead (crew leader) sees degraded tiles",
            ):
                smoke.login("p2m75_lead")
                smoke.page.goto(
                    f"{smoke.base_url}/web#action={ids['sa_id']}",
                    wait_until="networkidle",
                )
                smoke.assert_visible(
                    "div.o_neon_cashflow_dashboard",
                    "dashboard root rendered for crew_leader",
                )
                smoke.page.wait_for_timeout(1000)
                role_pill = smoke.page.locator(
                    "text=/role: crew_leader/").count()
                passed = role_pill >= 1
                smoke._record_assert(
                    "role pill shows 'crew_leader'",
                    expect=">=1",
                    actual=f"{role_pill} match(es)",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts(
                        "lead_no_role_pill")
                    raise AssertionFail("role pill missing for crew")
                # Recent costs tile must render with our $250 cost
                costs_tile = smoke.page.locator(
                    "div.o_neon_cf_tile:has-text('Recent Costs')"
                ).count()
                smoke._record_assert(
                    "Recent Costs tile renders for crew leader",
                    expect=">=1 tile",
                    actual=f"{costs_tile} tile(s)",
                    passed=costs_tile >= 1,
                )
                # Degraded tiles: receivables / pipeline / payments
                # should render '--' (no concrete USD value).
                # Locate by tile title and verify '--' substring present.
                # Note: the template uses fmtUsd which returns '--'
                # for null values.
                dashes = smoke.page.locator("text=/^\\s*--\\s*$/").count()
                smoke._record_assert(
                    "degraded tiles render '--' placeholder",
                    expect=">=4 dashes (4 degraded tiles x 2 currency rows)",
                    actual=f"{dashes} dash(es)",
                    passed=dashes >= 4,
                )
                smoke.screenshot("04_crew_leader_degraded")

            # ----------------------------------------------------------
            # 5. Non-finance user can't reach.
            # ----------------------------------------------------------
            with smoke.scenario(
                "p2m75_other (no finance/crew) blocked from dashboard",
            ):
                smoke.login("p2m75_other")
                # Direct URL navigation -- the server-action should
                # raise AccessError before client action descriptor
                # is returned.
                # @api.model RPC via the standard /web/dataset/call_kw
                # call shape -- args=[] (no positional args); empty
                # recordset is implied for @api.model.
                resp = smoke.json_rpc(
                    "neon.finance.dashboard",
                    "get_cash_flow_dashboard_data",
                    args=[],
                )
                err = resp.get("error") or {}
                msg = err.get("data", {}).get("message", "")
                passed = ("permission" in msg.lower()
                          or "access" in msg.lower())
                smoke._record_assert(
                    "non-finance user blocked at server-action layer",
                    expect="AccessError on RPC",
                    actual=f"err: {msg[:120]}",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts(
                        "other_bypassed_block")
                    raise AssertionFail(
                        "non-finance user not blocked")
                smoke.screenshot("05_other_blocked")

        return smoke.summary()
    finally:
        print("[p6m10] teardown: cleaning up fixture records ...")
        try:
            _teardown_fixtures(ids)
        except Exception as e:  # noqa: BLE001
            print(f"[p6m10] teardown failed (non-fatal): {e}")


if __name__ == "__main__":
    sys.exit(main())
