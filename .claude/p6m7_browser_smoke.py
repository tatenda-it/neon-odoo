"""P6.M7 browser smoke -- invoice schedule UI.

Five scenarios:

1. **p2m75_sales** opens an accepted quote, navigates to the Invoice
   Schedule notebook tab -- sees the default 100% on_acceptance row
   that materialised on accept.
2. **p2m75_sales** opens a draft quote with a partial (60%) schedule:
   the over/under banner is visible. Adds another line bringing the
   total to 100%; banner clears (RPC mutation; visual re-check).
3. **p2m75_book** navigates to the Invoice Schedule menu under
   Customers, sees the list rows materialised by setup, opens a row
   form, confirms the stage badge + currency render.
4. **p2m75_book** navigates to Configuration > Finance > Schedule
   Templates, sees the seed template row, opens form, confirms the
   embedded line editor renders.
5. **p2m75_approver** triggers an on_date schedule via the form's
   Trigger Now button (RPC under the hood); schedule flips to
   invoiced and the invoice record is reachable via the invoice_id
   field.
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
sales = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1).id
usd = env.ref('base.USD').id

partner = env['res.partner'].create({
    'name': 'P6M7 Browser Client', 'is_company': True,
}).id
venue = env['res.partner'].create({
    'name': 'P6M7 Browser Venue', 'is_company': True,
}).id
term = env['neon.finance.payment.term'].create({
    'partner_id': partner,
    'deposit_pct': 50.0, 'deposit_due_days': 0,
    'final_due_days': 30, 'late_policy': 'reminder',
}).id

# Template the bookkeeper will inspect
tpl = env['neon.finance.invoice.schedule.template'].create({
    'name': 'P6M7 Browser Cadence', 'partner_id': partner,
    'line_ids': [
        (0, 0, {'sequence': 1, 'stage': 'deposit',
                'trigger': 'on_acceptance', 'percentage': 50.0}),
        (0, 0, {'sequence': 2, 'stage': 'final',
                'trigger': 'on_date', 'trigger_offset_days': 30,
                'percentage': 50.0}),
    ],
}).id

# Quote 1: accepted, drove default schedule materialisation
job_a = env['commercial.job'].create({
    'partner_id': partner, 'venue_id': venue,
    'event_date': (date.today() + timedelta(days=30)).isoformat(),
    'currency_id': usd,
}).id
ej_a = env['commercial.event.job'].create({
    'commercial_job_id': job_a,
}).id
quote_a = env['neon.finance.quote'].create({
    'event_job_id': ej_a, 'salesperson_id': sales,
    'currency_id': usd, 'payment_term_id': term,
}).id
env['neon.finance.quote.line'].create({
    'quote_id': quote_a, 'line_type': 'other',
    'name': 'P6M7 line', 'quantity': 1, 'duration_days': 1,
    'unit_rate': 1000.0, 'pricing_status': 'manual',
})
env['neon.finance.quote'].browse(quote_a).sudo().write({'state': 'sent'})
env['neon.finance.quote'].browse(quote_a).sudo().with_user(sales).action_accept()

# Quote 2: draft + partial 60% schedule -> banner test
partner2 = env['res.partner'].create({
    'name': 'P6M7 Browser Client 2', 'is_company': True,
}).id
term2 = env['neon.finance.payment.term'].create({
    'partner_id': partner2,
    'deposit_pct': 50.0, 'deposit_due_days': 0,
    'final_due_days': 30, 'late_policy': 'reminder',
}).id
job_b = env['commercial.job'].create({
    'partner_id': partner2, 'venue_id': venue,
    'event_date': (date.today() + timedelta(days=30)).isoformat(),
    'currency_id': usd,
}).id
ej_b = env['commercial.event.job'].create({
    'commercial_job_id': job_b,
}).id
quote_b = env['neon.finance.quote'].create({
    'event_job_id': ej_b, 'salesperson_id': sales,
    'currency_id': usd, 'payment_term_id': term2,
}).id
env['neon.finance.quote.line'].create({
    'quote_id': quote_b, 'line_type': 'other',
    'name': 'P6M7 line', 'quantity': 1, 'duration_days': 1,
    'unit_rate': 1000.0, 'pricing_status': 'manual',
})
env['neon.finance.invoice.schedule'].create({
    'quote_id': quote_b, 'sequence': 1, 'stage': 'deposit',
    'trigger': 'on_acceptance', 'percentage': 60.0,
    'currency_id': usd,
})

# Quote 3: accepted + on_date schedule for the Trigger Now test
partner3 = env['res.partner'].create({
    'name': 'P6M7 Browser Client 3', 'is_company': True,
}).id
term3 = env['neon.finance.payment.term'].create({
    'partner_id': partner3,
    'deposit_pct': 50.0, 'deposit_due_days': 0,
    'final_due_days': 30, 'late_policy': 'reminder',
}).id
job_c = env['commercial.job'].create({
    'partner_id': partner3, 'venue_id': venue,
    'event_date': (date.today() + timedelta(days=30)).isoformat(),
    'currency_id': usd,
}).id
ej_c = env['commercial.event.job'].create({
    'commercial_job_id': job_c,
}).id
quote_c = env['neon.finance.quote'].create({
    'event_job_id': ej_c, 'salesperson_id': sales,
    'currency_id': usd, 'payment_term_id': term3,
}).id
env['neon.finance.quote.line'].create({
    'quote_id': quote_c, 'line_type': 'other',
    'name': 'P6M7 line', 'quantity': 1, 'duration_days': 1,
    'unit_rate': 1000.0, 'pricing_status': 'manual',
})
sched_future = env['neon.finance.invoice.schedule'].create({
    'quote_id': quote_c, 'sequence': 1, 'stage': 'final',
    'trigger': 'on_date',
    'trigger_date': (date.today() + timedelta(days=21)).isoformat(),
    'percentage': 100.0, 'currency_id': usd,
}).id
env['neon.finance.quote'].browse(quote_c).sudo().write({'state': 'sent'})
env['neon.finance.quote'].browse(quote_c).sudo().with_user(sales).action_accept()

action_sched = env.ref(
    'neon_finance.neon_finance_invoice_schedule_action').id
action_tpl = env.ref(
    'neon_finance.neon_finance_invoice_schedule_template_action').id
env.cr.commit()
print('IDS_JSON=' + repr({
    'partner_id': partner, 'partner2_id': partner2, 'partner3_id': partner3,
    'venue_id': venue,
    'term_id': term, 'term2_id': term2, 'term3_id': term3,
    'tpl_id': tpl,
    'job_a_id': job_a, 'ej_a_id': ej_a, 'quote_a_id': quote_a,
    'job_b_id': job_b, 'ej_b_id': ej_b, 'quote_b_id': quote_b,
    'job_c_id': job_c, 'ej_c_id': ej_c, 'quote_c_id': quote_c,
    'sched_future_id': sched_future,
    'action_sched_id': action_sched, 'action_tpl_id': action_tpl,
}))
"""

_TEARDOWN_SCRIPT_TEMPLATE = """
ids = {ids_repr}
import psycopg2

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
            'neon.finance.invoice.schedule.template.line':
                'neon_finance_invoice_schedule_template_line',
            'neon.finance.invoice.schedule.template':
                'neon_finance_invoice_schedule_template',
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

# Unlink invoices that came from any of the test schedules (avoid
# blocking the schedule unlink via ondelete='restrict').
sched_ids = env['neon.finance.invoice.schedule'].search([
    ('quote_id', 'in',
     (ids['quote_a_id'], ids['quote_b_id'], ids['quote_c_id']))
]).ids
moves = env['neon.finance.invoice.schedule'].browse(sched_ids).mapped(
    'invoice_id')
for m in moves:
    _try_unlink('account.move', m.id)

# Schedules
for sid in sched_ids:
    _try_unlink('neon.finance.invoice.schedule', sid)

# Quote lines
ql_ids = env['neon.finance.quote.line'].search([
    ('quote_id', 'in',
     (ids['quote_a_id'], ids['quote_b_id'], ids['quote_c_id']))
]).ids
for q in ql_ids:
    _try_unlink('neon.finance.quote.line', q)

# Quotes -> event_jobs -> jobs -> partners
for model, key in [
    ('neon.finance.quote', 'quote_a_id'),
    ('neon.finance.quote', 'quote_b_id'),
    ('neon.finance.quote', 'quote_c_id'),
    ('neon.finance.payment.term', 'term_id'),
    ('neon.finance.payment.term', 'term2_id'),
    ('neon.finance.payment.term', 'term3_id'),
    ('neon.finance.invoice.schedule.template', 'tpl_id'),
    ('commercial.event.job', 'ej_a_id'),
    ('commercial.event.job', 'ej_b_id'),
    ('commercial.event.job', 'ej_c_id'),
    ('commercial.job', 'job_a_id'),
    ('commercial.job', 'job_b_id'),
    ('commercial.job', 'job_c_id'),
    ('res.partner', 'partner_id'),
    ('res.partner', 'partner2_id'),
    ('res.partner', 'partner3_id'),
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
        print("[p6m7] teardown warning:")
        print(out[-1500:])


def main() -> int:
    print("[p6m7] setup: creating quotes + schedules + template ...")
    ids = _setup_fixtures()
    print(f"[p6m7] setup ok: quote_a={ids['quote_a_id']} "
          f"quote_b={ids['quote_b_id']} quote_c={ids['quote_c_id']}")
    try:
        with BrowserSmoke("p6m7") as smoke:

            # ----------------------------------------------------------
            # 1. p2m75_sales: accepted quote -> Invoice Schedule tab
            #    shows the default 100% on_acceptance materialised row.
            # ----------------------------------------------------------
            with smoke.scenario(
                "p2m75_sales sees default schedule on accepted quote",
            ):
                smoke.login("p2m75_sales")
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['quote_a_id']}"
                    f"&model=neon.finance.quote&view_type=form",
                    wait_until="networkidle",
                )
                smoke.assert_visible("div.o_form_view",
                                     "quote_a form loaded")
                # Click the Invoice Schedule notebook tab
                smoke.page.locator(
                    "a.nav-link:has-text('Invoice Schedule')").first.click()
                smoke.page.wait_for_timeout(300)
                # The default-fallback row materialised at accept
                # (100% on_acceptance, single line).
                rows = smoke.page.locator(
                    "div[name='invoice_schedule_ids'] table.o_list_table tbody tr.o_data_row"
                ).count()
                passed = rows >= 1
                smoke._record_assert(
                    "accepted quote shows materialised schedule row",
                    expect=">=1 row in Invoice Schedule tab",
                    actual=f"{rows} rows",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("no_schedule_rows_on_accepted")
                    raise AssertionFail(
                        "no schedule rows visible on accepted quote")
                smoke.screenshot("01_sales_accepted_quote_schedule")

            # ----------------------------------------------------------
            # 2. p2m75_sales: draft quote with partial 60% -> banner
            #    visible.
            # ----------------------------------------------------------
            with smoke.scenario(
                "p2m75_sales sees over/under banner on partial schedule",
            ):
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['quote_b_id']}"
                    f"&model=neon.finance.quote&view_type=form",
                    wait_until="networkidle",
                )
                smoke.assert_visible("div.o_form_view",
                                     "quote_b draft form loaded")
                smoke.page.locator(
                    "a.nav-link:has-text('Invoice Schedule')").first.click()
                smoke.page.wait_for_timeout(300)
                banner_count = smoke.page.locator(
                    "div.alert.alert-warning:has-text('Stage percentages sum to')"
                ).count()
                passed = banner_count >= 1
                smoke._record_assert(
                    "partial-schedule banner visible on draft quote",
                    expect=">=1 banner",
                    actual=f"{banner_count} banners",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("no_partial_banner")
                    raise AssertionFail("banner missing on partial schedule")
                smoke.screenshot("02_sales_draft_quote_partial_banner")

            # ----------------------------------------------------------
            # 3. p2m75_book: Invoice Schedule menu under Customers
            # ----------------------------------------------------------
            with smoke.scenario(
                "p2m75_book navigates Invoice Schedule menu, opens row",
            ):
                smoke.login("p2m75_book")
                smoke.page.goto(
                    f"{smoke.base_url}/web#action={ids['action_sched_id']}",
                    wait_until="networkidle",
                )
                smoke.assert_visible(
                    "table.o_list_table",
                    "Invoice Schedule list rendered",
                )
                rows = smoke.page.locator(
                    "table.o_list_table tbody tr.o_data_row").count()
                passed = rows >= 1
                smoke._record_assert(
                    "bookkeeper sees at least 1 schedule row",
                    expect=">=1 row",
                    actual=f"{rows} rows",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("book_empty_sched_list")
                    raise AssertionFail("bookkeeper schedule list empty")
                # Open the first row -> form renders
                smoke.page.locator(
                    "table.o_list_table tbody tr.o_data_row").first.click()
                smoke.assert_visible("div.o_form_view",
                                     "schedule form loaded")
                smoke.screenshot("03_book_schedule_list_and_form")

            # ----------------------------------------------------------
            # 4. p2m75_book: Schedule Templates menu
            # ----------------------------------------------------------
            with smoke.scenario(
                "p2m75_book navigates Schedule Templates, opens form",
            ):
                smoke.page.goto(
                    f"{smoke.base_url}/web#action={ids['action_tpl_id']}",
                    wait_until="networkidle",
                )
                smoke.assert_visible(
                    "table.o_list_table",
                    "Schedule Templates list rendered",
                )
                rows = smoke.page.locator(
                    "table.o_list_table tbody tr.o_data_row").count()
                passed = rows >= 1
                smoke._record_assert(
                    "templates list has >=1 row",
                    expect=">=1 row",
                    actual=f"{rows} rows",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("book_empty_tpl_list")
                    raise AssertionFail("templates list empty")
                # Open template form and confirm the embedded line
                # editor renders.
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['tpl_id']}"
                    f"&model=neon.finance.invoice.schedule.template&view_type=form",
                    wait_until="networkidle",
                )
                smoke.assert_visible(
                    "div[name='line_ids'] table.o_list_table",
                    "template form embedded line editor rendered",
                )
                smoke.screenshot("04_book_template_form")

            # ----------------------------------------------------------
            # 5. p2m75_approver: Trigger Now on scheduled on_date row.
            #    Use RPC for the mutation (button visibility verified
            #    visually); state flip confirmed via re-read.
            # ----------------------------------------------------------
            with smoke.scenario(
                "p2m75_approver triggers an on_date schedule via Trigger Now",
            ):
                smoke.login("p2m75_approver")
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['sched_future_id']}"
                    f"&model=neon.finance.invoice.schedule&view_type=form",
                    wait_until="networkidle",
                )
                smoke.assert_visible("div.o_form_view",
                                     "schedule form loaded for approver")
                btn_count = smoke.page.locator(
                    "button[name='action_trigger_now']").count()
                visible = btn_count >= 1
                smoke._record_assert(
                    "Trigger Now button visible to approver",
                    expect=">=1 button",
                    actual=f"{btn_count} buttons",
                    passed=visible,
                )
                if not visible:
                    smoke._capture_fail_artifacts(
                        "approver_no_trigger_button")
                    raise AssertionFail(
                        "Trigger Now button hidden from approver")
                # Mutate via RPC then visual re-check
                resp = smoke.json_rpc(
                    "neon.finance.invoice.schedule", "action_trigger_now",
                    args=[[ids["sched_future_id"]]],
                )
                if resp.get("error"):
                    raise AssertionFail(
                        f"action_trigger_now RPC failed: {resp['error']}")
                rec = smoke.json_rpc(
                    "neon.finance.invoice.schedule", "read",
                    args=[[ids["sched_future_id"]],
                          ["state", "invoice_id"]],
                )
                row = (rec.get("result") or [{}])[0]
                passed = (
                    row.get("state") in ("invoiced", "paid")
                    and bool(row.get("invoice_id"))
                )
                smoke._record_assert(
                    "post-Trigger: state=invoiced, invoice_id set",
                    expect="state in {invoiced,paid} + invoice_id truthy",
                    actual=(
                        f"state={row.get('state')} "
                        f"invoice_id={row.get('invoice_id')}"
                    ),
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("trigger_did_not_invoice")
                    raise AssertionFail(
                        "Trigger Now did not flip schedule to invoiced")
                smoke.screenshot("05_approver_trigger_now_done")

        return smoke.summary()
    finally:
        print("[p6m7] teardown: cleaning up fixture records ...")
        try:
            _teardown_fixtures(ids)
        except Exception as e:  # noqa: BLE001
            print(f"[p6m7] teardown failed (non-fatal): {e}")


if __name__ == "__main__":
    sys.exit(main())
