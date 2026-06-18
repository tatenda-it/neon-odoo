"""P-SUSP-UNDEP browser smoke — suspense + undeposited list -> form -> line
render, finance-gated menus visible to a director (superuser). Read restricted
to finance/director (python smoke covers the deny). [TESTSU-BS] fixtures.

Run:  .\\.claude\\.venv-browser\\Scripts\\python .\\.claude\\psusp_undep_browser_smoke.py
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke

DB = "neon_crm"
SUSP_MENU = "neon_migration.menu_suspense"
SUSP_ACTION = "neon_migration.action_suspense_statement"
UNDEP_MENU = "neon_migration.menu_undeposited"
UNDEP_ACTION = "neon_migration.action_undeposited_statement"

_SETUP = """
env = env(context=dict(env.context, tracking_disable=True))
U = env['res.users']
S = env['neon.suspense.statement']
N = env['neon.undeposited.statement']
U.with_context(active_test=False).search([('login','=','psu_director')]).unlink()
S.with_context(active_test=False).search([('source_tab','=','TESTSU-BS')]).unlink()
N.with_context(active_test=False).search([('source_tab','=','TESTSU-BS')]).unlink()
su = env.ref('neon_core.group_neon_superuser')
director = U.create({'name':'[TESTSU-BS] Director','login':'psu_director',
                     'password':'test123','groups_id':[(4, su.id)]}).id
susp = S.create({'name':'[TESTSU-BS] Suspense 2099','period_month':'2099-01-01',
    'currency_code':'USD','closing_balance':0.0,'source_tab':'TESTSU-BS',
    'line_ids':[(0,0,{'sequence':10,'date_raw':'22-09-25','date_parsed':'2099-01-01',
        'details':'SUBS Income Line','debit':100.0,'balance':100.0}),
        (0,0,{'sequence':20,'date_raw':'','date_parsed':False,
        'details':'SUBS Transfer to PC','credit':100.0,'balance':0.0})]}).id
undep = N.create({'name':'[TESTSU-BS] Undep 2099-01','period_month':'2099-01-01',
    'statement_format':'two_table','source_tab':'TESTSU-BS',
    'line_ids':[(0,0,{'sequence':10,'section':'receipt','details':'SUBS Receipt USD',
        'amount':1000.0,'currency':'USD','date_parsed':'2099-01-05'}),
        (0,0,{'sequence':20,'section':'receipt','details':'SUBS Receipt ZWG',
        'amount':16100.0,'currency':'ZWG','note':'Bank Transfer'}),
        (0,0,{'sequence':30,'section':'expense','details':'SUBS Expense Line',
        'amount':90.0,'currency':'USD'})]}).id
env.cr.commit()
print('IDS_JSON=' + repr({'director_id':director,'susp_id':susp,'undep_id':undep}))
"""

_TEARDOWN = """
ids = {ids_repr}
for model, key in [('neon.suspense.statement','susp_id'),
                   ('neon.undeposited.statement','undep_id'),
                   ('res.users','director_id')]:
    try:
        env[model].browse(ids[key]).unlink()
    except Exception as e:
        print('teardown failed', model, e)
env.cr.commit(); print('TEARDOWN_OK')
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
    print("[psusp_undep] setup ok:", ids)
    try:
        with BrowserSmoke("psusp_undep") as smoke:
            with smoke.scenario("Suspense menu + list -> form -> line"):
                smoke.login("psu_director")
                smoke.assert_menu_visible(SUSP_MENU)
                smoke.open_action(SUSP_ACTION)
                smoke.assert_visible("table.o_list_table", "suspense list")
                smoke.assert_count(
                    "tr.o_data_row td:has-text('[TESTSU-BS] Suspense 2099')", 1,
                    "suspense statement row")
                smoke.click(
                    "tr.o_data_row td:has-text('[TESTSU-BS] Suspense 2099')",
                    name="open suspense")
                smoke.assert_visible(
                    "td:has-text('SUBS Transfer to PC'), "
                    "div:has-text('SUBS Transfer to PC')",
                    "suspense line renders (depth)")
                smoke.screenshot("suspense_form")
            with smoke.scenario("Undeposited menu + list -> form -> ZWG line"):
                smoke.login("psu_director")
                smoke.assert_menu_visible(UNDEP_MENU)
                smoke.open_action(UNDEP_ACTION)
                smoke.assert_visible("table.o_list_table", "undeposited list")
                smoke.click(
                    "tr.o_data_row td:has-text('[TESTSU-BS] Undep 2099-01')",
                    name="open undeposited")
                smoke.assert_visible(
                    "td:has-text('SUBS Receipt ZWG'), "
                    "div:has-text('SUBS Receipt ZWG')",
                    "ZWG receipt line renders (depth)")
                smoke.screenshot("undeposited_form")
        return smoke.summary()
    finally:
        print("[psusp_undep] teardown ...")
        o = _shell(_TEARDOWN.format(ids_repr=repr(ids)))
        if "TEARDOWN_OK" not in o:
            print("[psusp_undep] teardown warning:\n" + o[-800:])


if __name__ == "__main__":
    sys.exit(main())
