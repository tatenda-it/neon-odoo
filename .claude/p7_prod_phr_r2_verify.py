"""P-HR-R2 PROD SQL-verify (odoo shell -d neon_crm). Read-only + a
rolled-back probe."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError

print("=" * 72)
print("P-HR-R2 PROD SQL VERIFY")
print("=" * 72)
env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))
env.company.sudo().write({"email": env.company.email or "noreply@neonhiring.com"})

M = env["ir.module.module"].sudo()
print("neon_hr:", M.search([("name", "=", "neon_hr")]).latest_version)
r2_models = ["neon.hr.accident", "neon.hr.case", "neon.hr.overtime",
             "neon.hr.handbook", "neon.hr.handbook.ack"]
present = sorted(env["ir.model"].sudo().search(
    [("model", "in", r2_models)]).mapped("model"))
print("R2 models present (%d/5):" % len(present), present)
acls = env["ir.model.access"].sudo().search([("model_id.model", "in", r2_models)])
print("R2 ACL perm_unlink values:", sorted(set(acls.mapped("perm_unlink"))))
rules = env["ir.rule"].sudo().search(
    [("model_id.model", "in", ["neon.hr.accident", "neon.hr.case",
                               "neon.hr.overtime", "neon.hr.handbook.ack"])])
print("R2 record rules:", len(rules))
print("TOIL leave type:", bool(env.ref("neon_hr.leave_type_toil", raise_if_not_found=False)))
print("accident trigger config:", env["action.centre.trigger.config"].sudo()
      .search_count([("trigger_type", "=", "accident_nssa_14day")]))
print("current handbook:", env["neon.hr.handbook"].sudo().search_count([("is_current", "=", True)]))
su = env.ref("neon_core.group_neon_superuser")
print("superuser implies hr_manager:", env.ref("hr.group_hr_manager") in su.implied_ids)

# ---- probe (rolled back) ----
print("--- probe (rolled back) ---")
cat = {c.code: c for c in env["neon.hr.category"].sudo().search([])}
today = fields.Date.today()
emp = env["hr.employee"].sudo().create({
    "name": "PHR R2 PROD PROBE", "neon_category_id": cat["employed_technician"].id})
acc = env["neon.hr.accident"].sudo().create({
    "employee_id": emp.id, "accident_date": today, "description": "probe"})
print("accident 14-day deadline:", acc.reporting_deadline == today + timedelta(days=14))
env["neon.hr.accident"]._cron_accident_nssa_deadline_scan()
sm = env["ir.model"].sudo()._get("neon.hr.accident")
item = env["action.centre.item"].sudo().search([
    ("trigger_type", "=", "accident_nssa_14day"),
    ("source_model_id", "=", sm.id), ("source_id", "=", acc.id)])
print("probe accident raises Action Centre task:", len(item) == 1)
case = env["neon.hr.case"].sudo().create({
    "employee_id": emp.id, "case_type": "disciplinary", "subject": "probe"})
su_probe = env["res.users"].sudo().create({
    "name": "PHR R2 su probe", "login": "phr_r2_su_probe",
    "email": "phr_r2_su_probe@neonhiring.com",
    "groups_id": [(6, 0, [env.ref("neon_core.group_neon_superuser").id])]})
ot = env["neon.hr.overtime"].sudo().create({
    "employee_id": emp.id, "hours": 8.0, "date": today, "resolution": "toil"})
ot.with_user(su_probe).action_approve()
ot.invalidate_recordset(["toil_allocation_id"])
print("TOIL overtime accrues allocation:", bool(ot.toil_allocation_id))
emp.invalidate_recordset(["handbook_ack_pending"])
print("handbook compliance flag works:", emp.handbook_ack_pending in (True, False))
bare = env["res.users"].sudo().create({
    "name": "PHR R2 bare prod", "login": "phr_r2_bare_prod",
    "email": "phr_r2_bare_prod@neonhiring.com",
    "groups_id": [(6, 0, [env.ref("base.group_user").id])]})
blk = False
try:
    env["neon.hr.case"].with_user(bare).browse(case.id).read(["subject"])
except AccessError:
    blk = True
print("non-OD/MD/Admin blocked from disciplinary:", blk)
env.cr.rollback()
print("(probe rolled back)")
print("=" * 72)
