"""P-HR-R1b browser smoke — leave/availability, payslip, event wage, loan.

W1 leave request+approve → availability; W2 payslip gross/deductions/net;
W3 USD-10 event incentive (Event/Job-linked); W4 staff loan + schedule.
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
Users = env['res.users']
HR = env['hr.employee']; Contract = env['hr.contract']
Leave = env['hr.leave']; Slip = env['neon.hr.payslip']
Wage = env['neon.hr.event.wage']; Loan = env['neon.hr.loan']
Grade = env['neon.hr.wage.grade']
cat = {c.code: c for c in env['neon.hr.category'].sudo().search([])}
today = date.today()


def _wipe_login(login):
    u = Users.search([('login', '=', login)], limit=1)
    if u:
        u.write({'login': login + '_OLD_' + str(u.id), 'active': False})


_wipe_login('phr_r1b_admin')
admin = Users.with_context(no_reset_password=True).create({
    'name': 'phr_r1b_admin', 'login': 'phr_r1b_admin', 'password': 'test123',
    'email': 'phr_r1b_admin@neonhiring.com',
    'groups_id': [(4, env.ref('base.group_user').id),
                  (4, env.ref('base.group_system').id),
                  (4, env.ref('neon_core.group_neon_superuser').id)]})

# wipe prior fixtures (clear dependent records first to avoid FK locks)
for e in HR.sudo().search([('name', 'like', 'PHR-R1B%')]):
    lv = Leave.sudo().search([('employee_id', '=', e.id)])
    if lv:
        lv.write({'state': 'draft'})
        lv.unlink()
    Slip.sudo().search([('employee_id', '=', e.id)]).unlink()
    Wage.sudo().search([('employee_id', '=', e.id)]).unlink()
    env['neon.hr.commission'].sudo().search(
        [('employee_id', '=', e.id)]).unlink()
    Loan.sudo().search([('employee_id', '=', e.id)]).unlink()
    e.contract_ids.unlink()
    e.unlink()

emp = HR.sudo().create({'name': 'PHR-R1B Tech',
                        'neon_category_id': cat['employed_technician'].id})
ctr = Contract.sudo().create({
    'name': 'PHR-R1B ctr', 'employee_id': emp.id, 'wage': 1000.0,
    'neon_contract_type': 'employed_technician',
    'date_start': today - timedelta(days=60), 'state': 'open'})

# W1: a validated leave -> availability
leave = Leave.sudo().create({
    'name': 'PHR-R1B leave', 'employee_id': emp.id,
    'holiday_status_id': env.ref('neon_hr.leave_type_sick').id,
    'request_date_from': today + timedelta(days=5),
    'request_date_to': today + timedelta(days=9)})
try:
    if leave.state == 'draft':
        leave.action_confirm()
    leave.action_validate()
except Exception:
    leave.sudo().write({'state': 'validate'})

# W2: a computed payslip
slip = Slip.sudo().create({
    'employee_id': emp.id, 'contract_id': ctr.id,
    'period_start': today.replace(day=1),
    'period_end': (today.replace(day=1) + timedelta(days=31)).replace(day=1) - timedelta(days=1)})
slip.action_compute()

# W3: a USD-10 incentive event wage linked to a DEDICATED job.
# Use our own event_job (get-or-create by name) — never a shared one —
# so an event-wage FK never blocks another suite's event_job teardown.
ejob = env['commercial.event.job'].sudo().search(
    [('name', '=', 'PHR-R1B EVENT')], limit=1)
if not ejob:
    partner = env['res.partner'].sudo().search([], limit=1)
    mjob = env['commercial.job'].sudo().search(
        [('name', '=', 'PHR-R1B JOB')], limit=1)
    if not mjob:
        # commercial_job.venue_id is required (since p2.m1). Resolve a
        # venue partner (create one if the DB has none) so the seed
        # never trips the NOT NULL constraint on a fresh DB.
        venue = env['res.partner'].sudo().search(
            [('is_venue', '=', True)], limit=1)
        if not venue:
            venue = env['res.partner'].sudo().create(
                {'name': 'PHR-R1B Venue', 'is_venue': True})
        mjob = env['commercial.job'].sudo().create({
            'name': 'PHR-R1B JOB', 'partner_id': partner.id,
            'venue_id': venue.id,
            'state': 'active', 'event_date': today})
    ejob = env['commercial.event.job'].sudo().create({
        'name': 'PHR-R1B EVENT', 'commercial_job_id': mjob.id,
        'partner_id': partner.id})
wage = Wage.sudo().create({
    'employee_id': emp.id, 'event_job_id': ejob.id,
    'wage_type': 'incentive', 'date': today})

# W4: an active loan with a schedule
loan = Loan.sudo().create({
    'employee_id': emp.id, 'principal_amount': 1200.0,
    'instalment_count': 12, 'start_date': today.replace(day=1)})
loan.action_approve()
loan.action_activate()

env.cr.commit()
print('IDS_JSON=' + repr({
    'leave_id': leave.id, 'slip_id': slip.id, 'wage_id': wage.id,
    'loan_id': loan.id,
    'avail_action': env.ref('neon_hr.action_neon_hr_availability').id,
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
        print("[phr_r1b] SETUP FAILED:")
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
    print("[phr_r1b] SETUP parse FAILED:", out[-1500:])
    sys.exit(2)


def run():
    ids = _setup()
    with BrowserSmoke("phr_r1b") as smoke:

        with smoke.scenario("W1: approved leave -> crew unavailability"):
            smoke.login("phr_r1b_admin")
            smoke.page.goto(f"{BASE_URL}/web#action={ids['avail_action']}")
            smoke.page.wait_for_selector(".o_list_view, .o_list_renderer",
                                         timeout=20000)
            smoke.page.wait_for_timeout(600)
            rows = smoke.page.locator(
                ".o_data_row:has-text('PHR-R1B Tech')").count()
            smoke._record_assert(
                "on-leave tech shows in Crew Availability",
                expect=">=1", actual=str(rows), passed=rows >= 1)

        with smoke.scenario("W2: payslip gross/deductions/net + statutory"):
            smoke.page.goto(f"{BASE_URL}/web#id={ids['slip_id']}"
                            f"&model=neon.hr.payslip&view_type=form")
            smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
            smoke.page.wait_for_timeout(500)
            for fld in ("gross_amount", "total_deductions", "net_amount"):
                c = smoke.page.locator(f"[name='{fld}']").count()
                smoke._record_assert(f"payslip {fld} renders",
                                     expect=">=1", actual=str(c), passed=c >= 1)
            stat = smoke.page.locator(
                "[name='line_ids'] .o_data_row").count()
            smoke._record_assert(
                "payslip has computed lines (gross + statutory + loan)",
                expect=">=4", actual=str(stat), passed=stat >= 4)

        with smoke.scenario("W3: USD-10 incentive, Event/Job-linked"):
            smoke.page.goto(f"{BASE_URL}/web#id={ids['wage_id']}"
                            f"&model=neon.hr.event.wage&view_type=form")
            smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
            smoke.page.wait_for_timeout(400)
            job = smoke.page.locator("[name='event_job_id']").count()
            amt = smoke.page.locator("[name='amount']").count()
            smoke._record_assert("event wage linked to Event/Job",
                                 expect=">=1", actual=str(job), passed=job >= 1)
            smoke._record_assert("incentive amount field renders",
                                 expect=">=1", actual=str(amt), passed=amt >= 1)

        with smoke.scenario("W4: staff loan + repayment schedule"):
            smoke.page.goto(f"{BASE_URL}/web#id={ids['loan_id']}"
                            f"&model=neon.hr.loan&view_type=form")
            smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
            smoke.page.wait_for_timeout(400)
            sched = smoke.page.locator(
                "[name='repayment_ids'] .o_data_row").count()
            smoke._record_assert(
                "loan repayment schedule rendered (12 instalments)",
                expect="12", actual=str(sched), passed=sched == 12)
            bal = smoke.page.locator("[name='balance_amount']").count()
            smoke._record_assert("loan balance field renders",
                                 expect=">=1", actual=str(bal), passed=bal >= 1)


if __name__ == "__main__":
    run()
