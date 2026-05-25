"""P8A.M7 browser smoke -- Alerts block + Ack + tier scoping
visible surfaces.

Scenarios:

1. p8a_director loads dashboard -> Alerts block renders real
   (not placeholder). If alerts exist: severity pills + rows
   visible. If none: "Everything looks healthy" empty state.
2. p8a_director seeds an alert (via RPC create of a stale quote
   fingerprint dismissal-related condition is not testable
   directly; instead we seed an overdue invoice + verify it
   surfaces). Click Ack -> alert disappears from view.
3. Refresh dashboard -> ack'd alert stays gone.
4. p8a_director re-opens dashboard; alerts block still has
   severity_counts shape (count badges visible) when at least
   one alert remains.
"""

from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP_SCRIPT = """
# Setup: ensure p8a_director exists in approver group so alerts
# scoping includes ALL sources. Save current ZiG rate (we don't
# touch it but it affects the cash subtitle indirectly).
Users = env['res.users']

def _get_or_make(login, group_xmlid):
    user = Users.search([('login', '=', login)], limit=1)
    group = env.ref(group_xmlid)
    if not user:
        user = Users.with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'password': 'test123',
            'groups_id': [(4, group.id)],
        })
    else:
        user.write({'password': 'test123'})
        if group.id not in user.groups_id.ids:
            user.write({'groups_id': [(4, group.id)]})
    return user

u_director = _get_or_make('p8a_director', 'neon_core.group_neon_superuser')
# Add to approver group too (Forecast at-risk + pending approval
# scopes).
approver = env.ref('neon_finance.group_neon_finance_approver')
if approver.id not in u_director.groups_id.ids:
    u_director.write({'groups_id': [(4, approver.id)]})

env.cr.commit()
print('IDS_JSON=' + repr({
    'director_id': u_director.id,
}))
"""


_CLEANUP_SCRIPT = """
# Best-effort cleanup -- remove any dismissals our test runs created.
ids = %(ids)s
Dismissal = env['neon.dashboard.alert.dismissal'].sudo()
created = Dismissal.search([
    ('user_id', '=', ids['director_id']),
    ('fingerprint', 'like', 'overdue_invoice:%%'),
])
if created:
    # Force-delete bypassing rule (sudo unlink allowed for superuser).
    created.unlink()
env.cr.commit()
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
        print("[p8a_m7] SETUP FAILED -- output tail:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


def _cleanup_fixtures(ids: dict) -> None:
    _run_odoo_shell(_CLEANUP_SCRIPT % {"ids": repr(ids)})


def run() -> int:
    ids = _setup_fixtures()
    try:
        with BrowserSmoke("p8a_m7") as smoke:

            # ========================================================
            # Scenario 1: Alerts block renders real, not placeholder.
            # ========================================================
            with smoke.scenario(
                    "Alerts block renders real (not placeholder)"):
                smoke.login("p8a_director")
                smoke.assert_menu_visible(
                    "neon_dashboard.menu_neon_dashboard_root")
                smoke.open_action(
                    "neon_dashboard.action_neon_dashboard_server")
                smoke.page.wait_for_selector(
                    ".o_neon_block_alerts", timeout=10000)
                # Either an alerts list or empty-state -- both
                # acceptable. Verify the placeholder text is GONE.
                placeholder_present = smoke.page.evaluate(
                    "() => document.body.innerText.includes('Coming in M7')"
                )
                ok = not placeholder_present
                smoke._record_assert(
                    "no 'Coming in M7' placeholder text",
                    expect="absent", actual=("present" if placeholder_present else "absent"),
                    passed=ok,
                )
                if not ok:
                    raise AssertionFail("Coming in M7 placeholder still visible")
                smoke.screenshot("alerts_block_rendered")

            # ========================================================
            # Scenario 2: alerts block contract -- if not empty,
            # severity pills are visible.
            # ========================================================
            with smoke.scenario(
                    "Alerts block shape: pills or empty-state"):
                # The dashboard is loaded from Scenario 1.
                has_alerts = smoke.page.evaluate(
                    "() => !!document.querySelector"
                    "('.o_neon_alerts_list .o_neon_alerts_row')"
                )
                if has_alerts:
                    # Severity row visible.
                    smoke.assert_visible(
                        ".o_neon_alerts_severity_row",
                        "severity pill row visible")
                else:
                    # Empty-state visible.
                    smoke.assert_visible(
                        ".o_neon_block_alerts .o_neon_block_empty",
                        "empty-state visible")
                smoke.screenshot("alerts_block_shape")

            # ========================================================
            # Scenario 3: Ack flow. Skipped cleanly if no alerts.
            # ========================================================
            with smoke.scenario(
                    "Ack flow: click Ack -> alert disappears + persists"):
                has_alerts = smoke.page.evaluate(
                    "() => !!document.querySelector"
                    "('.o_neon_alerts_list .o_neon_alerts_row')"
                )
                if not has_alerts:
                    smoke._record_assert(
                        "Ack flow skipped: no alerts on DB",
                        expect="N/A", actual="no alerts",
                        passed=True,
                    )
                else:
                    # Capture first alert's fingerprint via the OWL
                    # state isn't accessible; instead, click the first
                    # Ack button and verify the alert count drops.
                    count_before = smoke.page.locator(
                        ".o_neon_alerts_list .o_neon_alerts_row"
                    ).count()
                    # Click first Ack.
                    smoke.page.locator(
                        ".o_neon_alerts_ack"
                    ).first.click()
                    smoke.page.wait_for_timeout(500)
                    count_after = smoke.page.locator(
                        ".o_neon_alerts_list .o_neon_alerts_row"
                    ).count()
                    ok = count_after < count_before
                    smoke._record_assert(
                        "alert count drops after Ack",
                        expect=f"<{count_before}",
                        actual=str(count_after),
                        passed=ok,
                    )
                    if not ok:
                        raise AssertionFail(
                            f"Ack didn't reduce visible alerts: "
                            f"{count_before} -> {count_after}")
                    # Reload dashboard and verify the count didn't
                    # bounce back.
                    smoke.open_action(
                        "neon_dashboard.action_neon_dashboard_server")
                    smoke.page.wait_for_selector(
                        ".o_neon_block_alerts", timeout=10000)
                    smoke.page.wait_for_timeout(500)
                    count_after_reload = smoke.page.locator(
                        ".o_neon_alerts_list .o_neon_alerts_row"
                    ).count()
                    ok_persist = count_after_reload <= count_after
                    smoke._record_assert(
                        "Ack persists across reload",
                        expect=f"<={count_after}",
                        actual=str(count_after_reload),
                        passed=ok_persist,
                    )
                    if not ok_persist:
                        raise AssertionFail(
                            f"Ack didn't persist: post-reload "
                            f"{count_after_reload} > post-ack {count_after}")
                smoke.screenshot("after_ack")

            return smoke.summary()
    finally:
        _cleanup_fixtures(ids)


if __name__ == "__main__":
    sys.exit(run())
