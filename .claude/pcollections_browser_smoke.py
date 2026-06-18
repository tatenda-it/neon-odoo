"""P-COLLECTIONS browser smoke — the LIVE collections worklist board.

Director (superuser) opens the top-level Collections menu -> Outstanding
Payments -> kanban-by-status board renders -> a card opens its form with the
chatter (mail.thread). Depth principle: not just menu visibility — assert the
kanban card content, open the form, assert chatter + an editable status bar.
[TESTC-BS] fixtures, self-cleaning.

Run:  .\\.claude\\.venv-browser\\Scripts\\python .\\.claude\\pcollections_browser_smoke.py
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke

DB = "neon_crm"
MENU = "neon_migration.menu_collections_item"
ACTION = "neon_migration.action_collections_item"

_SETUP = """
env = env(context=dict(env.context, tracking_disable=True))
U = env['res.users']
M = env['neon.collections.item']
U.with_context(active_test=False).search([('login','=','pcoll_director')]).unlink()
M.with_context(active_test=False).search([('source','=','TESTC-BS')]).unlink()
su = env.ref('neon_core.group_neon_superuser')
director = U.create({'name':'[TESTC-BS] Director','login':'pcoll_director',
                     'password':'test123','groups_id':[(4, su.id)]}).id
item = M.create({'client_name':'PCBS British Residence',
    'event_name':'PCBS Residence Gala','amount_usd':4106.03,
    'contact_name':'Rati','contact_phone':'0782724481','status':'chasing',
    'period_year':'2026','note':'PCBS PO Submitted - awaiting payment',
    'source':'TESTC-BS'}).id
env.cr.commit()
print('IDS_JSON=' + repr({'user_id':director,'item_id':item}))
"""

_TEARDOWN = """
ids = {ids_repr}
env['neon.collections.item'].with_context(active_test=False).search(
    [('source','=','TESTC-BS')]).unlink()
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
    print("[pcollections] setup ok:", ids)
    try:
        with BrowserSmoke("pcollections") as smoke:
            with smoke.scenario("Collections board: kanban -> card -> form"):
                smoke.login("pcoll_director")
                smoke.assert_menu_visible(MENU)
                smoke.open_action(ACTION)
                smoke.assert_visible(".o_kanban_renderer", "kanban board")
                # Content depth on the board: the seeded card shows client +
                # contact (not just menu visibility).
                smoke.assert_count(
                    ".o_kanban_record:has-text('PCBS British Residence')", 1,
                    "collections card shows on the board")
                smoke.assert_visible(
                    ".o_kanban_record:has-text('Rati')",
                    "card shows contact (depth)")
                smoke.click(
                    ".o_kanban_record:has-text('PCBS British Residence')",
                    name="open collections item")
                smoke.assert_visible(
                    ".o_form_view", "item form opens")
                # Editable form: status renders on the clickable statusbar.
                smoke.assert_visible(
                    ".o_statusbar_status:has-text('Chasing')",
                    "status renders on the statusbar (depth)")
                smoke.assert_visible(
                    ".o_chatter, .o-mail-Chatter, .oe_chatter",
                    "chatter present (mail.thread)")
                smoke.screenshot("collections_form")
        return smoke.summary()
    finally:
        print("[pcollections] teardown ...")
        o = _shell(_TEARDOWN.format(ids_repr=repr(ids)))
        if "TEARDOWN_OK" not in o:
            print("[pcollections] teardown warning:\n" + o[-800:])


if __name__ == "__main__":
    sys.exit(main())
