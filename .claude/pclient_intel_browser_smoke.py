"""P-CLIENT-INTEL browser smoke — the L2.1 Owl ranking dashboard.

A director opens Client Intelligence -> Intelligence Board -> the Owl board
renders the ranking cards with real content AND the embedded read-only chat
panel. Depth: assert a ranking card header, a seeded client row, and the chat
panel root. [TESTCIB] fixtures, self-cleaning (recompute restores state).

Run:  .\\.claude\\.venv-browser\\Scripts\\python .\\.claude\\pclient_intel_browser_smoke.py
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke

DB = "neon_crm"
MENU = "neon_migration.menu_client_intel_board"
ACTION = "neon_migration.action_client_intel_board"

_SETUP = """
env = env(context=dict(env.context, tracking_disable=True))
U = env['res.users']
P = env['res.partner']
Q = env['neon.finance.quote.archive']
CI = env['neon.client.intel']
U.with_context(active_test=False).search([('login','=','pci_director')]).unlink()
Q.search([('zoho_estimate_number','=like','TESTCIB%')]).unlink()
P.with_context(active_test=False).search([('name','=like','TESTCIB %')]).unlink()
su = env.ref('neon_core.group_neon_superuser')
director = U.create({'name':'TESTCIB Director','login':'pci_director',
                     'password':'test123','groups_id':[(4, su.id)]}).id
mega = P.create({'name':'TESTCIB Mega Client','is_company':True})
Q.create({'zoho_estimate_number':'TESTCIB-W1','partner_id':mega.id,
          'amount_total':5000.0,'status_bucket':'won','currency_code':'USD',
          'quotation_date':'2026-05-01'})
CI.cron_recompute()
env.cr.commit()
print('IDS_JSON=' + repr({'user_id':director,'partner_id':mega.id}))
"""

_TEARDOWN = """
ids = {ids_repr}
env['neon.finance.quote.archive'].search(
    [('zoho_estimate_number','=like','TESTCIB%')]).unlink()
try:
    env['res.users'].browse(ids['user_id']).unlink()
except Exception as e:
    print('user teardown failed', e)
env['res.partner'].with_context(active_test=False).search(
    [('name','=like','TESTCIB %')]).unlink()
env['neon.client.intel'].cron_recompute()
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
    print("[pclient_intel] setup ok:", ids)
    try:
        with BrowserSmoke("pclient_intel") as smoke:
            with smoke.scenario("Client Intelligence board renders + chat"):
                smoke.login("pci_director")
                smoke.assert_menu_visible(MENU)
                smoke.open_action(ACTION)
                smoke.assert_visible(".o_neon_ci", "board root")
                smoke.assert_visible(
                    ".o_neon_ci_card h3", "a ranking card renders")
                smoke.assert_visible(
                    ".o_neon_ci_card td:has-text('TESTCIB Mega Client')",
                    "seeded client row shows (depth)")
                smoke.assert_visible(
                    ".o_neon_ai_chat", "embedded read-only chat panel")
                smoke.screenshot("client_intel_board")
        return smoke.summary()
    finally:
        print("[pclient_intel] teardown ...")
        o = _shell(_TEARDOWN.format(ids_repr=repr(ids)))
        if "TEARDOWN_OK" not in o:
            print("[pclient_intel] teardown warning:\n" + o[-800:])


if __name__ == "__main__":
    sys.exit(main())
