"""P-IMPORT browser smoke — neon_migration Zoho archive surface.

Depth principle: open the Zoho Archive menu -> assert the list renders the
fixture row -> open the form -> assert a line cell -> open the linked partner
-> assert the 'Archived Quotes' smart button renders + links. Read-only model;
fixtures created via odoo shell (superuser), torn down at the end.

Run from the host venv:
  .\\.claude\\.venv-browser\\Scripts\\python .\\.claude\\pimport_browser_smoke.py
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"

ARCHIVE_MENU = "neon_migration.menu_quote_archive"
ARCHIVE_ACTION = "neon_migration.action_quote_archive"
INVOICE_ACTION = "neon_migration.action_invoice_archive"
EXPENSE_ACTION = "neon_migration.action_expense_archive"
ROLLUP_ACTION = "neon_migration.action_quote_rollup"

_SETUP_SCRIPT = """
env = env(context=dict(env.context, tracking_disable=True))
P = env['res.partner']
A = env['neon.finance.quote.archive']
I = env['neon.finance.invoice.archive']
X = env['neon.finance.expense.archive']
# clean any prior smoke residue
A.with_context(active_test=False).search(
    [('zoho_estimate_number', '=', 'TESTQT-BS-001')]).unlink()
I.with_context(active_test=False).search(
    [('zoho_invoice_number', '=', 'TESTINV-BS-001')]).unlink()
X.with_context(active_test=False).search(
    [('zoho_expense_id', '=', 'TESTEXP-BS-001')]).unlink()
P.with_context(active_test=False).search(
    [('zoho_source_id', '=', 'TESTZ-BS')]).unlink()
partner = P.create({
    'name': '[TEST-ZIMP-BS] Smoke Client', 'company_type': 'company',
    'zoho_source_id': 'TESTZ-BS', 'email': 'zimp-bs@test',
}).id
arch = A.create({
    'zoho_estimate_number': 'TESTQT-BS-001', 'partner_id': partner,
    'zoho_customer_source_id': 'TESTZ-BS', 'quotation_date': '2025-04-01',
    'status_bucket': 'won', 'zoho_status': 'invoiced', 'currency_code': 'USD',
    'amount_untaxed': 200.0, 'amount_tax': 31.0, 'amount_total': 231.0,
    'salesperson_name': 'lisar', 'event_summary': 'Smoke Gala — 1 Apr 2025',
    'zoho_invoice_number': 'INV-SMOKE',
    'line_ids': [(0, 0, {
        'sequence': 10, 'category_prefix': 'LIGHTING',
        'name': 'SMOKE LED PAR', 'unit': 'qty', 'quantity': 4.0,
        'unit_rate': 50.0, 'line_total': 200.0, 'zoho_item_id': 'ZBS1'})],
}).id
inv = I.create({
    'zoho_invoice_number': 'TESTINV-BS-001', 'partner_id': partner,
    'zoho_customer_source_id': 'TESTZ-BS', 'zoho_estimate_number': 'TESTQT-BS-001',
    'invoice_date': '2025-04-05', 'status': 'paid', 'status_bucket': 'paid',
    'currency_code': 'USD', 'amount_untaxed': 200.0, 'amount_tax': 31.0,
    'amount_total': 231.0,
    'line_ids': [(0, 0, {'category_prefix': 'LIGHTING', 'name': 'SMOKE INV LINE',
                         'quantity': 4.0, 'unit_rate': 50.0, 'line_total': 200.0})],
}).id
exp = X.create({
    'zoho_expense_id': 'TESTEXP-BS-001', 'expense_date': '2025-04-06',
    'account_name': 'Fuel', 'description': 'SMOKE EXPENSE', 'is_billable': True,
    'partner_id': partner, 'zoho_customer_source_id': 'TESTZ-BS',
    'currency_code': 'USD', 'amount': 40.0, 'tax': 6.2,
}).id
env.cr.commit()
print('IDS_JSON=' + repr({'partner_id': partner, 'arch_id': arch,
                          'inv_id': inv, 'exp_id': exp}))
"""

_TEARDOWN_TEMPLATE = """
ids = {ids_repr}
for model, key in [('neon.finance.invoice.archive', 'inv_id'),
                   ('neon.finance.expense.archive', 'exp_id'),
                   ('neon.finance.quote.archive', 'arch_id'),
                   ('res.partner', 'partner_id')]:
    try:
        env[model].browse(ids[key]).unlink()
    except Exception as e:
        print('teardown unlink failed for', model, ids[key], ':', e)
env.cr.commit()
print('TEARDOWN_OK')
"""


def _run_odoo_shell(script: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "--project-directory", "C:/Users/Neon/neon-odoo",
         "exec", "-T", "odoo", "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"), capture_output=True, timeout=180)
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def _setup() -> dict:
    out = _run_odoo_shell(_SETUP_SCRIPT)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out)
        raise RuntimeError("setup did not produce IDS_JSON marker")
    return eval(m.group(1), {"__builtins__": {}}, {})


def _teardown(ids: dict) -> None:
    out = _run_odoo_shell(_TEARDOWN_TEMPLATE.format(ids_repr=repr(ids)))
    if "TEARDOWN_OK" not in out:
        print("[pimport] teardown warning:\n" + out[-1200:])


def main() -> int:
    print("[pimport] setup: creating Zoho-archive fixture ...")
    ids = _setup()
    print("[pimport] setup ok: partner=%s arch=%s"
          % (ids["partner_id"], ids["arch_id"]))
    try:
        with BrowserSmoke("pimport") as smoke:
            with smoke.scenario("Zoho Archive list -> form -> line (depth)"):
                smoke.login("p2m75_sales")
                smoke.assert_menu_visible(ARCHIVE_MENU)
                smoke.open_action(ARCHIVE_ACTION)
                smoke.assert_visible("table.o_list_table",
                                     "archive list view")
                smoke.assert_count(
                    "tr.o_data_row td:has-text('TESTQT-BS-001')", 1,
                    "fixture estimate row renders in the list")
                smoke.click("tr.o_data_row td:has-text('TESTQT-BS-001')",
                            name="open archived quote row")
                smoke.assert_visible("div.o_form_view", "archive form view")
                smoke.assert_visible(
                    "td:has-text('SMOKE LED PAR'), div:has-text('SMOKE LED PAR')",
                    "line item renders on the form")
                smoke.screenshot("archive_form")

            with smoke.scenario("Partner -> Archived Quotes smart button links"):
                smoke.login("p2m75_sales")
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['partner_id']}"
                    f"&model=res.partner&view_type=form",
                    wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "partner form view")
                # Odoo 17 overflows extra stat buttons into a "More" dropdown,
                # whose items are teleported into the DOM only when opened. Our
                # button is the 5th (after Meetings/Opportunities/Sales/
                # Invoiced), so open "More" if it isn't already inline.
                btn_sel = "button[name='action_view_archived_quotes']"
                if smoke.page.locator(btn_sel).count() == 0:
                    smoke.page.locator(
                        ".o_button_more, "
                        "button.dropdown-toggle:has-text('More')").first.click()
                    smoke.page.wait_for_timeout(500)
                smoke.assert_visible(
                    btn_sel,
                    "Archived Quotes smart button renders (inline or via More)")
                smoke.click(btn_sel, name="click Archived Quotes smart button")
                smoke.assert_count(
                    "tr.o_data_row td:has-text('TESTQT-BS-001')", 1,
                    "smart button opens the partner's archived quote")
                smoke.screenshot("partner_archived_quotes")

            with smoke.scenario("Finance archives: invoice + expense list -> form"):
                smoke.login("p2m75_sales")
                smoke.open_action(INVOICE_ACTION)
                smoke.assert_visible("table.o_list_table", "invoice list view")
                smoke.assert_count(
                    "tr.o_data_row td:has-text('TESTINV-BS-001')", 1,
                    "fixture invoice row renders")
                smoke.click("tr.o_data_row td:has-text('TESTINV-BS-001')",
                            name="open invoice row")
                smoke.assert_visible(
                    "td:has-text('SMOKE INV LINE'), div:has-text('SMOKE INV LINE')",
                    "invoice line renders on the form")
                smoke.open_action(EXPENSE_ACTION)
                smoke.assert_visible("table.o_list_table", "expense list view")
                smoke.assert_count(
                    "tr.o_data_row td:has-text('SMOKE EXPENSE')", 1,
                    "fixture expense row renders")
                smoke.screenshot("finance_archives")

            with smoke.scenario("Partner -> Archived Invoices smart button links"):
                smoke.login("p2m75_sales")
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['partner_id']}"
                    f"&model=res.partner&view_type=form",
                    wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "partner form view")
                inv_sel = "button[name='action_view_archived_invoices']"
                if smoke.page.locator(inv_sel).count() == 0:
                    smoke.page.locator(
                        ".o_button_more, "
                        "button.dropdown-toggle:has-text('More')").first.click()
                    smoke.page.wait_for_timeout(500)
                smoke.assert_visible(
                    inv_sel,
                    "Archived Invoices smart button renders (inline or via More)")
                smoke.click(inv_sel, name="click Archived Invoices smart button")
                smoke.assert_count(
                    "tr.o_data_row td:has-text('TESTINV-BS-001')", 1,
                    "smart button opens the partner's archived invoice")
                smoke.screenshot("partner_archived_invoices")

            with smoke.scenario("Quote Performance pivot: opens, rep x bucket, currency"):
                smoke.login("p2m75_sales")
                smoke.open_action(ROLLUP_ACTION)
                smoke.assert_visible(".o_pivot", "pivot view renders")
                # the fixture quote (salesperson_name 'lisar', won, USD) groups
                # by salesperson_display -> 'lisar' row + its 231 total appear
                # (USD default filter + Salesperson group-by both on).
                smoke.assert_visible(".o_pivot:has-text('lisar')",
                                     "rep row 'lisar' appears in the pivot")
                smoke.assert_visible(".o_pivot:has-text('231')",
                                     "the fixture's USD total renders (depth)")
                smoke.assert_visible(".o_searchview, div.o_cp_searchview",
                                     "search bar present (currency switch)")
                smoke.screenshot("quote_rollup_pivot")

        return smoke.summary()
    finally:
        print("[pimport] teardown ...")
        _teardown(ids)


if __name__ == "__main__":
    sys.exit(main())
