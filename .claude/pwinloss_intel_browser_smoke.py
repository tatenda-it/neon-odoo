"""P-WINLOSS-INTEL browser smoke — the L2.3 Realisation & Win/Loss board.

A director opens Realisation & Win/Loss -> Board -> the Owl board renders the
by-rep card with content, the overall win-rate/realisation header, and the
embedded read-only chat. [TESTWB] fixtures, self-cleaning (recompute restores).

Run:  .\\.claude\\.venv-browser\\Scripts\\python .\\.claude\\pwinloss_intel_browser_smoke.py
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke

DB = "neon_crm"
MENU = "neon_migration.menu_winloss_board"
ACTION = "neon_migration.action_winloss_board"

_SETUP = """
env = env(context=dict(env.context, tracking_disable=True))
U = env['res.users']; P = env['res.partner']; Q = env['neon.finance.quote.archive']
W = env['neon.winloss.intel']
U.with_context(active_test=False).search([('login','=','pwl_director')]).unlink()
Q.search([('zoho_estimate_number','=like','TESTWB%')]).unlink()
P.with_context(active_test=False).search([('name','=like','TESTWB %')]).unlink()
su = env.ref('neon_core.group_neon_superuser')
director = U.create({'name':'TESTWB Director','login':'pwl_director',
                     'password':'test123','groups_id':[(4, su.id)]}).id
mega = P.create({'name':'TESTWB Mega Client','is_company':True})
Q.create({'zoho_estimate_number':'TESTWB-W1','partner_id':mega.id,
          'status_bucket':'won','currency_code':'USD','amount_untaxed':5000.0,
          'amount_total':5750.0,'quotation_date':'2025-05-01',
          'salesperson_name':'TESTWB Rep'})
W.cron_recompute()
env.cr.commit()
print('IDS_JSON=' + repr({'user_id':director,'partner_id':mega.id}))
"""

_TEARDOWN = """
ids = {ids_repr}
env['neon.finance.quote.archive'].search(
    [('zoho_estimate_number','=like','TESTWB%')]).unlink()
try:
    env['res.users'].browse(ids['user_id']).unlink()
except Exception as e:
    print('user teardown failed', e)
env['res.partner'].with_context(active_test=False).search(
    [('name','=like','TESTWB %')]).unlink()
env['neon.winloss.intel'].cron_recompute()
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
    print("[pwinloss] setup ok:", ids)
    try:
        with BrowserSmoke("pwinloss_intel") as smoke:
            with smoke.scenario("Realisation & Win/Loss board renders + chat"):
                smoke.login("pwl_director")
                smoke.assert_menu_visible(MENU)
                smoke.open_action(ACTION)
                smoke.assert_visible(".o_neon_wl", "board root")
                smoke.assert_visible(
                    ".o_neon_wl_card h3", "a card renders")
                smoke.assert_visible(
                    ".o_neon_wl_card td:has-text('TESTWB Rep')",
                    "by-rep row shows (depth)")
                smoke.assert_visible(
                    ".o_neon_ai_chat", "embedded read-only chat panel")
                smoke.screenshot("winloss_board")
        return smoke.summary()
    finally:
        print("[pwinloss] teardown ...")
        o = _shell(_TEARDOWN.format(ids_repr=repr(ids)))
        if "TEARDOWN_OK" not in o:
            print("[pwinloss] teardown warning:\n" + o[-800:])


if __name__ == "__main__":
    sys.exit(main())
