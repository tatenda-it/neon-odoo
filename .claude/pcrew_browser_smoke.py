"""P-CREW browser smoke — crew roster list -> form -> aliases, menu visible to a
PLAIN internal user (all-user read; names/roles only). Active crew shown by
default; former hidden unless toggled. [TESTCREW-BS] fixtures.

Run:  .\\.claude\\.venv-browser\\Scripts\\python .\\.claude\\pcrew_browser_smoke.py
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke

DB = "neon_crm"
MENU = "neon_migration.menu_crew_member"
ACTION = "neon_migration.action_crew_member"

_SETUP = """
env = env(context=dict(env.context, tracking_disable=True))
U = env['res.users']
M = env['neon.crew.member']
U.with_context(active_test=False).search([('login','=','pcrew_user')]).unlink()
M.with_context(active_test=False).search([('source','=','TESTCREW-BS')]).unlink()
basic = U.create({'name':'[TESTCREW-BS] Basic User','login':'pcrew_user',
                  'password':'test123','groups_id':[(4, env.ref('base.group_user').id)]}).id
lead = M.create({'name':'PCBS Ranganai Lead','aliases':'KK\\nPCBS-KK','role':'lead',
                 'is_lead':True,'status':'active','active':True,'source':'TESTCREW-BS'}).id
former = M.create({'name':'PCBS Former Crew','aliases':'PCBS-Old','role':'unknown',
                   'status':'former','active':False,'source':'TESTCREW-BS'}).id
env.cr.commit()
print('IDS_JSON=' + repr({'user_id':basic,'lead_id':lead,'former_id':former}))
"""

_TEARDOWN = """
ids = {ids_repr}
env['neon.crew.member'].with_context(active_test=False).search(
    [('source','=','TESTCREW-BS')]).unlink()
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
    print("[pcrew] setup ok:", ids)
    try:
        with BrowserSmoke("pcrew") as smoke:
            with smoke.scenario("Crew roster (all-user) list -> form -> aliases"):
                smoke.login("pcrew_user")
                smoke.assert_menu_visible(MENU)
                smoke.open_action(ACTION)
                smoke.assert_visible("table.o_list_table", "crew roster list")
                smoke.assert_count(
                    "tr.o_data_row td:has-text('PCBS Ranganai Lead')", 1,
                    "active lead row renders")
                # former hidden by default (active=False)
                smoke.assert_count(
                    "tr.o_data_row td:has-text('PCBS Former Crew')", 0,
                    "former crew hidden by default")
                smoke.click("tr.o_data_row td:has-text('PCBS Ranganai Lead')",
                            name="open lead")
                smoke.assert_visible(
                    "div:has-text('PCBS-KK'), textarea:has-text('PCBS-KK')",
                    "aliases render on the form (depth)")
                smoke.screenshot("crew_form")
        return smoke.summary()
    finally:
        print("[pcrew] teardown ...")
        o = _shell(_TEARDOWN.format(ids_repr=repr(ids)))
        if "TEARDOWN_OK" not in o:
            print("[pcrew] teardown warning:\n" + o[-800:])


if __name__ == "__main__":
    sys.exit(main())
