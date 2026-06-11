"""P-HR HR client render -- browser smoke (the DOM half of the proof).

Scenario 1 (HR lens RENDERS -- the bug this milestone fixes):
  HR-admin opens the dashboard -> exactly 5 widget--kpi_hr_* tiles +
  3 widget--block_hr_* panels render; the Headcount tile shows the
  real active-employee count; the filter row shows exactly one "All"
  chip (was: 4 director chips via the fall-through); and at least one
  panel shows the empty-state line (sparse HR data reads as *empty*,
  not *broken*).

Scenario 2 (BYTE-EQUIVALENCE at the DOM -- the binding constraint):
  A superuser opens the default (director) dashboard -> ZERO
  widget--kpi_hr_* and ZERO widget--block_hr_* nodes exist. The HR
  markup is inert for non-HR lenses (isWidgetVisible guards false).

Run after -u neon_dashboard + the asset-bundle delete + force-recreate;
the served bundle must already carry the HR keys (else scenario 1 fails
exactly as the live bug did -- which is the point of this smoke).
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke  # noqa: F401


BASE_URL = "http://localhost:8069"
DB = "neon_crm"
DASH = "neon_dashboard.action_neon_dashboard_server"

KPI_SEL = "[class*='widget--kpi_hr_']"
BLOCK_SEL = "[class*='widget--block_hr_']"


_SETUP = """
Users = env['res.users']

def _wipe_login(login):
    olds = Users.sudo().with_context(active_test=False).search(
        [('login','=',login)])
    for u in olds:
        u.write({'login': login + '_OLD_' + str(u.id), 'active': False})

for login in ('phr_hrr_br_hr', 'phr_hrr_br_super'):
    _wipe_login(login)

g_hr_admin = env.ref('neon_hr.group_neon_hr_admin')
g_super = env.ref('neon_core.group_neon_superuser')

u_hr = Users.sudo().with_context(no_reset_password=True).create({
    'name': 'PHR-HRR BR HR', 'login': 'phr_hrr_br_hr', 'password': 'test123',
    'groups_id': [(4, env.ref('base.group_user').id), (4, g_hr_admin.id)],
})
u_super = Users.sudo().with_context(no_reset_password=True).create({
    'name': 'PHR-HRR BR Super', 'login': 'phr_hrr_br_super',
    'password': 'test123',
    'groups_id': [(4, env.ref('base.group_user').id), (4, g_super.id)],
})
emp_count = env['hr.employee'].sudo().search_count([('active','=',True)])
env.cr.commit()
print('IDS_JSON=' + repr(
    {'hr': u_hr.id, 'super': u_super.id, 'headcount': emp_count}))
"""


_TEARDOWN = """
Users = env['res.users']
for login in ('phr_hrr_br_hr', 'phr_hrr_br_super'):
    u = Users.sudo().with_context(active_test=False).search(
        [('login','=',login)], limit=1)
    if u:
        u.write({'active': False})
env.cr.commit()
print('TEARDOWN OK')
"""


def _shell(script):
    p = subprocess.run(
        ["docker", "compose", "--project-directory",
         "C:/Users/Neon/neon-odoo", "exec", "-T", "odoo",
         "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"),
        capture_output=True, timeout=180)
    return (p.stdout + p.stderr).decode("utf-8", errors="replace")


def _setup():
    out = _shell(_SETUP)
    idx = out.find("IDS_JSON=")
    if idx < 0:
        print("[phr_hrr] SETUP FAILED:")
        print(out[-1500:])
        sys.exit(2)
    depth = 0
    start = out.find("{", idx)
    for i in range(start, len(out)):
        if out[i] == "{":
            depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                return eval(out[start:i + 1])  # noqa: S307
    print("[phr_hrr] SETUP FAILED parse:")
    print(out[-1500:])
    sys.exit(2)


def _teardown():
    out = _shell(_TEARDOWN)
    if "TEARDOWN OK" not in out:
        print("[phr_hrr] TEARDOWN WARN:")
        print(out[-500:])


def _count(smoke, sel):
    return len(smoke.page.query_selector_all(sel))


def run():
    ids = _setup()
    try:
        with BrowserSmoke("phr_hr_render") as smoke:

            # --- Scenario 1: the HR lens actually renders -------------
            with smoke.scenario(
                    "HR admin: HR lens renders 5 tiles + 3 panels + "
                    "1 'All' chip + empty-state line"):
                smoke.login("phr_hrr_br_hr")
                smoke.page.goto(f"{BASE_URL}/web#action={DASH}")
                rendered = True
                try:
                    smoke.page.wait_for_selector(
                        "[class*='widget--kpi_hr_headcount']",
                        timeout=12000)
                except Exception:
                    rendered = False
                smoke.page.wait_for_timeout(600)

                n_kpi = _count(smoke, KPI_SEL)
                n_block = _count(smoke, BLOCK_SEL)
                smoke._record_assert(
                    "HR lens renders 5 KPI tiles + 3 panels",
                    expect="5 kpi_hr_* + 3 block_hr_*",
                    actual=f"kpi={n_kpi} block={n_block} "
                           f"(headcount tile rendered={rendered})",
                    passed=rendered and n_kpi == 5 and n_block == 3)

                hc_txt = ""
                try:
                    hc_txt = smoke.page.inner_text(
                        "[class*='widget--kpi_hr_headcount'] "
                        ".o_neon_kpi_value").strip()
                except Exception:
                    pass
                smoke._record_assert(
                    "Headcount tile shows the real active-employee count",
                    expect=f"value == {ids['headcount']}",
                    actual=f"tile text={hc_txt!r}",
                    passed=hc_txt == str(ids["headcount"]))

                chips = smoke.page.query_selector_all(".o_neon_filter_chip")
                chip_txt = [c.inner_text().strip() for c in chips]
                smoke._record_assert(
                    "HR lens shows exactly one 'All' filter chip "
                    "(not the director fall-through)",
                    expect="['All']",
                    actual=repr(chip_txt),
                    passed=chip_txt == ["All"])

                # SCOPED to the HR panels: the unscoped
                # .o_neon_block_empty_msg also matches block_alerts /
                # block_tasks (both in the HR layout + empty for a fresh
                # fixture user), which would false-PASS even if all 3 HR
                # panels failed to render their empty line. [review fix]
                n_empty = _count(
                    smoke,
                    "[class*='widget--block_hr_'] .o_neon_block_empty_msg")
                smoke._record_assert(
                    "At least one HR panel shows its OWN empty-state line "
                    "(scoped to widget--block_hr_*, not alerts/tasks)",
                    expect=">=1 HR-panel empty-state message",
                    actual=f"hr_empty_msgs={n_empty}",
                    passed=n_empty >= 1)

            # --- Scenario 2: byte-equivalence at the DOM --------------
            with smoke.scenario(
                    "Superuser (director lens): ZERO HR widget nodes "
                    "in the DOM (other lenses byte-equivalent)"):
                smoke.login("phr_hrr_br_super")
                smoke.page.goto(f"{BASE_URL}/web#action={DASH}")
                try:
                    smoke.page.wait_for_selector(
                        ".o_neon_dashboard", timeout=12000)
                except Exception:
                    pass
                smoke.page.wait_for_timeout(600)

                n_kpi = _count(smoke, KPI_SEL)
                n_block = _count(smoke, BLOCK_SEL)
                smoke._record_assert(
                    "Director DOM carries no HR widget nodes",
                    expect="0 kpi_hr_* + 0 block_hr_*",
                    actual=f"kpi={n_kpi} block={n_block}",
                    passed=n_kpi == 0 and n_block == 0)
    finally:
        _teardown()


if __name__ == "__main__":
    run()
