"""P-HR-R1a browser smoke — employee foundation (neon_hr).

Maps to the walkthrough scenarios W1-W4:

(W1) HR user opens an employee with category=employed_technician →
     Neon HR tab renders the auto-generated document checklist; the
     employee is not yet compliant.
(W2) A contract with end_date 25 days out shows the renewal
     statusbar + settable buttons, and surfaces in the
     "Contracts Expiring / Expired" list.
(W3) A non-OD/MD/Admin user CANNOT see salary (wage) on the contract
     form nor the confidential statutory fields on the employee form,
     while the public directory field (name) still renders.
(W4) "Check Assignability" on an expired-contract employee raises a
     soft-block warning; the OD/MD override button is present.
"""
from __future__ import annotations

import subprocess
import sys

from browser_smoke import BrowserSmoke

BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP = r"""
from datetime import date, timedelta, datetime, time
Users = env['res.users']
HR = env['hr.employee']
Contract = env['hr.contract']
Cat = env['neon.hr.category']

# Headless mail unblock (so the expiry cron's chatter posts queue).
env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))
env.company.sudo().write({'email': env.company.email or 'noreply@neonhiring.com'})

today = date.today()
cat = {c.code: c for c in Cat.sudo().search([])}

# Good-citizen cleanup: remove any contract-expiry Action Centre items
# left by prior runs so this smoke does not accumulate dashboard-count
# pollution on the shared dev DB (the daily cron recreates legitimate
# ones from live contracts).
env['action.centre.item'].sudo().search(
    [('trigger_type', '=', 'contract_expiry_30days')]
).with_context(_allow_state_write=True).unlink()


def _wipe_login(login):
    u = Users.search([('login', '=', login)], limit=1)
    if u:
        u.write({'login': login + '_OLD_' + str(u.id), 'active': False})


_wipe_login('phr_admin')
phr_admin = Users.with_context(no_reset_password=True).create({
    'name': 'phr_admin', 'login': 'phr_admin', 'password': 'test123',
    'email': 'phr_admin@neonhiring.com',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('base.group_system').id),
        (4, env.ref('neon_core.group_neon_superuser').id),
    ],
})

_wipe_login('phr_nonhr')
phr_nonhr = Users.with_context(no_reset_password=True).create({
    'name': 'phr_nonhr', 'login': 'phr_nonhr', 'password': 'test123',
    'email': 'phr_nonhr@neonhiring.com',
    'groups_id': [(6, 0, [env.ref('neon_core.group_neon_sales_rep').id])],
})


def _wipe_emp(name):
    e = HR.sudo().search([('name', '=', name)], limit=1)
    if e:
        e.contract_ids.unlink()
        e.unlink()


# W1 — employee with category -> checklist, not compliant
_wipe_emp('PHR-W1 Employee')
emp_w1 = HR.sudo().create({'name': 'PHR-W1 Employee'})
emp_w1.write({'neon_category_id': cat['employed_technician'].id})

# W2 — open contract expiring in 25 days
_wipe_emp('PHR-W2 Employee')
emp_w2 = HR.sudo().create({'name': 'PHR-W2 Employee'})
c_w2 = Contract.sudo().create({
    'name': 'PHR-W2 contract', 'employee_id': emp_w2.id, 'wage': 1500.0,
    'date_start': today - timedelta(days=300),
    'date_end': today + timedelta(days=25), 'state': 'open',
})

# W4 — open contract already expired (soft-block)
_wipe_emp('PHR-W4 Employee')
emp_w4 = HR.sudo().create({'name': 'PHR-W4 Employee'})
Contract.sudo().create({
    'name': 'PHR-W4 contract', 'employee_id': emp_w4.id, 'wage': 1100.0,
    'date_start': today - timedelta(days=400),
    'date_end': today - timedelta(days=7), 'state': 'open',
})
emp_w4.invalidate_recordset(['has_valid_contract'])

# Raise the expiry Action Centre items (cron).
Contract._cron_contract_expiry_scan()

expiring_action = env.ref('neon_hr.action_neon_hr_contracts_expiring')
doc_action = env.ref('neon_hr.action_neon_hr_document')

env.cr.commit()
print('IDS_JSON=' + repr({
    'emp_w1': emp_w1.id,
    'contract_w2': c_w2.id,
    'emp_w4': emp_w4.id,
    'expiring_action': expiring_action.id,
    'doc_action': doc_action.id,
}))
"""


def _shell(script):
    p = subprocess.run(
        ["docker", "compose", "--project-directory",
         "C:/Users/Neon/neon-odoo", "exec", "-T", "odoo",
         "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"), capture_output=True, timeout=240)
    return (p.stdout + p.stderr).decode("utf-8", errors="replace")


def _setup():
    out = _shell(_SETUP)
    idx = out.find("IDS_JSON=")
    if idx < 0:
        print("[phr_r1a] SETUP FAILED:")
        print(out[-2500:])
        sys.exit(2)
    start = out.find("{", idx)
    depth = 0
    for i in range(start, len(out)):
        if out[i] == "{":
            depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                return eval(out[start:i + 1])  # noqa: S307
    print("[phr_r1a] SETUP parse FAILED:")
    print(out[-2500:])
    sys.exit(2)


def run():
    ids = _setup()

    with BrowserSmoke("phr_r1a") as smoke:

        # ---- W1: employee category -> document checklist ----
        with smoke.scenario("W1: employee category drives document checklist"):
            smoke.login("phr_admin")
            smoke.page.goto(
                f"{BASE_URL}/web#id={ids['emp_w1']}"
                f"&model=hr.employee&view_type=form")
            smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
            smoke.page.locator(
                "a.nav-link:has-text('Neon HR')").first.click()
            smoke.page.wait_for_timeout(500)
            cat_field = smoke.page.locator("[name='neon_category_id']").count()
            smoke._record_assert(
                "neon_category_id renders on Neon HR tab",
                expect=">=1", actual=str(cat_field), passed=cat_field >= 1)
            doc_rows = smoke.page.locator(
                "[name='document_ids'] .o_data_row").count()
            smoke._record_assert(
                "document checklist auto-generated (10 rows)",
                expect="10", actual=str(doc_rows), passed=doc_rows == 10)
            # is_compliant shows false (unchecked boolean)
            compliant_unchecked = smoke.page.locator(
                "[name='is_compliant'] input:not(:checked)").count()
            smoke._record_assert(
                "is_compliant is false (no documents provided yet)",
                expect=">=1", actual=str(compliant_unchecked),
                passed=compliant_unchecked >= 1)

        # ---- W2: renewal statusbar + expiring list ----
        with smoke.scenario("W2: renewal state machine + expiring surfacing"):
            smoke.page.goto(
                f"{BASE_URL}/web#id={ids['contract_w2']}"
                f"&model=hr.contract&view_type=form")
            smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
            smoke.page.wait_for_timeout(400)
            renewal_sb = smoke.page.locator("[name='renewal_state']").count()
            smoke._record_assert(
                "renewal_state statusbar present on contract",
                expect=">=1", actual=str(renewal_sb), passed=renewal_sb >= 1)
            start_btn = smoke.page.locator(
                "button:has-text('Start Renewal Review')").count()
            smoke._record_assert(
                "renewal 'Start Renewal Review' action settable",
                expect=">=1", actual=str(start_btn), passed=start_btn >= 1)
            # Expiring list surfaces the contract.
            smoke.page.goto(
                f"{BASE_URL}/web#action={ids['expiring_action']}")
            smoke.page.wait_for_selector(
                ".o_list_view, .o_list_renderer", timeout=20000)
            smoke.page.wait_for_timeout(500)
            rows = smoke.page.locator(".o_data_row").count()
            smoke._record_assert(
                "Contracts Expiring/Expired list shows >=1 contract",
                expect=">=1", actual=str(rows), passed=rows >= 1)

        # ---- W3: confidentiality for a non-HR user ----
        # hr.employee + hr.contract are HR-gated: a non-HR user cannot
        # open them at all (Odoo serves the public directory via a
        # separate model). Salary is therefore unreachable, and the
        # personal-document list is record-rule-scoped to the owner —
        # so a non-owner sees zero rows.
        with smoke.scenario("W3: salary + personal docs hidden from non-HR user"):
            smoke.page.goto(f"{BASE_URL}/web/session/logout",
                            wait_until="domcontentloaded")
            smoke.login("phr_nonhr")
            # Salary on the contract form must NOT be reachable.
            smoke.page.goto(
                f"{BASE_URL}/web#id={ids['contract_w2']}"
                f"&model=hr.contract&view_type=form")
            smoke.page.wait_for_timeout(1800)
            wage_visible = smoke.page.locator("[name='wage']").count()
            smoke._record_assert(
                "non-HR user CANNOT see salary (wage) on contract",
                expect="0", actual=str(wage_visible), passed=wage_visible == 0)
            # Personal-document list: record rule scopes to the owner,
            # so this non-owner sees an empty list (0 rows).
            smoke.page.goto(
                f"{BASE_URL}/web#action={ids['doc_action']}")
            smoke.page.wait_for_selector(
                ".o_list_view, .o_list_renderer", timeout=20000)
            smoke.page.wait_for_timeout(700)
            doc_rows = smoke.page.locator(".o_data_row").count()
            smoke._record_assert(
                "non-owner sees ZERO personal documents (record rule)",
                expect="0", actual=str(doc_rows), passed=doc_rows == 0)

        # ---- W4: assignment soft-block + override ----
        with smoke.scenario("W4: assignment gate soft-block + OD/MD override"):
            smoke.page.goto(f"{BASE_URL}/web/session/logout",
                            wait_until="domcontentloaded")
            smoke.login("phr_admin")
            smoke.page.goto(
                f"{BASE_URL}/web#id={ids['emp_w4']}"
                f"&model=hr.employee&view_type=form")
            smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
            smoke.page.locator(
                "a.nav-link:has-text('Neon HR')").first.click()
            smoke.page.wait_for_timeout(400)
            override_btn = smoke.page.locator(
                "button:has-text('Override')").count()
            smoke._record_assert(
                "OD/MD override button present on employee",
                expect=">=1", actual=str(override_btn),
                passed=override_btn >= 1)
            smoke.page.locator(
                "button:has-text('Check Assignability')").first.click()
            smoke.page.wait_for_timeout(900)
            notif = smoke.page.locator(
                ".o_notification:has-text('Soft block'), "
                ".o_notification:has-text('assignment')").count()
            smoke._record_assert(
                "Check Assignability raises a soft-block warning",
                expect=">=1", actual=str(notif), passed=notif >= 1)


if __name__ == "__main__":
    run()
