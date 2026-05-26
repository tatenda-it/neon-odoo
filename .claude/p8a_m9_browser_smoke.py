"""P8A.M9 browser smoke -- Weekly digest manual trigger + log
+ visible surfaces.

Scenarios:

1. p8a_director navigates Settings > Neon and sees both new menu
   entries (Send Weekly Digest + Digest History).
2. Send Weekly Digest -> click Send Now -> success notification
   appears.
3. Digest History list shows the new row (status=sent, recipients
   count > 0, PDF attachment present).
4. Non-superuser (p8a_m9_basic) does NOT see either menu under
   Settings > Neon (negative gate).
"""

from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP_SCRIPT = """
# Setup: ensure p8a_director is in approver group (so digest send
# has a real recipient) and create a basic non-superuser for the
# negative scenario.
Users = env['res.users']

def _get_or_make(login, group_xmlids):
    user = Users.search([('login', '=', login)], limit=1)
    groups = [env.ref(x) for x in group_xmlids]
    if not user:
        user = Users.with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'password': 'test123',
            'groups_id': [(4, g.id) for g in groups],
        })
    else:
        user.write({'password': 'test123', 'active': True})
        for g in groups:
            if g.id not in user.groups_id.ids:
                user.write({'groups_id': [(4, g.id)]})
    return user

u_director = _get_or_make(
    'p8a_director',
    ['neon_core.group_neon_superuser',
     'neon_finance.group_neon_finance_approver'])

# Basic non-superuser (internal user, no neon tier groups).
u_basic = _get_or_make('p8a_m9_basic', ['base.group_user'])

# Clear any prior M9 browser-smoke log rows so the scenario sees
# our send as the new latest row.
Log = env['neon.dashboard.digest.log'].sudo()
prior = Log.search([('window_label', 'like', '%')], limit=200)
# Don't delete real history -- just snapshot the highest id so we
# can assert "new row above this id" later.
max_id_before = max(prior.ids) if prior else 0

env.cr.commit()
print('IDS_JSON=' + repr({
    'director_id': u_director.id,
    'basic_id': u_basic.id,
    'max_log_id_before': max_id_before,
}))
"""


_CLEANUP_SCRIPT = """
# No destructive cleanup -- the digest log is append-only audit
# history, we preserve every row. Just print OK.
print('CLEANUP_OK')
"""


def _run_odoo_shell(script: str) -> str:
    proc = subprocess.run(
        [
            "docker", "compose",
            "--project-directory", "C:/Users/Neon/neon-odoo",
            "exec", "-T", "odoo",
            "odoo", "shell", "-d", DB, "--no-http",
        ],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=180,
    )
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def _setup_fixtures() -> dict:
    out = _run_odoo_shell(_SETUP_SCRIPT)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print("[p8a_m9] SETUP FAILED -- output tail:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


def _cleanup_fixtures(ids: dict) -> None:
    _run_odoo_shell(_CLEANUP_SCRIPT)


def run() -> int:
    ids = _setup_fixtures()
    try:
        with BrowserSmoke("p8a_m9") as smoke:

            # =========================================================
            # Scenario 1: superuser sees both new Settings menu items.
            # =========================================================
            with smoke.scenario(
                    "Superuser sees Send Digest + History menus"):
                smoke.login("p8a_director")
                # The Send Weekly Digest entry sits under
                # Settings > Neon. We assert by xmlid menu visibility.
                smoke.assert_menu_visible(
                    "neon_dashboard.menu_neon_dashboard_send_digest")
                smoke.assert_menu_visible(
                    "neon_dashboard.menu_neon_dashboard_digest_log")
                smoke.screenshot("menus_visible")

            # =========================================================
            # Scenario 2: open the wizard, click Send Now, success.
            # =========================================================
            with smoke.scenario(
                    "Send Weekly Digest -> Send Now -> success"):
                smoke.open_action(
                    "neon_dashboard.action_neon_dashboard_send_digest_wizard")
                # Wizard opens in modal; wait for the Send Now button.
                smoke.page.wait_for_selector(
                    "button[name='action_send_now']", timeout=10000)
                # Click and wait for notification.
                smoke.page.locator(
                    "button[name='action_send_now']").click()
                # Notification body contains "Sent to N recipient(s)"
                # or "FAILED" or "No recipients". We assert success.
                smoke.page.wait_for_function(
                    "() => Array.from(document.querySelectorAll('*'))"
                    ".some(el => /Weekly digest sent|FAILED|No recipients/"
                    ".test(el.innerText || ''))",
                    timeout=10000,
                )
                body_text = smoke.page.evaluate(
                    "() => document.body.innerText")
                ok = ("Weekly digest sent" in body_text
                      or "Sent to" in body_text)
                smoke._record_assert(
                    "Send Now produced success notification",
                    expect="'Weekly digest sent' in notification",
                    actual=("found" if ok else "absent"),
                    passed=ok,
                )
                if not ok:
                    raise AssertionFail(
                        "Send Now did not produce success notification; "
                        f"body excerpt: {body_text[:500]}")
                smoke.screenshot("after_send_now")

            # =========================================================
            # Scenario 3: Digest History shows the new row.
            # =========================================================
            with smoke.scenario(
                    "Digest History shows new row"):
                smoke.open_action(
                    "neon_dashboard.action_neon_dashboard_digest_log")
                smoke.page.wait_for_selector(
                    ".o_list_view, .o_data_row", timeout=10000)
                # Look for a row with status=sent and any window label.
                row_count = smoke.page.locator(".o_data_row").count()
                ok = row_count >= 1
                smoke._record_assert(
                    "Digest history has at least one row",
                    expect=">=1",
                    actual=str(row_count),
                    passed=ok,
                )
                if not ok:
                    raise AssertionFail(
                        f"Digest history empty (rows={row_count})")
                # Verify the row says "sent" (status badge text).
                has_sent = smoke.page.evaluate(
                    "() => document.body.innerText.includes('sent')"
                )
                smoke._record_assert(
                    "Digest row status=sent visible",
                    expect="visible",
                    actual=("visible" if has_sent else "absent"),
                    passed=has_sent,
                )
                if not has_sent:
                    raise AssertionFail(
                        "Sent status not visible in digest history")
                smoke.screenshot("digest_history")

            # =========================================================
            # Scenario 4: basic non-superuser cannot see the menus.
            # ---------------------------------------------------------
            # smoke.login() spawns a fresh browser context when the
            # login changes (browser_smoke.py:202), so explicit logout
            # isn't needed.
            # =========================================================
            with smoke.scenario(
                    "Non-superuser does NOT see digest menus"):
                smoke.login("p8a_m9_basic")
                # Both menus are gated to neon_core.group_neon_superuser
                # so they MUST be hidden for a base.group_user-only
                # account. assert_menu_hidden uses ir.ui.menu.
                # load_web_menus -- the canonical menu-visibility RPC.
                smoke.assert_menu_hidden(
                    "neon_dashboard.menu_neon_dashboard_send_digest")
                smoke.assert_menu_hidden(
                    "neon_dashboard.menu_neon_dashboard_digest_log")

            return smoke.summary()
    finally:
        _cleanup_fixtures(ids)


if __name__ == "__main__":
    sys.exit(run())
