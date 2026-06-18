"""P-FAMCAL browser smoke — job-history list -> form -> verbatim notes, menu
visible to a PLAIN internal user (all-user read; carries no money). Default view
shows jobs only. [TESTFC-BS] fixtures.

Run:  .\\.claude\\.venv-browser\\Scripts\\python .\\.claude\\pfamcal_browser_smoke.py
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke

DB = "neon_crm"
MENU = "neon_migration.menu_job_history"
ACTION = "neon_migration.action_job_history"

_SETUP = """
env = env(context=dict(env.context, tracking_disable=True))
U = env['res.users']
J = env['neon.job.history']
U.with_context(active_test=False).search([('login','=','pfc_user')]).unlink()
J.with_context(active_test=False).search([('source','=','TESTFC-BS')]).unlink()
# plain INTERNAL user (base.group_user only) proves all-user read
basic = U.create({'name':'[TESTFC-BS] Basic User','login':'pfc_user',
                  'password':'test123','groups_id':[(4, env.ref('base.group_user').id)]}).id
job = J.create({'date_start':'2025-02-14 18:00:00','date_end':'2025-02-14 23:00:00',
    'title':'PFCBS Wedding Job','location':'Leopard Rock','is_job':True,
    'category':'job','source':'TESTFC-BS',
    'notes':'PFCBS NOTES 4 sparklers | 1 low fog | 16 Wireless Cans'}).id
adm = J.create({'date_start':'2025-02-01 05:00:00','title':'PFCBS ZOHO Reminder',
    'is_job':False,'category':'reminder','source':'TESTFC-BS'}).id
env.cr.commit()
print('IDS_JSON=' + repr({'user_id':basic,'job_id':job,'adm_id':adm}))
"""

_TEARDOWN = """
ids = {ids_repr}
env['neon.job.history'].with_context(active_test=False).search(
    [('source','=','TESTFC-BS')]).unlink()
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
    print("[pfamcal] setup ok:", ids)
    try:
        with BrowserSmoke("pfamcal") as smoke:
            with smoke.scenario("Job-history (all-user) list -> form -> notes"):
                smoke.login("pfc_user")
                smoke.assert_menu_visible(MENU)
                smoke.open_action(ACTION)
                smoke.assert_visible("table.o_list_table", "job-history list")
                smoke.assert_count(
                    "tr.o_data_row td:has-text('PFCBS Wedding Job')", 1,
                    "job row renders (default Jobs filter)")
                # default filter hides the reminder
                smoke.assert_count(
                    "tr.o_data_row td:has-text('PFCBS ZOHO Reminder')", 0,
                    "reminder hidden by default Jobs filter")
                smoke.click("tr.o_data_row td:has-text('PFCBS Wedding Job')",
                            name="open job")
                smoke.assert_visible(
                    "div:has-text('PFCBS NOTES 4 sparklers')",
                    "verbatim equipment notes render (depth)")
                smoke.screenshot("job_history_form")
        return smoke.summary()
    finally:
        print("[pfamcal] teardown ...")
        o = _shell(_TEARDOWN.format(ids_repr=repr(ids)))
        if "TEARDOWN_OK" not in o:
            print("[pfamcal] teardown warning:\n" + o[-800:])


if __name__ == "__main__":
    sys.exit(main())
