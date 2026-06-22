"""DASH-DUALROLE-1 browser smoke -- dual-role View-As round-trip.

A dual-role Bookkeeper+HR non-superuser (Kudzai's exact group combo)
must now:
  1. LAND on the Bookkeeper lens (was: HR);
  2. see a View-As switcher offering BOTH Bookkeeper and HR (the data-
     only fix could not surface this -- the switcher only ever held HR);
  3. switch to HR (HR-unique tile appears);
  4. switch BACK to Bookkeeper (the round-trip the data-only fix could
     not do).

Lens identity is asserted via lens-unique KPI tiles:
  * Bookkeeper -> .widget--kpi_pending_invoices
  * HR         -> .widget--kpi_hr_headcount

Mirrors the P8A.M1-M3 dashboard browser-smoke harness.
"""

from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP_SCRIPT = """
# DASH-DUALROLE-1 browser-smoke setup -- ensure the dual-role fixture
# (Bookkeeper + HR Admin) exists, active, password test123. (6,0,...)
# sets the exact tier membership; implied_ids re-cascade. Dedicated
# dash_dr_browser login -- never mutate real users.
Users = env['res.users']
grp_ids = [
    env.ref('base.group_user').id,
    env.ref('neon_core.group_neon_bookkeeper').id,
    env.ref('neon_hr.group_neon_hr_admin').id,
]
u = Users.with_context(active_test=False).search(
    [('login', '=', 'dash_dr_browser')], limit=1)
if u:
    u.write({'active': True, 'password': 'test123',
             'groups_id': [(6, 0, grp_ids)]})
else:
    u = Users.with_context(no_reset_password=True).create({
        'name': 'dash_dr_browser', 'login': 'dash_dr_browser',
        'password': 'test123', 'groups_id': [(6, 0, grp_ids)],
    })
env.cr.commit()
print('IDS_JSON=' + repr({'dual_id': u.id}))
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
        print("[dash_dualrole] SETUP FAILED -- output tail:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307 (controlled local input)


def run() -> int:
    _setup_fixtures()
    with BrowserSmoke("dash_dualrole") as smoke:

        with smoke.scenario(
                "dual-role lands Bookkeeper, switcher offers both lenses, "
                "round-trips to HR and back"):
            smoke.login("dash_dr_browser")
            smoke.assert_menu_visible(
                "neon_dashboard.menu_neon_dashboard_root")
            smoke.open_action(
                "neon_dashboard.action_neon_dashboard_server")

            # (2) View-As switcher visible for the dual-role user -- the
            # whole point of the fix (data-only could not surface this).
            smoke.assert_visible(
                ".o_neon_dashboard_viewas",
                "View-As switcher visible (dual-role, >=2 lenses)")
            smoke.assert_count(
                ".o_neon_dashboard_viewas option[value='bookkeeper']", 1,
                "switcher offers Bookkeeper")
            smoke.assert_count(
                ".o_neon_dashboard_viewas option[value='hr']", 1,
                "switcher offers HR")

            # (1) Landed on the Bookkeeper lens (bookkeeper-unique tile
            # present; HR-unique tile absent).
            smoke.assert_visible(
                ".widget--kpi_pending_invoices",
                "landed on Bookkeeper (Pending Invoices tile present)")
            smoke.assert_count(
                ".widget--kpi_hr_headcount", 0,
                "HR Headcount tile absent on Bookkeeper lens")
            smoke.screenshot("dualrole_lands_bookkeeper")

            # (3) Switch to HR -> HR-unique tile appears, bookkeeper tile
            # gone.
            smoke.page.locator(
                ".o_neon_dashboard_viewas").select_option("hr")
            smoke.assert_visible(
                ".widget--kpi_hr_headcount",
                "after View-As=hr: HR Headcount tile present")
            smoke.assert_count(
                ".widget--kpi_pending_invoices", 0,
                "Bookkeeper tile gone on HR lens")
            smoke.screenshot("dualrole_switched_hr")

            # (4) Switch BACK to Bookkeeper -- the round-trip.
            smoke.page.locator(
                ".o_neon_dashboard_viewas").select_option("bookkeeper")
            smoke.assert_visible(
                ".widget--kpi_pending_invoices",
                "round-trip back to Bookkeeper (Pending Invoices present)")
            smoke.assert_count(
                ".widget--kpi_hr_headcount", 0,
                "HR tile gone after switching back to Bookkeeper")
            smoke.screenshot("dualrole_back_to_bookkeeper")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(run())
