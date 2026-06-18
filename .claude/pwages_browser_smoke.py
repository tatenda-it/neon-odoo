"""P-WAGES browser smoke — wages list -> form -> jobs_raw + crew FK, finance-
gated menu visible to a director (superuser). Pay -> finance/director only
(python smoke covers the sales deny). [TESTW-BS] fixtures.

Run:  .\\.claude\\.venv-browser\\Scripts\\python .\\.claude\\pwages_browser_smoke.py
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke

DB = "neon_crm"
MENU = "neon_migration.menu_wages_entry"
ACTION = "neon_migration.action_wages_entry"

_SETUP = """
env = env(context=dict(env.context, tracking_disable=True))
U = env['res.users']
W = env['neon.wages.entry']
C = env['neon.crew.member']
U.with_context(active_test=False).search([('login','=','pwages_director')]).unlink()
W.with_context(active_test=False).search([('source','=','TESTW-BS')]).unlink()
C.with_context(active_test=False).search([('source','=','TESTW-BS')]).unlink()
su = env.ref('neon_core.group_neon_superuser')
director = U.create({'name':'[TESTW-BS] Director','login':'pwages_director',
                     'password':'test123','groups_id':[(4, su.id)]}).id
crew = C.create({'name':'PWBS Oswel Kauni','aliases':'Oswell','source':'TESTW-BS'}).id
wage = W.create({'week_label':'PWBS May 5 2025','week_date':'2025-05-05',
    'crew_member_id':crew,'total':60.0,'currency_code':'USD','paid':'paid',
    'jobs_raw':'PWBS Golden Conifer\\nPWBS Zim Open Golf','source':'TESTW-BS'}).id
env.cr.commit()
print('IDS_JSON=' + repr({'user_id':director,'crew_id':crew,'wage_id':wage}))
"""

_TEARDOWN = """
ids = {ids_repr}
env['neon.wages.entry'].with_context(active_test=False).search(
    [('source','=','TESTW-BS')]).unlink()
env['neon.crew.member'].with_context(active_test=False).search(
    [('source','=','TESTW-BS')]).unlink()
try:
    env['res.users'].browse(ids['user_id']).unlink()
except Exception as e:
    print('user teardown failed', e)
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
    print("[pwages] setup ok:", ids)
    try:
        with BrowserSmoke("pwages") as smoke:
            with smoke.scenario("Wages (finance) list -> form -> jobs + crew"):
                smoke.login("pwages_director")
                smoke.assert_menu_visible(MENU)
                smoke.open_action(ACTION)
                smoke.assert_visible("table.o_list_table", "wages list")
                smoke.assert_count(
                    "tr.o_data_row td:has-text('PWBS Oswel Kauni')", 1,
                    "wage row shows crew FK")
                smoke.click("tr.o_data_row td:has-text('PWBS Oswel Kauni')",
                            name="open wage entry")
                smoke.assert_visible(
                    "div:has-text('PWBS Golden Conifer'), "
                    "textarea:has-text('PWBS Golden Conifer')",
                    "jobs_raw verbatim renders (depth)")
                smoke.screenshot("wages_form")
        return smoke.summary()
    finally:
        print("[pwages] teardown ...")
        o = _shell(_TEARDOWN.format(ids_repr=repr(ids)))
        if "TEARDOWN_OK" not in o:
            print("[pwages] teardown warning:\n" + o[-800:])


if __name__ == "__main__":
    sys.exit(main())
