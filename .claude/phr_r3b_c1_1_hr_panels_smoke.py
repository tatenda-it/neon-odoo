"""P-HR-R3b C1.1 smoke -- HR variant panels + payload integration."""
from odoo.exceptions import AccessError


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-HR-R3b C1.1 -- HR panels + payload integration")
print("=" * 72)
results = {}

Users = env["res.users"]
Dashboard = env["neon.dashboard"]
DefaultLayout = env["neon.dashboard.default.layout"].sudo()


for login in ("phr_r3b_c11_hr_admin", "phr_r3b_c11_sales"):
    u = Users.sudo().with_context(active_test=False).search(
        [("login", "=", login)], limit=1)
    if u:
        u.write({"login": login + "_OLD_" + str(u.id),
                  "active": False})

g_hr_admin = env.ref("neon_hr.group_neon_hr_admin")
g_sales = env.ref("neon_core.group_neon_sales_rep")

u_hr = Users.sudo().with_context(no_reset_password=True).create({
    "name": "PHR-R3b C1.1 HR Admin",
    "login": "phr_r3b_c11_hr_admin",
    "password": "test123",
    "groups_id": [
        (4, env.ref("base.group_user").id),
        (4, g_hr_admin.id),
    ],
})
u_sales = Users.sudo().with_context(no_reset_password=True).create({
    "name": "PHR-R3b C1.1 Sales",
    "login": "phr_r3b_c11_sales",
    "password": "test123",
    "groups_id": [
        (4, env.ref("base.group_user").id),
        (4, g_sales.id),
    ],
})
env.cr.commit()

D_hr = Dashboard.with_user(u_hr)
D_sales = Dashboard.with_user(u_sales)


contracts = D_hr._compute_hr_contracts_expiring_block()
_check("T-R3b-C11-01",
       isinstance(contracts, dict)
       and "rows" in contracts
       and "title" in contracts
       and "row_count" in contracts
       and isinstance(contracts["rows"], list)
       and len(contracts["rows"]) <= 10,
       f"contracts block shape: {sorted(contracts.keys())} "
       f"rows={len(contracts['rows'])}")


licences = D_hr._compute_hr_licences_expiring_block()
_check("T-R3b-C11-02",
       isinstance(licences, dict)
       and "rows" in licences
       and isinstance(licences["rows"], list)
       and len(licences["rows"]) <= 10,
       f"licences block: {sorted(licences.keys())} "
       f"rows={len(licences['rows'])}")


leaves = D_hr._compute_hr_pending_leaves_block()
_check("T-R3b-C11-03",
       isinstance(leaves, dict)
       and "rows" in leaves
       and isinstance(leaves["rows"], list)
       and len(leaves["rows"]) <= 10,
       f"leaves block: {sorted(leaves.keys())} "
       f"rows={len(leaves['rows'])}")


refused_contracts = False
try:
    D_sales._compute_hr_contracts_expiring_block()
except AccessError:
    refused_contracts = True
_check("T-R3b-C11-04", refused_contracts,
       "contracts panel refuses non-HR caller")

refused_licences = False
try:
    D_sales._compute_hr_licences_expiring_block()
except AccessError:
    refused_licences = True
_check("T-R3b-C11-05", refused_licences,
       "licences panel refuses non-HR caller")

refused_leaves = False
try:
    D_sales._compute_hr_pending_leaves_block()
except AccessError:
    refused_leaves = True
_check("T-R3b-C11-06", refused_leaves,
       "pending leaves panel refuses non-HR caller")


payload = D_hr.get_dashboard_data("hr")
_check("T-R3b-C11-07",
       payload.get("dashboard_type") == "hr"
       and "kpi" in payload
       and "hr_contracts_block" in payload
       and "hr_licences_block" in payload
       and "hr_pending_leaves_block" in payload,
       f"HR payload keys present: dashboard_type="
       f"{payload.get('dashboard_type')}")


payload_s = D_sales.get_dashboard_data("hr")
_check("T-R3b-C11-08",
       payload_s.get("dashboard_type") != "hr"
       and "hr_contracts_block" not in payload_s
       and "hr_licences_block" not in payload_s
       and "hr_pending_leaves_block" not in payload_s,
       f"Sales requesting 'hr' downgraded (dashboard_type="
       f"{payload_s.get('dashboard_type')}); no HR blocks in payload")


seed = DefaultLayout.search(
    [("dashboard_type", "=", "hr")], limit=1)
seeded_keys = sorted(l.widget_key for l in seed.layout_line_ids)
expected = {
    "kpi_hr_headcount", "kpi_hr_on_leave_today",
    "kpi_hr_contracts_30", "kpi_hr_licences_30",
    "kpi_hr_pending_leave",
    "block_hr_contracts", "block_hr_licences",
    "block_hr_pending_leaves",
    "block_alerts", "block_tasks",
}
_check("T-R3b-C11-09",
       bool(seed) and set(seeded_keys) == expected,
       f"HR default layout seed count={len(seed.layout_line_ids)} "
       f"keys_match={set(seeded_keys) == expected}")


for u in (u_hr, u_sales):
    u.sudo().write({"active": False})
env.cr.commit()


print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
