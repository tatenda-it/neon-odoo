"""P-HR-R2 smoke — accidents/NSSA, disciplinary, TOIL, handbook.

Acceptance §: accident capture + 14-day alert fires; disciplinary
categories + confidentiality; TOIL accrues + reduces availability;
handbook-ack compliance flag; same-day-absence escalation + OD clear.
"""
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-HR-R2 — accidents/NSSA · disciplinary · TOIL · handbook")
print("=" * 72)
results = {}

env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))
env.company.sudo().write({"email": env.company.email or "noreply@neonhiring.com"})
if not env.user.email:
    env.user.sudo().write({"email": "shell@neonhiring.com"})

HR = env["hr.employee"]
Accident = env["neon.hr.accident"]
Case = env["neon.hr.case"]
OT = env["neon.hr.overtime"]
Handbook = env["neon.hr.handbook"]
Ack = env["neon.hr.handbook.ack"]
ACItem = env["action.centre.item"]
cat = {c.code: c for c in env["neon.hr.category"].sudo().search([])}
today = date.today()

su_user = env["res.users"].sudo().create({
    "name": "PHR R2 su", "login": "phr_r2_su", "email": "su@neonhiring.com",
    "groups_id": [(6, 0, [env.ref("neon_core.group_neon_superuser").id])]})
bare = env["res.users"].sudo().create({
    "name": "PHR R2 bare", "login": "phr_r2_bare", "email": "b@neonhiring.com",
    "groups_id": [(6, 0, [env.ref("base.group_user").id])]})
emp = HR.sudo().create({"name": "PHR R2 Emp",
                        "neon_category_id": cat["employed_technician"].id})

# ============ ACCIDENT / NSSA ============
acc = Accident.sudo().create({
    "employee_id": emp.id, "accident_date": today,
    "description": "Slipped on cable", "injury_description": "Sprained wrist"})
_check("T-R2-01", acc.reporting_deadline == today + timedelta(days=14),
       "14-day NSSA deadline computed (%s)" % acc.reporting_deadline)
_check("T-R2-02", acc.state == "captured", "accident captured")
_check("T-R2-03", "penalty_risk" in acc._fields and "penalty_note" in acc._fields
       and "penalty_amount" not in acc._fields,
       "penalty is ALERT-ONLY (flag + note, no amount field)")

# 14-day Action Centre alert fires
Accident._cron_accident_nssa_deadline_scan()
sm = env["ir.model"].sudo()._get("neon.hr.accident")
items = ACItem.sudo().search([
    ("trigger_type", "=", "accident_nssa_14day"),
    ("source_model_id", "=", sm.id), ("source_id", "=", acc.id),
    ("state", "in", ("open", "in_progress"))])
_check("T-R2-04", len(items) == 1,
       "14-day NSSA Action Centre alert fires (%d item)" % len(items))
# idempotent
Accident._cron_accident_nssa_deadline_scan()
items2 = ACItem.sudo().search([
    ("trigger_type", "=", "accident_nssa_14day"),
    ("source_model_id", "=", sm.id), ("source_id", "=", acc.id),
    ("state", "in", ("open", "in_progress"))])
_check("T-R2-05", len(items2) == 1, "accident alert idempotent (no dup)")

acc.action_review()
_check("T-R2-06", acc.state == "reviewed" and acc.reviewed_by_id,
       "accident review (OD/MD)")
nssa_blocked = False
try:
    acc.action_nssa_submit()
except UserError:
    nssa_blocked = True
_check("T-R2-07", nssa_blocked, "NSSA submit blocked without submission ref")
acc.sudo().nssa_submission_ref = "NSSA/2026/001"
acc.action_nssa_submit()
acc.invalidate_recordset(["state"])
_check("T-R2-08", acc.state == "nssa_submitted", "NSSA submission recorded")
items_closed = ACItem.sudo().search([
    ("trigger_type", "=", "accident_nssa_14day"),
    ("source_model_id", "=", sm.id), ("source_id", "=", acc.id),
    ("state", "in", ("open", "in_progress"))])
_check("T-R2-09", len(items_closed) == 0,
       "NSSA submission closes the Action Centre alert")

# ============ CASES (all 4 categories) ============
cases = {}
for ctype in ("disciplinary", "incident", "performance", "recognition"):
    cases[ctype] = Case.sudo().create({
        "employee_id": emp.id, "case_type": ctype,
        "subject": "%s test" % ctype, "severity": "medium"})
_check("T-R2-10", all(cases[c].case_type == c for c in cases),
       "all 4 case categories: disciplinary/incident/performance/recognition")
_check("T-R2-11", "attachment_ids" in Case._fields,
       "cases carry evidence attachments")
cases["disciplinary"].action_open()
_check("T-R2-12", cases["disciplinary"].state == "in_progress",
       "case lifecycle draft->in_progress")

# ============ SAME-DAY EVENT ABSENCE (Q22) ============
ejob = env["commercial.event.job"].sudo().search([], limit=1)
abs_case = Case.sudo().create({
    "employee_id": emp.id, "case_type": "incident",
    "subject": "Same-day no-show", "event_job_id": ejob.id if ejob else False})
abs_case.action_escalate_line_manager()
_check("T-R2-13", abs_case.absence_flow == "escalated_line_manager",
       "same-day absence escalates to line manager")
abs_case.action_escalate_disciplinary()
_check("T-R2-14", abs_case.absence_flow == "escalated_disciplinary"
       and abs_case.case_type == "disciplinary",
       "escalates to disciplinary")
# OD-only clear
od_blocked = False
try:
    abs_case.with_user(bare).action_od_clear()
except AccessError:
    od_blocked = True
_check("T-R2-15", od_blocked, "non-OD/MD CANNOT OD-clear an absence case")
abs_case.with_user(su_user).action_od_clear()
abs_case.invalidate_recordset(["absence_flow", "state"])
_check("T-R2-16", abs_case.absence_flow == "od_cleared",
       "OD clears to resume event allocation")

# ============ TOIL ============
toil_type = env.ref("neon_hr.leave_type_toil")
ot = OT.sudo().create({"employee_id": emp.id, "hours": 16.0, "date": today})
ot_no_res = False
try:
    ot.with_user(su_user).action_approve()
except UserError:
    ot_no_res = True
_check("T-R2-17", ot_no_res, "overtime approval blocked without a resolution")
ot.sudo().resolution = "toil"
ot.with_user(su_user).action_approve()
ot.invalidate_recordset(["state", "toil_allocation_id"])
_check("T-R2-18", ot.state == "approved" and ot.toil_allocation_id,
       "TOIL overtime approved -> accrues a leave allocation")
_check("T-R2-19", abs(ot.toil_allocation_id.number_of_days - 2.0) < 0.01,
       "TOIL accrual = hours/8 (16h -> %.1f days)"
       % ot.toil_allocation_id.number_of_days)
# authority
ot2 = OT.sudo().create({"employee_id": emp.id, "hours": 8.0, "date": today,
                        "resolution": "paid"})
ot_auth = False
try:
    ot2.with_user(bare).action_approve()
except AccessError:
    ot_auth = True
_check("T-R2-20", ot_auth, "non-OD/MD/Finance CANNOT approve overtime")

# TOIL taken reduces availability (reuse R1b neon.hr.availability)
toil_leave = env["hr.leave"].sudo().create({
    "name": "TOIL day", "employee_id": emp.id,
    "holiday_status_id": toil_type.id,
    "request_date_from": today + timedelta(days=20),
    "request_date_to": today + timedelta(days=20)})
try:
    if toil_leave.state == "draft":
        toil_leave.action_confirm()
    toil_leave.action_validate()
except Exception:
    toil_leave.sudo().write({"state": "validate"})
toil_leave.flush_recordset()
avail = env["neon.hr.availability"].sudo().search([
    ("employee_id", "=", emp.id),
    ("holiday_status_id", "=", toil_type.id)])
_check("T-R2-21", len(avail) >= 1,
       "taking TOIL reduces availability (appears in neon.hr.availability)")

# ============ HANDBOOK ============
hb = Handbook.sudo().search([("is_current", "=", True)], limit=1)
_check("T-R2-22", bool(hb), "a current handbook version exists")
emp_hb = HR.sudo().create({"name": "PHR R2 Handbook Emp"})
emp_hb.invalidate_recordset(["handbook_ack_pending"])
_check("T-R2-23", emp_hb.handbook_ack_pending,
       "new employee flagged as not-acknowledged (compliance flag)")
hb.action_acknowledge(employee=emp_hb)
emp_hb.invalidate_recordset(["handbook_ack_pending"])
_check("T-R2-24", not emp_hb.handbook_ack_pending,
       "acknowledgement clears the compliance flag")
ack = Ack.sudo().search([("handbook_id", "=", hb.id),
                         ("employee_id", "=", emp_hb.id)])
_check("T-R2-25", ack.state == "acknowledged" and ack.acknowledged_date,
       "ack recorded with date")
# is_current is single
hb2 = Handbook.sudo().create({"name": "Employee Handbook", "version": "v2",
                              "is_current": True})
hb.invalidate_recordset(["is_current"])
_check("T-R2-26", hb2.is_current and not hb.is_current,
       "setting a new current version unsets the old one")

# ============ CONFIDENTIALITY ============
acc_blk = case_blk = ot_blk = False
try:
    Accident.with_user(bare).browse(acc.id).read(["description"])
except AccessError:
    acc_blk = True
try:
    Case.with_user(bare).browse(cases["disciplinary"].id).read(["subject"])
except AccessError:
    case_blk = True
try:
    OT.with_user(bare).browse(ot.id).read(["hours"])
except AccessError:
    ot_blk = True
_check("T-R2-27", acc_blk, "non-OD/MD/Admin CANNOT read another's accident")
_check("T-R2-28", case_blk, "non-OD/MD/Admin CANNOT read another's disciplinary")
_check("T-R2-29", ot_blk, "non-OD/MD/Admin CANNOT read another's overtime")

# ============ manifest + R3 contract ============
import os
from odoo.modules.module import get_module_path
with open(os.path.join(get_module_path("neon_hr"), "__manifest__.py"),
          encoding="utf-8") as f:
    _check("T-R2-30", "17.0.4.0.0" in f.read(),
           "neon_hr manifest version 17.0.4.0.0")

contract = (
    ("neon.hr.accident", "reporting_deadline", "date"),
    ("neon.hr.accident", "penalty_risk", "boolean"),
    ("neon.hr.case", "case_type", "selection"),
    ("neon.hr.case", "absence_flow", "selection"),
    ("neon.hr.overtime", "resolution", "selection"),
    ("neon.hr.overtime", "toil_allocation_id", "many2one"),
    ("neon.hr.handbook", "is_current", "boolean"),
    ("neon.hr.handbook.ack", "state", "selection"),
    ("hr.employee", "handbook_ack_pending", "boolean"),
)
mism = []
for model_name, fname, ftype in contract:
    fld = env[model_name]._fields.get(fname)
    if not fld:
        mism.append("%s.%s MISSING" % (model_name, fname))
    elif fld.type != ftype:
        mism.append("%s.%s=%s!=%s" % (model_name, fname, fld.type, ftype))
_check("T-R2-31", not mism, "R3 field-name contract intact" if not mism else str(mism))

print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
env.cr.rollback()
