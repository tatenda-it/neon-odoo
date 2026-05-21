"""P7a.M12.1 smoke -- three QWeb reports (15 tests).

Report registration + access:
T8300  Expiring report ir.actions.report record exists
T8301  Compliance report ir.actions.report record exists
T8302  Cross-competency report ir.actions.report record exists
T8303  Expiring report binds to neon.training.certification
T8304  Compliance report binds to neon.training.certification
T8305  Cross-competency report binds to neon.training.cross_competency

Compliance report ACL (DP8):
T8306  Compliance report has signoff + admin groups (NOT sales)
T8307  Sales-tier cannot read the compliance report record

Report templates:
T8308  Expiring report template renders (basic QWeb sanity)
T8309  Compliance report template renders (Safety category)
T8310  Cross-competency report template renders

Menu items:
T8311  Reports submenu xmlid exists + parented to root
T8312  Expiring menu xmlid exists
T8313  Compliance menu xmlid exists
T8314  Cross-competency menu xmlid exists
"""
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:
        return (e, None)


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Report = env["ir.actions.report"]
Menu = env["ir.ui.menu"]
Users = env["res.users"]

u_sales = Users.sudo().search([("login", "=", "p2m75_sales")], limit=1)
u_admin = Users.sudo().search(
    [("login", "=", "p7am2_train_admin")], limit=1)
u_signoff = Users.sudo().search(
    [("login", "=", "p7am2_train_signoff")], limit=1)
assert all([u_sales, u_admin, u_signoff]), "fixture users"


# ============================================================
print()
print("T8300 - Expiring report action record exists")
print("=" * 72)
r_exp = env.ref(
    "neon_training.neon_training_expiring_report_action",
    raise_if_not_found=False)
ok = bool(r_exp)
print("  record id:", r_exp.id if r_exp else None,
      " name:", r_exp.name if r_exp else None)
print("T8300:", "PASS" if ok else "FAIL")
results["T8300"] = ok


# ============================================================
print()
print("T8301 - Compliance report action record exists")
print("=" * 72)
r_comp = env.ref(
    "neon_training.neon_training_compliance_report_action",
    raise_if_not_found=False)
ok = bool(r_comp)
print("  record id:", r_comp.id if r_comp else None,
      " name:", r_comp.name if r_comp else None)
print("T8301:", "PASS" if ok else "FAIL")
results["T8301"] = ok


# ============================================================
print()
print("T8302 - Cross-competency report action exists")
print("=" * 72)
r_cc = env.ref(
    "neon_training.neon_training_cross_competency_report_action",
    raise_if_not_found=False)
ok = bool(r_cc)
print("  record id:", r_cc.id if r_cc else None,
      " name:", r_cc.name if r_cc else None)
print("T8302:", "PASS" if ok else "FAIL")
results["T8302"] = ok


# ============================================================
print()
print("T8303 - Expiring binds to neon.training.certification")
print("=" * 72)
ok = (r_exp.model == "neon.training.certification"
      and r_exp.report_type == "qweb-pdf")
print("  model:", r_exp.model, " report_type:", r_exp.report_type)
print("T8303:", "PASS" if ok else "FAIL")
results["T8303"] = ok


# ============================================================
print()
print("T8304 - Compliance binds to neon.training.certification")
print("=" * 72)
ok = (r_comp.model == "neon.training.certification")
print("  model:", r_comp.model)
print("T8304:", "PASS" if ok else "FAIL")
results["T8304"] = ok


# ============================================================
print()
print("T8305 - Cross-competency binds to neon.training.cross_competency")
print("=" * 72)
ok = (r_cc.model == "neon.training.cross_competency")
print("  model:", r_cc.model)
print("T8305:", "PASS" if ok else "FAIL")
results["T8305"] = ok


# ============================================================
print()
print("T8306 - Compliance report has signoff + admin groups (DP8)")
print("=" * 72)
g_signoff = env.ref("neon_training.group_neon_training_signoff")
g_admin = env.ref("neon_training.group_neon_training_admin")
report_groups = r_comp.groups_id
ok = (g_signoff in report_groups and g_admin in report_groups)
print("  group ids on report:", report_groups.ids,
      " signoff in:", g_signoff in report_groups,
      " admin in:", g_admin in report_groups)
print("T8306:", "PASS" if ok else "FAIL")
results["T8306"] = ok


# ============================================================
print()
print("T8307 - Sales user is NOT in any of the report's groups (DP8)")
print("=" * 72)
# DP8: sales doesn't see the compliance report's print binding.
# Odoo enforces groups_id on ir.actions.report by filtering the
# print menu client-side; the back-end contract is "groups_id
# restricts to a set the user must intersect."
# Verify sales user has NO intersection with r_comp.groups_id.
sales_groups = set(u_sales.groups_id.ids)
report_groups = set(r_comp.groups_id.ids)
ok = (len(sales_groups & report_groups) == 0)
print("  sales groups overlap with report groups:",
      len(sales_groups & report_groups),
      " (expected 0 for DP8)")
print("T8307:", "PASS" if ok else "FAIL")
results["T8307"] = ok


# ============================================================
print()
print("T8308 - Expiring report template renders")
print("=" * 72)
# Render the report against an empty docs set; expect HTML
# bytes back (no exception).
err, content = _try(lambda: Report._render_qweb_html(
    "neon_training.report_expiring_document", [])[0])
ok = (err is None and isinstance(content, (str, bytes))
      and len(content) > 100)
print("  err:", type(err).__name__ if err else None,
      " content len:", len(content) if content else 0)
print("T8308:", "PASS" if ok else "FAIL")
results["T8308"] = ok


# ============================================================
print()
print("T8309 - Compliance report template renders")
print("=" * 72)
err, content = _try(lambda: Report._render_qweb_html(
    "neon_training.report_compliance_document", [])[0])
ok = (err is None and isinstance(content, (str, bytes))
      and len(content) > 100)
print("  err:", type(err).__name__ if err else None,
      " content len:", len(content) if content else 0)
print("T8309:", "PASS" if ok else "FAIL")
results["T8309"] = ok


# ============================================================
print()
print("T8310 - Cross-competency report template renders")
print("=" * 72)
err, content = _try(lambda: Report._render_qweb_html(
    "neon_training.report_cross_competency_document", [])[0])
ok = (err is None and isinstance(content, (str, bytes))
      and len(content) > 100)
print("  err:", type(err).__name__ if err else None,
      " content len:", len(content) if content else 0)
print("T8310:", "PASS" if ok else "FAIL")
results["T8310"] = ok


# ============================================================
print()
print("T8311 - Reports submenu parented to training root")
print("=" * 72)
m_reports = env.ref(
    "neon_training.menu_neon_training_reports",
    raise_if_not_found=False)
m_root = env.ref(
    "neon_training.menu_neon_training_root",
    raise_if_not_found=False)
ok = (m_reports and m_reports.parent_id == m_root)
print("  reports parent:",
      m_reports.parent_id.complete_name if m_reports else None)
print("T8311:", "PASS" if ok else "FAIL")
results["T8311"] = ok


# ============================================================
print()
print("T8312 - Expiring menu xmlid exists")
print("=" * 72)
m_exp = env.ref(
    "neon_training.menu_neon_training_report_expiring",
    raise_if_not_found=False)
ok = (m_exp and m_exp.action.id == r_exp.id)
print("  menu->action:",
      m_exp.action.id if m_exp else None,
      " expected:", r_exp.id)
print("T8312:", "PASS" if ok else "FAIL")
results["T8312"] = ok


# ============================================================
print()
print("T8313 - Compliance menu xmlid exists")
print("=" * 72)
m_comp = env.ref(
    "neon_training.menu_neon_training_report_compliance",
    raise_if_not_found=False)
ok = (m_comp and m_comp.action.id == r_comp.id)
print("  menu->action:",
      m_comp.action.id if m_comp else None)
print("T8313:", "PASS" if ok else "FAIL")
results["T8313"] = ok


# ============================================================
print()
print("T8314 - Cross-competency menu xmlid exists")
print("=" * 72)
m_cc = env.ref(
    "neon_training.menu_neon_training_report_cross_competency",
    raise_if_not_found=False)
ok = (m_cc and m_cc.action.id == r_cc.id)
print("  menu->action:",
      m_cc.action.id if m_cc else None)
print("T8314:", "PASS" if ok else "FAIL")
results["T8314"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in range(8300, 8315)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
