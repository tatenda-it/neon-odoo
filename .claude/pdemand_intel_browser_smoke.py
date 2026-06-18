"""P-DEMAND-INTEL browser smoke — the L2.2 Owl seasonality board.

A director opens Demand & Seasonality -> Seasonality Board -> the Owl board
renders the seasonality bars + YoY + recurring named events, plus the embedded
read-only chat. Depth: assert a card header, the recurring event row, and the
chat panel root. [TESTDB] fixtures, self-cleaning (recompute restores state).

Run:  .\\.claude\\.venv-browser\\Scripts\\python .\\.claude\\pdemand_intel_browser_smoke.py
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke

DB = "neon_crm"
MENU = "neon_migration.menu_demand_board"
ACTION = "neon_migration.action_demand_board"

_SETUP = """
env = env(context=dict(env.context, tracking_disable=True))
U = env['res.users']
J = env['neon.job.history']
DI = env['neon.demand.intel']
U.with_context(active_test=False).search([('login','=','pdb_director')]).unlink()
J.with_context(active_test=False).search([('source','=','TESTDB')]).unlink()
su = env.ref('neon_core.group_neon_superuser')
director = U.create({'name':'TESTDB Director','login':'pdb_director',
                     'password':'test123','groups_id':[(4, su.id)]}).id
J.create({'title':'TESTDB Megafest 2024','date_start':'2024-05-10',
          'is_job':True,'source':'TESTDB'})
J.create({'title':'TESTDB Megafest 2025','date_start':'2025-05-12',
          'is_job':True,'source':'TESTDB'})
DI.cron_recompute()
env.cr.commit()
print('IDS_JSON=' + repr({'user_id':director}))
"""

_TEARDOWN = """
ids = {ids_repr}
env['neon.job.history'].with_context(active_test=False).search(
    [('source','=','TESTDB')]).unlink()
try:
    env['res.users'].browse(ids['user_id']).unlink()
except Exception as e:
    print('user teardown failed', e)
env['neon.demand.intel'].cron_recompute()
env.cr.commit(); print('TEARDOWN_OK')
"""


def _shell(script):
    p = subprocess.run(
        ["docker", "compose", "--project-directory", "C:/Users/Neon/neon-odoo",
         "exec", "-T", "odoo", "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"), capture_output=True, timeout=240)
    return (p.stdout + p.stderr).decode("utf-8", errors="replace")


def main():
    out = _shell(_SETUP)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out)
        raise RuntimeError("setup failed")
    ids = eval(m.group(1), {"__builtins__": {}}, {})
    print("[pdemand_intel] setup ok:", ids)
    try:
        with BrowserSmoke("pdemand_intel") as smoke:
            with smoke.scenario("Seasonality board renders + chat"):
                smoke.login("pdb_director")
                smoke.assert_menu_visible(MENU)
                smoke.open_action(ACTION)
                smoke.assert_visible(".o_neon_dmd", "board root")
                smoke.assert_visible(
                    ".o_neon_dmd_card h3", "a card renders")
                smoke.assert_visible(
                    ".o_neon_dmd_bars .o_neon_dmd_bar_row",
                    "seasonality bars render (depth)")
                smoke.assert_visible(
                    ".o_neon_dmd_card td:has-text('TESTDB Megafest')",
                    "recurring named event shows (depth)")
                smoke.assert_visible(
                    ".o_neon_ai_chat", "embedded read-only chat panel")
                smoke.screenshot("demand_board")
        return smoke.summary()
    finally:
        print("[pdemand_intel] teardown ...")
        o = _shell(_TEARDOWN.format(ids_repr=repr(ids)))
        if "TEARDOWN_OK" not in o:
            print("[pdemand_intel] teardown warning:\n" + o[-800:])


if __name__ == "__main__":
    sys.exit(main())
