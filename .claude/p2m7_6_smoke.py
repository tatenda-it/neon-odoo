"""P2.M7.6 smoke — role hardening: kill auto-implication, gate cross-module menus."""
from odoo import fields

print("=" * 72)
print("SETUP")
print("=" * 72)

# Cleanup any previous T27 user
env["res.users"].sudo().search([("login", "=", "p2m76_fresh_internal")]).unlink()
env.cr.commit()

# Re-fetch the test users created in P2.M7 + P2.M7.5
sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
crew_leader = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
crew_only = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
print("sales groups:", [g.name for g in sales.groups_id
                          if g.category_id.name == "Neon Operations"])
print("manager groups:", [g.name for g in manager.groups_id
                            if g.category_id.name == "Neon Operations"])
print("crew_leader groups:", [g.name for g in crew_leader.groups_id
                                if g.category_id.name == "Neon Operations"])
print("crew_only groups:", [g.name for g in crew_only.groups_id
                              if g.category_id.name == "Neon Operations"])

results = {}

# ============================================================
print()
print("=" * 72)
print("T27 - Auto-implication removed: fresh internal user has NO neon_jobs_user")
print("=" * 72)
fresh = env["res.users"].create({
    "name": "P2M76 Fresh Internal", "login": "p2m76_fresh_internal",
    "email": "p2m76_fresh@test.local",
    "groups_id": [(6, 0, [env.ref("base.group_user").id])],
})
ok = not fresh.has_group("neon_jobs.group_neon_jobs_user")
print("T27: fresh user neon_jobs_user?", fresh.has_group("neon_jobs.group_neon_jobs_user"),
      " (want False)")
print("T27:", "PASS" if ok else "FAIL")
results["T27"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T28 - Existing sales user retains commercial.job read access")
print("=" * 72)
# p2m75_sales had crew_leader leak; post-migrate stripped neon_jobs_user.
# But we explicitly want a sales user with neon_jobs_user. Use one of the
# Neon team users instead — munashe@neonhiring.co.zw.
sales_real = env["res.users"].search([
    ("login", "=", "munashe@neonhiring.co.zw"),
], limit=1)
try:
    jobs = env["commercial.job"].with_user(sales_real).search([], limit=1)
    ok = True  # search succeeded → has read access
    print("T28: munashe@ (neon_jobs_user) read commercial.job → OK, returned",
          len(jobs), "records")
except Exception as e:
    print("T28 FAIL:", type(e).__name__, ":", str(e)[:120])
    ok = False
print("T28:", "PASS" if ok else "FAIL")
results["T28"] = ok

# ============================================================
print()
print("=" * 72)
print("T29 - Crew user is internal, not portal")
print("=" * 72)
internal = env.ref("base.group_user")
portal = env.ref("base.group_portal")
ok = (internal in crew_only.groups_id and portal not in crew_only.groups_id)
print("T29: crew_only internal?", internal in crew_only.groups_id,
      " portal?", portal in crew_only.groups_id)
print("T29:", "PASS" if ok else "FAIL")
results["T29"] = ok

# ============================================================
print()
print("=" * 72)
print("T30 - Crew user menu visibility: My Schedule + My Calendar yes, ")
print("      Operations Dashboard no")
print("=" * 72)
ops_dash = env.ref("neon_jobs.menu_operations_dashboard")
my_sched = env.ref("neon_jobs.menu_my_schedule")
my_cal = env.ref("neon_jobs.menu_my_calendar")
# Apply ir.ui.menu's visibility filter as the crew user would see it
visible = env["ir.ui.menu"].with_user(crew_only).search([
    ("id", "in", [ops_dash.id, my_sched.id, my_cal.id]),
])
ops_in = ops_dash in visible
sched_in = my_sched in visible
cal_in = my_cal in visible
ok = (not ops_in) and sched_in and cal_in
print("T30: ops_dashboard visible?", ops_in, "(want False)")
print("     my_schedule visible?  ", sched_in, "(want True)")
print("     my_calendar visible?  ", cal_in, "(want True)")
print("T30:", "PASS" if ok else "FAIL")
results["T30"] = ok

# ============================================================
print()
print("=" * 72)
print("T31 - Crew Leader cannot see Money fields on commercial.job form")
print("=" * 72)
# Render the form view arch as crew_leader would see it.
# get_view applies the groups attribute filter.
view_def = env["commercial.job"].with_user(crew_leader).get_view(
    view_id=env.ref("neon_jobs.commercial_job_view_form").id,
    view_type="form",
)
arch = view_def.get("arch", "")
contains_quoted = "quoted_value" in arch
contains_deposit = "deposit_received" in arch
contains_finance = "finance_status" in arch
ok = not (contains_quoted or contains_deposit or contains_finance)
print("T31: arch contains quoted_value?", contains_quoted, "(want False)")
print("     arch contains deposit_received?", contains_deposit, "(want False)")
print("     arch contains finance_status?", contains_finance, "(want False)")
print("T31:", "PASS" if ok else "FAIL")
results["T31"] = ok

# ============================================================
print()
print("=" * 72)
print("T32 - Crew user does NOT see Sales/CRM/Invoicing menus")
print("=" * 72)
sale_root = env.ref("sale.sale_menu_root", raise_if_not_found=False)
crm_root = env.ref("crm.crm_menu_root", raise_if_not_found=False)
finance_root = env.ref("account.menu_finance", raise_if_not_found=False)
contacts_root = env.ref("contacts.menu_contacts", raise_if_not_found=False) \
                or env.ref("base.menu_contacts", raise_if_not_found=False)
ops_root = env.ref("neon_jobs.menu_operations_root")
ids = [m.id for m in [sale_root, crm_root, finance_root, ops_root] if m]
visible = env["ir.ui.menu"].with_user(crew_only).search([("id", "in", ids)])
sale_in = sale_root and sale_root in visible
crm_in = crm_root and crm_root in visible
finance_in = finance_root and finance_root in visible
ops_in = ops_root in visible
ok = (not sale_in) and (not crm_in) and (not finance_in) and ops_in
print("T32: Sales visible?     ", sale_in, "(want False)")
print("     CRM visible?       ", crm_in, "(want False)")
print("     Invoicing visible? ", finance_in, "(want False)")
print("     Operations visible?", ops_in, "(want True)")
print("T32:", "PASS" if ok else "FAIL")
results["T32"] = ok

# ============================================================
print()
print("=" * 72)
print("T33 - Sales user (neon_jobs_user) sees Sales + CRM")
print("=" * 72)
visible = env["ir.ui.menu"].with_user(sales_real).search([
    ("id", "in", [sale_root.id, crm_root.id]),
])
sale_in = sale_root in visible
crm_in = crm_root in visible
ok = sale_in and crm_in
print("T33: Sales visible for munashe@?", sale_in, "(want True)")
print("     CRM visible for munashe@?  ", crm_in, "(want True)")
print("T33:", "PASS" if ok else "FAIL")
results["T33"] = ok

# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T27", "T28", "T29", "T30", "T31", "T32", "T33"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
