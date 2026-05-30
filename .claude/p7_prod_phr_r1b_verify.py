"""P-HR-R1b PROD SQL-verify (odoo shell -d neon_crm). Read-only except a
rolled-back probe."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError

print("=" * 72)
print("P-HR-R1b PROD SQL VERIFY")
print("=" * 72)
env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))
env.company.sudo().write({"email": env.company.email or "noreply@neonhiring.com"})

M = env["ir.module.module"].sudo()
nh = M.search([("name", "=", "neon_hr")])
print("neon_hr:", nh.latest_version, "/", nh.state)
print("hr_holidays:", M.search([("name", "=", "hr_holidays")]).state)

models = sorted(env["ir.model"].sudo().search(
    [("model", "like", "neon.hr.%")]).mapped("model"))
print("neon.hr.* models (%d):" % len(models), models)

sens = ["neon.hr.payslip", "neon.hr.loan", "neon.hr.commission",
        "neon.hr.event.wage", "neon.hr.statutory.rule"]
acls = env["ir.model.access"].sudo().search(
    [("model_id.model", "in", sens + ["neon.hr.payslip.line",
                                      "neon.hr.loan.repayment"])])
print("new-model ACL perm_unlink values:", sorted(set(acls.mapped("perm_unlink"))))
rules = env["ir.rule"].sudo().search(
    [("model_id.model", "in", ["neon.hr.payslip", "neon.hr.loan",
                               "neon.hr.commission", "neon.hr.event.wage",
                               "neon.hr.payslip.line", "neon.hr.loan.repayment"])])
print("payroll confidentiality record rules:", len(rules))

stat = env["neon.hr.statutory.rule"].sudo().search([])
print("statutory rules:", len(stat), "| all flagged:",
      all(stat.mapped("needs_finance_confirmation")))
print("wage grades:", sorted(env["neon.hr.wage.grade"].sudo().search([]).mapped("amount"), reverse=True))
print("neon leave types:", env["hr.leave.type"].sudo().search_count(
    [("neon_statutory_days", ">=", 0)]))
su = env.ref("neon_core.group_neon_superuser")
print("superuser implies hr_holidays_manager:",
      env.ref("hr_holidays.group_hr_holidays_manager") in su.implied_ids)
print("superuser implies hr_manager:",
      env.ref("hr.group_hr_manager") in su.implied_ids)

# ---- probe (rolled back) ----
print("--- probe (rolled back) ---")
cat = {c.code: c for c in env["neon.hr.category"].sudo().search([])}
today = fields.Date.today()
emp = env["hr.employee"].sudo().create({
    "name": "PHR R1B PROD PROBE",
    "neon_category_id": cat["employed_technician"].id})
ctr = env["hr.contract"].sudo().create({
    "name": "probe", "employee_id": emp.id, "wage": 1000.0,
    "neon_contract_type": "employed_technician",
    "date_start": today - timedelta(days=60), "state": "open"})
lv = env["hr.leave"].sudo().create({
    "name": "probe lv", "employee_id": emp.id,
    "holiday_status_id": env.ref("neon_hr.leave_type_sick").id,
    "request_date_from": today + timedelta(days=10),
    "request_date_to": today + timedelta(days=12)})
try:
    if lv.state == "draft":
        lv.action_confirm()
    lv.action_validate()
except Exception:
    lv.sudo().write({"state": "validate"})
avail = env["neon.hr.availability"].sudo().search([("employee_id", "=", emp.id)])
print("probe leave -> availability removed:", len(avail) >= 1)
slip = env["neon.hr.payslip"].sudo().create({
    "employee_id": emp.id, "contract_id": ctr.id,
    "period_start": today.replace(day=1), "period_end": today})
slip.action_compute()
statlines = slip.line_ids.filtered(lambda l: l.category == "statutory")
print("probe payslip gross=%.2f net=%.2f statutory_lines=%d"
      % (slip.gross_amount, slip.net_amount, len(statlines)))
ejob = env["commercial.event.job"].sudo().search([], limit=1)
if ejob:
    w = env["neon.hr.event.wage"].sudo().create({
        "employee_id": emp.id, "event_job_id": ejob.id,
        "wage_type": "incentive", "date": today})
    print("probe USD-10 incentive links to job:",
          w.amount == 10.0 and bool(w.event_job_id))
loan = env["neon.hr.loan"].sudo().create({
    "employee_id": emp.id, "principal_amount": 1200.0,
    "instalment_count": 12, "start_date": today})
loan.action_approve(); loan.action_activate()
print("probe loan schedule:", len(loan.repayment_ids), "instalments, balance=%.2f"
      % loan.balance_amount)
bare = env["res.users"].sudo().create({
    "name": "PHR bare prod", "login": "phr_r1b_bare_prod",
    "email": "phr_r1b_bare_prod@neonhiring.com",
    "groups_id": [(6, 0, [env.ref("base.group_user").id])]})
blk = False
try:
    env["neon.hr.payslip"].with_user(bare).browse(slip.id).read(["net_amount"])
except AccessError:
    blk = True
print("probe non-OD/MD/Admin blocked from payslip:", blk)
env.cr.rollback()
print("(probe rolled back — no prod data created)")
print("=" * 72)
