"""P-HR-R2 browser smoke — accident, disciplinary case, handbook compliance.

W1 accident form (NSSA fields + deadline + state machine);
W2 disciplinary case form (category/severity/evidence/escalation);
W3 handbook "Not Acknowledged" compliance list.
"""
from __future__ import annotations

import subprocess
import sys

from browser_smoke import BrowserSmoke

BASE_URL = "http://localhost:8069"
DB = "neon_crm"

_SETUP = r"""
from datetime import date
env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))
env.company.sudo().write({'email': env.company.email or 'noreply@neonhiring.com'})
Users = env['res.users']; HR = env['hr.employee']
cat = {c.code: c for c in env['neon.hr.category'].sudo().search([])}
today = date.today()


def _wipe_login(login):
    u = Users.search([('login', '=', login)], limit=1)
    if u:
        u.write({'login': login + '_OLD_' + str(u.id), 'active': False})


_wipe_login('phr_r2_admin')
admin = Users.with_context(no_reset_password=True).create({
    'name': 'phr_r2_admin', 'login': 'phr_r2_admin', 'password': 'test123',
    'email': 'phr_r2_admin@neonhiring.com',
    'groups_id': [(4, env.ref('base.group_user').id),
                  (4, env.ref('base.group_system').id),
                  (4, env.ref('neon_core.group_neon_superuser').id)]})

# wipe prior R2 fixtures (clear dependents first)
for e in HR.sudo().search([('name', 'like', 'PHR-R2%')]):
    env['neon.hr.accident'].sudo().search([('employee_id', '=', e.id)]).unlink()
    env['neon.hr.case'].sudo().search([('employee_id', '=', e.id)]).unlink()
    env['neon.hr.overtime'].sudo().search([('employee_id', '=', e.id)]).unlink()
    env['neon.hr.handbook.ack'].sudo().search([('employee_id', '=', e.id)]).unlink()
    e.contract_ids.unlink()
    e.unlink()

emp = HR.sudo().create({'name': 'PHR-R2 Tech',
                        'neon_category_id': cat['employed_technician'].id})
acc = env['neon.hr.accident'].sudo().create({
    'employee_id': emp.id, 'accident_date': today,
    'description': 'Cable trip', 'injury_description': 'Bruise'})
case = env['neon.hr.case'].sudo().create({
    'employee_id': emp.id, 'case_type': 'disciplinary',
    'subject': 'PHR-R2 conduct', 'severity': 'high'})

env.cr.commit()
print('IDS_JSON=' + repr({
    'acc_id': acc.id, 'case_id': case.id,
    'pending_action': env.ref('neon_hr.action_neon_hr_handbook_pending').id,
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
        print("[phr_r2] SETUP FAILED:")
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
    print("[phr_r2] SETUP parse FAILED:", out[-1500:])
    sys.exit(2)


def run():
    ids = _setup()
    with BrowserSmoke("phr_r2") as smoke:

        with smoke.scenario("W1: accident form (NSSA + 14-day deadline)"):
            smoke.login("phr_r2_admin")
            smoke.page.goto(f"{BASE_URL}/web#id={ids['acc_id']}"
                            f"&model=neon.hr.accident&view_type=form")
            smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
            smoke.page.wait_for_timeout(400)
            for fld in ("reporting_deadline", "nssa_submission_ref", "penalty_risk"):
                c = smoke.page.locator(f"[name='{fld}']").count()
                smoke._record_assert(f"accident field {fld} renders",
                                     expect=">=1", actual=str(c), passed=c >= 1)
            btn = smoke.page.locator(
                "button:has-text('Record NSSA Submission')").count()
            smoke._record_assert("NSSA-submit action present",
                                 expect=">=1", actual=str(btn), passed=btn >= 1)

        with smoke.scenario("W2: disciplinary case form"):
            smoke.page.goto(f"{BASE_URL}/web#id={ids['case_id']}"
                            f"&model=neon.hr.case&view_type=form")
            smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
            smoke.page.wait_for_timeout(400)
            for fld in ("case_type", "severity", "attachment_ids", "absence_flow"):
                c = smoke.page.locator(f"[name='{fld}']").count()
                smoke._record_assert(f"case field {fld} renders",
                                     expect=">=1", actual=str(c), passed=c >= 1)

        with smoke.scenario("W3: handbook 'Not Acknowledged' compliance list"):
            smoke.page.goto(f"{BASE_URL}/web#action={ids['pending_action']}")
            smoke.page.wait_for_selector(".o_list_view, .o_list_renderer",
                                         timeout=20000)
            smoke.page.wait_for_timeout(600)
            rows = smoke.page.locator(".o_data_row").count()
            smoke._record_assert(
                "non-acknowledged employees surface as a compliance list",
                expect=">=1", actual=str(rows), passed=rows >= 1)


if __name__ == "__main__":
    run()
