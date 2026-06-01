"""P-HR-R3a browser smoke — driver licences + competency gate UI.

W1 Driver Licences list + licence form (class/expiry/state badge);
W2 Crew Assignment Gate list (gate-state badges: competency gap /
   no-employee);
W3 Employee Fleet & Competency tab (is_driver + licence tree).
"""
from __future__ import annotations

import subprocess
import sys

from browser_smoke import BrowserSmoke

BASE_URL = "http://localhost:8069"
DB = "neon_crm"

_SETUP = r"""
from datetime import date, timedelta
env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))
env.company.sudo().write({'email': env.company.email or 'noreply@neonhiring.com'})
Users = env['res.users']; HR = env['hr.employee']
Partner = env['res.partner']; Crew = env['commercial.job.crew']
Lic = env['neon.hr.licence']; Comp = env['neon.hr.competency']
EComp = env['neon.hr.employee.competency']; RoleComp = env['neon.hr.role.competency']
ICP = env['ir.config_parameter'].sudo()
cat = env['neon.hr.category'].sudo().search([('code', '=', 'employed_technician')], limit=1)
today = date.today()
ICP.set_param('neon_hr.competency_gate_mode', 'warn')
ICP.set_param('neon_hr.licence_expiry_lead_days', '30')


def _wipe_login(login):
    u = Users.search([('login', '=', login)], limit=1)
    if u:
        u.write({'login': login + '_OLD_' + str(u.id), 'active': False})


_wipe_login('phr_r3a_admin')
admin = Users.with_context(no_reset_password=True).create({
    'name': 'phr_r3a_admin', 'login': 'phr_r3a_admin', 'password': 'test123',
    'email': 'phr_r3a_admin@neonhiring.com',
    'groups_id': [(4, env.ref('base.group_user').id),
                  (4, env.ref('base.group_system').id),
                  (4, env.ref('neon_core.group_neon_superuser').id)]})

# wipe prior PHR-R3A-B fixtures (jobs cascade their crew)
for j in env['commercial.job'].sudo().search([('name', '=like', 'PHR-R3A-B%')]):
    j.crew_ids.unlink(); j.unlink()
for e in HR.sudo().search([('name', '=like', 'PHR-R3A-B%')]):
    Lic.sudo().search([('employee_id', '=', e.id)]).unlink()
    EComp.sudo().search([('employee_id', '=', e.id)]).unlink()
    e.unlink()
RoleComp.sudo().search([('crew_role', '=', 'tech')]).unlink()
Comp.sudo().search([('code', '=', 'phr_r3a_b_height')]).unlink()
Partner.sudo().search([('name', '=like', 'PHR-R3A-B%')]).unlink()

# a driver with a valid licence
p_drv = Partner.sudo().create({'name': 'PHR-R3A-B Driver contact'})
emp_drv = HR.sudo().create({'name': 'PHR-R3A-B Driver',
                            'neon_category_id': cat.id, 'work_contact_id': p_drv.id})
lic = Lic.sudo().create({'employee_id': emp_drv.id, 'licence_class': 'class_3',
                         'licence_number': 'B-VALID', 'issue_date': today - timedelta(days=300),
                         'expiry_date': today + timedelta(days=200)})

# a tech with a competency gap (warn mode -> assignment allowed + warning)
comp = Comp.sudo().create({'name': 'PHR-R3A-B Working at Heights',
                           'code': 'phr_r3a_b_height', 'requires_expiry': True})
RoleComp.sudo().create({'crew_role': 'tech', 'competency_ids': [(6, 0, [comp.id])]})
p_tech = Partner.sudo().create({'name': 'PHR-R3A-B Tech contact'})
emp_tech = HR.sudo().create({'name': 'PHR-R3A-B Tech',
                             'neon_category_id': cat.id, 'work_contact_id': p_tech.id})

venue = Partner.sudo().search([('is_venue', '=', True)], limit=1)
if not venue:
    venue = Partner.sudo().create({'name': 'PHR-R3A-B Venue', 'is_venue': True})
job = env['commercial.job'].sudo().create({
    'name': 'PHR-R3A-B JOB', 'partner_id': p_drv.id, 'venue_id': venue.id,
    'state': 'active', 'event_date': today})
crew_warn = Crew.sudo().create({'job_id': job.id, 'partner_id': p_tech.id, 'role': 'tech'})
p_free = Partner.sudo().create({'name': 'PHR-R3A-B Freelancer'})
crew_free = Crew.sudo().create({'job_id': job.id, 'partner_id': p_free.id, 'role': 'driver'})

env.cr.commit()
print('IDS_JSON=' + repr({
    'lic_id': lic.id, 'emp_id': emp_drv.id, 'job_id': job.id,
    'lic_action': env.ref('neon_hr.action_neon_hr_licence').id,
    'gate_action': env.ref('neon_hr.action_neon_hr_crew_gate').id,
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
        print("[phr_r3a] SETUP FAILED:")
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
    print("[phr_r3a] SETUP parse FAILED:", out[-1500:])
    sys.exit(2)


def run():
    ids = _setup()
    with BrowserSmoke("phr_r3a") as smoke:

        with smoke.scenario("W1: Driver Licences list + licence form"):
            smoke.login("phr_r3a_admin")
            smoke.page.goto(f"{BASE_URL}/web#action={ids['lic_action']}")
            smoke.page.wait_for_selector(".o_list_view, .o_list_renderer",
                                         timeout=20000)
            smoke.page.wait_for_timeout(600)
            rows = smoke.page.locator(
                ".o_data_row:has-text('PHR-R3A-B Driver')").count()
            smoke._record_assert("driver licence shows in Licences list",
                                 expect=">=1", actual=str(rows), passed=rows >= 1)
            smoke.page.goto(f"{BASE_URL}/web#id={ids['lic_id']}"
                            f"&model=neon.hr.licence&view_type=form")
            smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
            smoke.page.wait_for_timeout(500)
            for fld in ("licence_class", "expiry_date", "state"):
                c = smoke.page.locator(f"[name='{fld}']").count()
                smoke._record_assert(f"licence form {fld} renders",
                                     expect=">=1", actual=str(c), passed=c >= 1)

        with smoke.scenario("W2: Crew Assignment Gate list (gate states)"):
            smoke.page.goto(f"{BASE_URL}/web#action={ids['gate_action']}")
            smoke.page.wait_for_selector(".o_list_view, .o_list_renderer",
                                         timeout=20000)
            smoke.page.wait_for_timeout(700)
            warn = smoke.page.locator(
                ".o_data_row:has-text('PHR-R3A-B Tech contact')").count()
            smoke._record_assert("competency-gap crew row present",
                                 expect=">=1", actual=str(warn), passed=warn >= 1)
            free = smoke.page.locator(
                ".o_data_row:has-text('PHR-R3A-B Freelancer')").count()
            smoke._record_assert("no-employee (freelancer) crew row present",
                                 expect=">=1", actual=str(free), passed=free >= 1)
            badge = smoke.page.locator(
                ".o_data_row:has-text('No Employee Record'), "
                ".o_data_row:has-text('Competency Gap')").count()
            smoke._record_assert("gate-state badge rendered on a row",
                                 expect=">=1", actual=str(badge), passed=badge >= 1)

        with smoke.scenario("W3: Employee Fleet & Competency tab"):
            smoke.page.goto(f"{BASE_URL}/web#id={ids['emp_id']}"
                            f"&model=hr.employee&view_type=form")
            smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
            smoke.page.wait_for_timeout(600)
            tab = smoke.page.locator("a.nav-link:has-text('Fleet')")
            smoke._record_assert("Fleet & Competency tab present",
                                 expect=">=1", actual=str(tab.count()),
                                 passed=tab.count() >= 1)
            if tab.count():
                tab.first.click()
                smoke.page.wait_for_timeout(600)
            drv = smoke.page.locator("[name='is_driver']").count()
            smoke._record_assert("is_driver field renders on Fleet tab",
                                 expect=">=1", actual=str(drv), passed=drv >= 1)
            lic_rows = smoke.page.locator(
                "[name='licence_ids'] .o_data_row").count()
            smoke._record_assert("licence row renders on Fleet tab",
                                 expect=">=1", actual=str(lic_rows),
                                 passed=lic_rows >= 1)

    sys.exit(smoke.summary())


if __name__ == "__main__":
    run()
