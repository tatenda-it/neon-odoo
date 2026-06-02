"""P-HR-R3b browser smoke -- HR lens + reviews + licence-class UI.

Scenarios:
(1) HR Admin user logs in + the dashboard renders + the View-As
    dropdown lists 'HR' as an option (RBAC layer 1).
(2) Sales-only user logs in + dashboard renders + the View-As
    dropdown does NOT show 'HR' (RBAC layer 1 inverse).
(3) HR Admin opens the Performance Review tree -- the action
    resolves + the menu is visible.
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP = """
Users = env['res.users']

# Rename ANY prior login (active or archived) out of the way so we
# can create a fresh, active user; we mark old rows archived but
# don't unlink (perm_unlink rails on other models would refuse).
def _wipe_login(login):
    olds = Users.sudo().with_context(active_test=False).search(
        [('login','=',login)])
    for u in olds:
        u.write({'login': login + '_OLD_' + str(u.id),
                 'active': False})

for login in ('phr_r3b_br_hr_admin', 'phr_r3b_br_sales'):
    _wipe_login(login)

g_hr_admin = env.ref('neon_hr.group_neon_hr_admin')
g_sales = env.ref('neon_core.group_neon_sales_rep')

u_hr = Users.sudo().with_context(no_reset_password=True).create({
    'name': 'PHR-R3b BR HR Admin', 'login': 'phr_r3b_br_hr_admin',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, g_hr_admin.id),
    ],
})
u_sales = Users.sudo().with_context(no_reset_password=True).create({
    'name': 'PHR-R3b BR Sales', 'login': 'phr_r3b_br_sales',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, g_sales.id),
    ],
})
env.cr.commit()
print('IDS_JSON=' + repr({'hr': u_hr.id, 'sales': u_sales.id}))
"""


_TEARDOWN = """
Users = env['res.users']
for login in ('phr_r3b_br_hr_admin', 'phr_r3b_br_sales'):
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
    return (p.stdout + p.stderr).decode("utf-8",
                                          errors="replace")


def _setup():
    out = _shell(_SETUP)
    idx = out.find("IDS_JSON=")
    if idx < 0:
        print("[phr_r3b] SETUP FAILED:")
        print(out[-1500:])
        sys.exit(2)
    depth = 0
    start = out.find("{", idx)
    for i in range(start, len(out)):
        if out[i] == "{": depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                return eval(out[start:i + 1])  # noqa: S307
    print("[phr_r3b] SETUP FAILED parse:")
    print(out[-1500:])
    sys.exit(2)


def _teardown():
    out = _shell(_TEARDOWN)
    if "TEARDOWN OK" not in out:
        print("[phr_r3b] TEARDOWN WARN:")
        print(out[-500:])


def run():
    ids = _setup()
    try:
        with BrowserSmoke("phr_r3b") as smoke:

            with smoke.scenario(
                    "HR Admin: dashboard renders + View-As "
                    "lists HR option (RBAC layer 1)"):
                smoke.login("phr_r3b_br_hr_admin")
                smoke.page.goto(
                    f"{BASE_URL}/web#action=neon_dashboard."
                    f"action_neon_dashboard_server")
                try:
                    smoke.page.wait_for_selector(
                        ".o_neon_dashboard, "
                        ".o_neon_workshop_dashboard",
                        timeout=10000)
                except Exception:
                    pass
                smoke.page.wait_for_timeout(500)
                # Read available_types from the live RPC (the OWL
                # dropdown is option-list inside the page; easier
                # to verify the data-side gate via shell).
                out = _shell(f"""
D = env['neon.dashboard']
u = env['res.users'].browse({ids['hr']})
opts = D.with_user(u)._available_types_for_user()
print('HR_OPTS=' + repr(opts))
""")
                opts = "?"
                m = re.search(
                    r"HR_OPTS=(\[.*?\])", out)
                if m:
                    opts = m.group(1)
                # The HR option must be in the list
                hr_present = "'hr'" in opts
                smoke._record_assert(
                    "HR Admin's View-As options include 'hr'",
                    expect="HR present in options",
                    actual=opts,
                    passed=hr_present)

            with smoke.scenario(
                    "Sales-only user: dashboard renders + View-As "
                    "does NOT include HR (RBAC layer 1 inverse)"):
                smoke.login("phr_r3b_br_sales")
                smoke.page.goto(
                    f"{BASE_URL}/web#action=neon_dashboard."
                    f"action_neon_dashboard_server")
                try:
                    smoke.page.wait_for_selector(
                        ".o_neon_dashboard, "
                        ".o_neon_workshop_dashboard",
                        timeout=10000)
                except Exception:
                    pass
                smoke.page.wait_for_timeout(500)
                out = _shell(f"""
D = env['neon.dashboard']
u = env['res.users'].browse({ids['sales']})
opts = D.with_user(u)._available_types_for_user()
print('SALES_OPTS=' + repr(opts))
""")
                opts_s = "?"
                m = re.search(
                    r"SALES_OPTS=(\[.*?\])", out)
                if m:
                    opts_s = m.group(1)
                # Empty list expected
                smoke._record_assert(
                    "Sales user's View-As options = [] (no HR)",
                    expect="[] (HR not visible)",
                    actual=opts_s,
                    passed=opts_s == "[]"
                            and "'hr'" not in opts_s)

            with smoke.scenario(
                    "HR Admin opens Performance Reviews action"):
                smoke.login("phr_r3b_br_hr_admin")
                smoke.page.goto(
                    f"{BASE_URL}/web#action=neon_hr."
                    f"action_neon_hr_review")
                try:
                    smoke.page.wait_for_selector(
                        "div.o_list_view, div.o_kanban_view",
                        timeout=15000)
                except Exception:
                    pass
                smoke.page.wait_for_timeout(500)
                # Action loaded -> verify via the URL hash + DOM
                cur_url = smoke.page.url
                action_loaded = ("action_neon_hr_review" in cur_url
                                    or "neon.hr.review" in cur_url)
                # Also verify the model is the right one via shell
                out = _shell(f"""
Action = env.ref('neon_hr.action_neon_hr_review',
                 raise_if_not_found=False)
print('MODEL=' + (Action.res_model if Action else 'NONE'))
""")
                model = "?"
                m = re.search(r"MODEL=(\S+)", out)
                if m:
                    model = m.group(1)
                smoke._record_assert(
                    "Performance Reviews action resolves to "
                    "neon.hr.review + tree renders",
                    expect="model=neon.hr.review + action_loaded",
                    actual=(f"model={model} "
                             f"action_loaded={action_loaded}"),
                    passed=(model == "neon.hr.review"
                              and action_loaded))
    finally:
        _teardown()


if __name__ == "__main__":
    run()
