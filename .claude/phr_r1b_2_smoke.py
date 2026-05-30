"""P-HR-R1b-2 smoke — payroll + event wages + commission + loans.

Covers acceptance §3 (R1b-2 portion):
- statutory deductions present (rates flagged); freelance per-event vs salaried monthly
- USD 10 incentive separate + Event/Job-linked; freelance 50/30/20 grades
- commission proposed-not-auto-paid + needs approval+evidence
- loan instalments deduct + final-pay block
- confidentiality holds for non-OD/MD/Admin
"""
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-HR-R1b-2 — payroll + wages + commission + loans")
print("=" * 72)
results = {}

env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))
env.company.sudo().write({"email": env.company.email or "noreply@neonhiring.com"})
if not env.user.email:
    env.user.sudo().write({"email": "shell@neonhiring.com"})

HR = env["hr.employee"]
Contract = env["hr.contract"]
Slip = env["neon.hr.payslip"]
Stat = env["neon.hr.statutory.rule"]
Wage = env["neon.hr.event.wage"]
Grade = env["neon.hr.wage.grade"]
Comm = env["neon.hr.commission"]
Loan = env["neon.hr.loan"]
cat = {c.code: c for c in env["neon.hr.category"].sudo().search([])}
today = date.today()
p_start = today.replace(day=1)
p_end = (p_start + timedelta(days=31)).replace(day=1) - timedelta(days=1)

su_user = env["res.users"].sudo().create({
    "name": "PHR su", "login": "phr_r1b2_su", "email": "su@neonhiring.com",
    "groups_id": [(6, 0, [env.ref("neon_core.group_neon_superuser").id])]})
bare = env["res.users"].sudo().create({
    "name": "PHR bare", "login": "phr_r1b2_bare", "email": "bare@neonhiring.com",
    "groups_id": [(6, 0, [env.ref("base.group_user").id])]})


# ---- statutory rules ----
rules = Stat.sudo().search([])
_check("T-R1b2-01", len(rules) >= 4
       and all(r.needs_finance_confirmation for r in rules),
       "%d statutory rules, ALL flagged for finance confirmation" % len(rules))
paye = Stat.sudo().search([("code", "=", "paye")], limit=1)
_check("T-R1b2-02", abs(paye._compute_amount(1000.0) - 200.0) < 0.01,
       "PAYE _compute_amount(1000) = %.2f (20%% placeholder)"
       % paye._compute_amount(1000.0))

# ---- wage grades ----
amts = sorted(Grade.sudo().search([]).mapped("amount"), reverse=True)
_check("T-R1b2-03", amts[:3] == [50.0, 30.0, 20.0],
       "freelance grades = 50/30/20: %s" % amts[:3])
_check("T-R1b2-04",
       env["ir.config_parameter"].sudo().get_param("neon_hr.event_incentive_usd") == "10",
       "USD 10 event incentive configured")


# ---- salaried payslip: gross -> statutory deductions -> net ----
emp_s = HR.sudo().create({
    "name": "PHR Salaried", "neon_category_id": cat["employed_technician"].id})
ctr_s = Contract.sudo().create({
    "name": "ctr salaried", "employee_id": emp_s.id, "wage": 1000.0,
    "neon_contract_type": "employed_technician",
    "date_start": today - timedelta(days=60), "state": "open"})
slip = Slip.sudo().create({
    "employee_id": emp_s.id, "contract_id": ctr_s.id,
    "period_start": p_start, "period_end": p_end})
slip.action_compute()
slip.invalidate_recordset(["gross_amount", "total_deductions", "net_amount", "state"])
stat_lines = slip.line_ids.filtered(lambda l: l.category == "statutory")
_check("T-R1b2-05", slip.state == "computed" and slip.gross_amount == 1000.0,
       "salaried payslip gross = monthly wage (%.2f)" % slip.gross_amount)
_check("T-R1b2-06", len(stat_lines) >= 4,
       "statutory deduction lines present (%d)" % len(stat_lines))
_check("T-R1b2-07",
       abs(slip.net_amount - (slip.gross_amount - slip.total_deductions)) < 0.01
       and slip.total_deductions > 0,
       "net = gross - deductions (%.2f - %.2f = %.2f)"
       % (slip.gross_amount, slip.total_deductions, slip.net_amount))
slip.action_confirm()
_check("T-R1b2-08", slip.state == "confirmed", "payslip draft->computed->confirmed")

# ---- event wages: incentive (USD10, separate, job-linked) ----
ejob = env["commercial.event.job"].sudo().search([], limit=1)
if not ejob:
    partner = env["res.partner"].sudo().search([], limit=1)
    mjob = env["commercial.job"].sudo().create({
        "name": "PHR WAGE JOB", "partner_id": partner.id,
        "state": "active", "event_date": today})
    ejob = env["commercial.event.job"].sudo().create({
        "name": "PHR WAGE EVENT", "commercial_job_id": mjob.id,
        "partner_id": partner.id})
inc = Wage.sudo().create({
    "employee_id": emp_s.id, "event_job_id": ejob.id,
    "wage_type": "incentive", "date": today})
_check("T-R1b2-09", inc.amount == 10.0 and inc.event_job_id == ejob,
       "USD 10 incentive auto-set + Event/Job-linked (%.2f)" % inc.amount)
_check("T-R1b2-10",
       inc.state == "draft" and slip.gross_amount == 1000.0,
       "incentive starts draft + is SEPARATE from salary (gross excludes the USD 10)")

# freelance grade wage
grade_a = Grade.sudo().search([("code", "=", "a")], limit=1)
fw = Wage.sudo().create({
    "employee_id": emp_s.id, "event_job_id": ejob.id,
    "wage_type": "freelance_grade", "grade_id": grade_a.id, "date": today})
_check("T-R1b2-11", fw.amount == 50.0,
       "freelance grade A wage = USD 50 (%.2f)" % fw.amount)

# authority: bare user cannot approve; OD/MD can
inc.action_review()
auth_blocked = False
try:
    inc.with_user(bare).action_approve()
except AccessError:
    auth_blocked = True
_check("T-R1b2-12", auth_blocked,
       "non-OD/MD/Finance user CANNOT approve an event wage")
inc.with_user(su_user).action_approve()
_check("T-R1b2-13", inc.state == "approved", "OD/MD approves event wage")

# ---- freelance per-event payslip ----
emp_f = HR.sudo().create({
    "name": "PHR Freelance", "neon_category_id": cat["freelance_technician"].id})
ctr_f = Contract.sudo().create({
    "name": "ctr freelance", "employee_id": emp_f.id, "wage": 0.0,
    "neon_contract_type": "freelance_technician",
    "date_start": today - timedelta(days=60), "state": "open"})
for amt_grade in ("a", "b"):
    g = Grade.sudo().search([("code", "=", amt_grade)], limit=1)
    w = Wage.sudo().create({
        "employee_id": emp_f.id, "event_job_id": ejob.id,
        "wage_type": "freelance_grade", "grade_id": g.id, "date": today})
    w.action_review()
    w.with_user(su_user).action_approve()
slip_f = Slip.sudo().create({
    "employee_id": emp_f.id, "contract_id": ctr_f.id,
    "period_start": p_start, "period_end": p_end})
slip_f.action_compute()
slip_f.invalidate_recordset(["gross_amount"])
_check("T-R1b2-14", slip_f.gross_amount == 80.0,
       "freelance payslip gross = sum approved event wages (50+30=%.2f)"
       % slip_f.gross_amount)

# ---- commission: proposed 10%, never auto-paid, needs evidence ----
comm = Comm.sudo().create({
    "employee_id": emp_s.id, "base_amount": 1000.0})
_check("T-R1b2-15", comm.state == "proposed" and comm.proposed_amount == 100.0,
       "commission proposes 10%% (%.2f), starts 'proposed' (never auto-paid)"
       % comm.proposed_amount)
no_evidence_blocked = False
try:
    comm.with_user(su_user).action_approve()
except UserError:
    no_evidence_blocked = True
_check("T-R1b2-16", no_evidence_blocked,
       "commission approval BLOCKED without evidence")
comm.sudo().evidence = "Closed the Acme launch; signed SOW attached."
comm.with_user(su_user).action_approve()
_check("T-R1b2-17",
       comm.state == "approved" and comm.approved_amount == 100.0,
       "commission approved WITH evidence + authority")
comm_auth_blocked = False
try:
    comm2 = Comm.sudo().create({"employee_id": emp_s.id, "base_amount": 500.0,
                                "evidence": "x"})
    comm2.with_user(bare).action_approve()
except AccessError:
    comm_auth_blocked = True
_check("T-R1b2-18", comm_auth_blocked,
       "non-OD/MD/Finance user CANNOT approve commission")

# ---- loan: schedule + balance + final-pay block ----
loan = Loan.sudo().create({
    "employee_id": emp_s.id, "principal_amount": 1200.0,
    "instalment_count": 12, "start_date": p_start})
loan.action_approve()
loan.action_activate()
loan.invalidate_recordset(["balance_amount", "instalment_amount"])
_check("T-R1b2-19",
       len(loan.repayment_ids) == 12
       and abs(sum(loan.repayment_ids.mapped("amount")) - 1200.0) < 0.01,
       "loan schedule = 12 instalments summing to principal")
_check("T-R1b2-20", loan.instalment_amount == 100.0 and loan.balance_amount == 1200.0,
       "instalment = 100, balance = principal until deducted")

# payslip picks up the due instalment as a deduction
slip2 = Slip.sudo().create({
    "employee_id": emp_s.id, "contract_id": ctr_s.id,
    "period_start": p_start, "period_end": p_end})
slip2.action_compute()
loan_lines = slip2.line_ids.filtered(lambda l: l.category == "loan")
_check("T-R1b2-21", len(loan_lines) == 1 and loan_lines.amount == 100.0,
       "due loan instalment flows into the payslip as a deduction")

# final-pay block: confirmed final pay with outstanding balance is refused
slip2.action_confirm()
slip2.sudo().is_final_pay = True
final_blocked = False
try:
    slip2.action_mark_paid()
except UserError:
    final_blocked = True
_check("T-R1b2-22", final_blocked,
       "FINAL pay blocked while a loan balance is outstanding (Q19)")

# normal (non-final) payslip pays + marks the instalment deducted
slip2.sudo().is_final_pay = False
slip2.action_mark_paid()
loan.invalidate_recordset(["balance_amount", "total_repaid"])
_check("T-R1b2-23",
       slip2.state == "paid" and loan.balance_amount == 1100.0,
       "paying deducts the instalment: balance 1200->%.2f" % loan.balance_amount)

# ---- confidentiality ----
pay_blocked = doc_blocked = False
try:
    Slip.with_user(bare).browse(slip.id).read(["net_amount"])
except AccessError:
    pay_blocked = True
try:
    Loan.with_user(bare).browse(loan.id).read(["principal_amount"])
except AccessError:
    doc_blocked = True
_check("T-R1b2-24", pay_blocked, "non-OD/MD/Admin CANNOT read another's payslip")
_check("T-R1b2-25", doc_blocked, "non-OD/MD/Admin CANNOT read another's loan")

# ---- manifest ----
import os
from odoo.modules.module import get_module_path
with open(os.path.join(get_module_path("neon_hr"), "__manifest__.py"),
          encoding="utf-8") as f:
    _check("T-R1b2-26", "17.0.3.0.0" in f.read(),
           "neon_hr manifest version 17.0.3.0.0")

print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
env.cr.rollback()
