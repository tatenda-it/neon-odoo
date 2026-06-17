"""P-PETTY-CASH browser smoke — statement list -> form -> line render, and the
finance-gated menu is visible to a director (superuser). Read access is
restricted to finance/director (the python smoke asserts non-finance denial).

Fixture (odoo shell): a [TESTPC-BS] director user (superuser, test123) + one
[TESTPC-BS] statement with lines. Torn down (deleting the user cascades nothing
business; the statement is unlinked explicitly).

Run:  .\\.claude\\.venv-browser\\Scripts\\python .\\.claude\\ppetty_cash_browser_smoke.py
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke

BASE_URL = "http://localhost:8069"
DB = "neon_crm"
PC_MENU = "neon_migration.menu_petty_cash"
PC_ACTION = "neon_migration.action_petty_cash_statement"

_SETUP = """
env = env(context=dict(env.context, tracking_disable=True))
U = env['res.users']
S = env['neon.petty.cash.statement']
U.with_context(active_test=False).search([('login','=','phpc_director')]).unlink()
S.with_context(active_test=False).search(
    [('source_tab','=','TESTPC-BS')]).unlink()
su = env.ref('neon_core.group_neon_superuser')
director = U.create({'name': '[TESTPC-BS] Director', 'login': 'phpc_director',
                     'password': 'test123', 'groups_id': [(4, su.id)]}).id
stmt = S.create({
    'name': '[TESTPC-BS] Jan 2024', 'period_month': '2024-01-01',
    'currency_code': 'USD', 'opening_balance': 500.0, 'closing_balance': 430.0,
    'cr_total': 70.0, 'source_tab': 'TESTPC-BS',
    'line_ids': [
        (0, 0, {'sequence': 10, 'date_raw': '2024-01-01', 'date_parsed': '2024-01-01',
                'details': 'PCBS Opening Balance', 'debit': 500.0, 'balance': 500.0}),
        (0, 0, {'sequence': 20, 'date_raw': '', 'date_parsed': False,
                'details': 'PCBS Smoke Lunch Line', 'credit': 70.0, 'balance': 430.0}),
    ]}).id
env.cr.commit()
print('IDS_JSON=' + repr({'director_id': director, 'stmt_id': stmt}))
"""

_TEARDOWN = """
ids = {ids_repr}
for model, key in [('neon.petty.cash.statement', 'stmt_id'),
                   ('res.users', 'director_id')]:
    try:
        env[model].browse(ids[key]).unlink()
    except Exception as e:
        print('teardown failed', model, ids[key], e)
env.cr.commit()
print('TEARDOWN_OK')
"""


def _shell(script):
    p = subprocess.run(
        ["docker", "compose", "--project-directory", "C:/Users/Neon/neon-odoo",
         "exec", "-T", "odoo", "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"), capture_output=True, timeout=180)
    return (p.stdout + p.stderr).decode("utf-8", errors="replace")


def main():
    out = _shell(_SETUP)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out)
        raise RuntimeError("setup failed")
    ids = eval(m.group(1), {"__builtins__": {}}, {})
    print("[ppetty_cash] setup ok:", ids)
    try:
        with BrowserSmoke("ppetty_cash") as smoke:
            with smoke.scenario("Petty cash menu + list -> form -> line"):
                smoke.login("phpc_director")
                smoke.assert_menu_visible(PC_MENU)
                smoke.open_action(PC_ACTION)
                smoke.assert_visible("table.o_list_table",
                                     "statement list renders")
                smoke.assert_count(
                    "tr.o_data_row td:has-text('[TESTPC-BS] Jan 2024')", 1,
                    "fixture statement row renders")
                smoke.click("tr.o_data_row td:has-text('[TESTPC-BS] Jan 2024')",
                            name="open statement")
                smoke.assert_visible("div.o_form_view", "statement form")
                smoke.assert_visible(
                    "td:has-text('PCBS Smoke Lunch Line'), "
                    "div:has-text('PCBS Smoke Lunch Line')",
                    "cashbook line renders on the form (depth)")
                smoke.screenshot("petty_cash_form")
        return smoke.summary()
    finally:
        print("[ppetty_cash] teardown ...")
        o = _shell(_TEARDOWN.format(ids_repr=repr(ids)))
        if "TEARDOWN_OK" not in o:
            print("[ppetty_cash] teardown warning:\n" + o[-800:])


if __name__ == "__main__":
    sys.exit(main())
