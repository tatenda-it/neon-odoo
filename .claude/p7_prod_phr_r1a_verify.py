"""P-HR-R1a PROD SQL-verify (runs in odoo shell -d neon_crm on prod).
Read-only except a probe that is rolled back at the end."""
from odoo import fields
from odoo.exceptions import AccessError

print("=" * 72)
print("P-HR-R1a PROD SQL VERIFY")
print("=" * 72)

M = env["ir.module.module"].sudo()
nh = M.search([("name", "=", "neon_hr")])
print("neon_hr:", nh.latest_version, "/", nh.state)
print("hr_skills_slides:", M.search([("name", "=", "hr_skills_slides")]).state)
print("hr / hr_contract:",
      M.search([("name", "=", "hr")]).state, "/",
      M.search([("name", "=", "hr_contract")]).state)

models = env["ir.model"].sudo().search(
    [("model", "like", "neon.hr.%")]).mapped("model")
print("neon.hr.* models:", sorted(models))

acls = env["ir.model.access"].sudo().search(
    [("model_id.model", "like", "neon.hr.%")])
print("neon.hr.* ACL rows:", len(acls),
      "| perm_unlink values:", sorted(set(acls.mapped("perm_unlink"))))

print("categories:", env["neon.hr.category"].sudo().search_count([]))
print("doc types:", env["neon.hr.document.type"].sudo().search_count([]))
print("course_url on hr.resume.line:",
      "course_url" in env["hr.resume.line"]._fields)

# ---- HR access holders ----
HRm = env.ref("hr.group_hr_manager")
HRu = env.ref("hr.group_hr_user")
su = env.ref("neon_core.group_neon_superuser")
ha = env.ref("neon_hr.group_neon_hr_admin")
root = env.ref("base.user_root")
admin = env.ref("base.user_admin", raise_if_not_found=False)
su_ids = set(su.users.ids)
ha_ids = set(ha.users.ids)


def classify(u):
    if u.id in su_ids:
        return "OD/MD (superuser)"
    if u.id in ha_ids:
        return "HR-Admin"
    if u.id == root.id:
        return "root"
    if admin and u.id == admin.id:
        return "admin"
    return "*** STRAY — should have been revoked ***"


mgr = env["res.users"].sudo().search(
    [("groups_id", "in", HRm.id), ("active", "=", True)])
print("\n--- hr_manager holders (%d) ---" % len(mgr))
strays = []
for u in mgr.sorted("login"):
    c = classify(u)
    print("  %-24s %s" % (u.login, c))
    if "STRAY" in c:
        strays.append(u.login)

usr = env["res.users"].sudo().search(
    [("groups_id", "in", HRu.id), ("active", "=", True)])
usr_strays = [u.login for u in usr if "STRAY" in classify(u)]
print("\nhr_user holders: %d | strays: %s" % (len(usr), usr_strays or "NONE"))
print("hr_manager strays:", strays or "NONE")

should = su_ids | ha_ids
lacking = env["res.users"].sudo().browse(list(should)).filtered(
    lambda u: u.active and HRm not in u.groups_id)
print("OD/MD or HR-Admin LACKING hr_manager (locked out):",
      lacking.mapped("login") or "NONE")
print("OD/MD (superuser) active members:",
      su.users.filtered("active").mapped("login"))
print("HR-Admin active members:",
      ha.users.filtered("active").mapped("login") or "NONE (group empty)")

# ---- probe (rolled back) ----
print("\n--- probe: incomplete docs + confidentiality (rolled back) ---")
emp = env["hr.employee"].sudo().create({"name": "PHR PROD VERIFY PROBE"})
emp.write({"neon_category_id":
           env.ref("neon_hr.category_employed_technician").id})
emp.invalidate_recordset(["is_compliant", "document_ids"])
print("probe docs auto-generated:", len(emp.document_ids),
      "| is_compliant:", emp.is_compliant)

bare = env["res.users"].sudo().create({
    "name": "PHR PROD BARE", "login": "phr_prod_bare_probe",
    "email": "phr_prod_bare_probe@neonhiring.com",
    "groups_id": [(6, 0, [env.ref("base.group_user").id])]})
ctr = env["hr.contract"].sudo().create({
    "name": "probe ctr", "employee_id": emp.id, "wage": 9999.0,
    "date_start": fields.Date.today(), "state": "open"})
doc = emp.document_ids[0]
salary_blocked = doc_blocked = False
try:
    env["hr.contract"].with_user(bare).browse(ctr.id).read(["wage"])
except AccessError:
    salary_blocked = True
try:
    env["neon.hr.document"].with_user(bare).browse(doc.id).read(["state"])
except AccessError:
    doc_blocked = True
print("non-admin blocked from salary(wage):", salary_blocked,
      "| from personal doc:", doc_blocked)

f = env["hr.employee"]._fields.get("assignment_override")
print("Q6 assignment_override tracking (auditable via chatter):",
      getattr(f, "tracking", False))

env.cr.rollback()
print("(probe rolled back — no prod data created)")
print("=" * 72)
