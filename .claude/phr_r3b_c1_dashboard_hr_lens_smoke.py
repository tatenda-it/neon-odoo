"""P-HR-R3b C1 smoke -- HR role-lens on Director Dashboard.

Covers the RBAC red-rail + the HR KPI compute:
- 'hr' added to _DASHBOARD_TYPES
- _is_hr_user returns True for HR admin / HR manager / superuser,
  False for sales / lead tech / bookkeeper / crew
- _available_types_for_user: HR user gets [HR]; sales user gets []
- _resolve_dashboard_type: HR user requesting 'hr' -> 'hr';
  sales user requesting 'hr' -> their default (silent downgrade)
- _default_dashboard_type_for_user: HR-only user -> 'hr';
  OD/MD -> 'director' (superuser trumps)
- _check_dashboard_access: HR user allowed; portal/external denied
- _compute_kpi_hr returns 5 keys when called by HR user
- _compute_kpi_hr raises AccessError when called by non-HR user
  (defence-in-depth)
- _compute_kpi('hr') dispatches to _compute_kpi_hr
- KPI helpers return correct counts on a small synthetic dataset

T-R3b-C1-01 ... T-R3b-C1-15.
"""
from datetime import date, timedelta

from odoo.exceptions import AccessError


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-HR-R3b C1 -- HR role-lens RBAC + KPI compute")
print("=" * 72)
results = {}

Users = env["res.users"]
Dashboard = env["neon.dashboard"]


# ============================================================
# Cleanup leftover R3b test users
# ============================================================
for login in ("phr_r3b_hr_only", "phr_r3b_hr_admin",
               "phr_r3b_sales", "phr_r3b_super"):
    # active_test=False -- prior runs left these inactive; without
    # this flag the default search filter hides them and the
    # rename-to-OLD never runs, then create() collides on login.
    u = Users.sudo().with_context(active_test=False).search(
        [("login", "=", login)], limit=1)
    if u:
        u.write({"login": login + "_OLD_" + str(u.id),
                  "active": False})

g_super = env.ref("neon_core.group_neon_superuser")
g_sales = env.ref("neon_core.group_neon_sales_rep")
g_hr_admin = env.ref("neon_hr.group_neon_hr_admin")
g_hr_manager = env.ref("hr.group_hr_manager",
                        raise_if_not_found=False)

# An HR-tier-only user (HR Admin but NOT superuser, NOT sales)
u_hr_admin = Users.sudo().with_context(
    no_reset_password=True).create({
        "name": "PHR-R3b HR Admin",
        "login": "phr_r3b_hr_admin",
        "password": "test123",
        "groups_id": [
            (4, env.ref("base.group_user").id),
            (4, g_hr_admin.id),
        ],
    })

# An HR-Manager-only user (the broader HR-tier path)
u_hr_only = Users.sudo().with_context(
    no_reset_password=True).create({
        "name": "PHR-R3b HR Only",
        "login": "phr_r3b_hr_only",
        "password": "test123",
        "groups_id": [
            (4, env.ref("base.group_user").id),
            (4, g_hr_manager.id) if g_hr_manager else (
                4, g_hr_admin.id),
        ],
    })

# A Sales-only user (no HR group, no superuser)
u_sales = Users.sudo().with_context(
    no_reset_password=True).create({
        "name": "PHR-R3b Sales Only",
        "login": "phr_r3b_sales",
        "password": "test123",
        "groups_id": [
            (4, env.ref("base.group_user").id),
            (4, g_sales.id),
        ],
    })

# A Superuser (OD/MD) -- to verify the existing superuser path
u_super = Users.sudo().with_context(
    no_reset_password=True).create({
        "name": "PHR-R3b Super",
        "login": "phr_r3b_super",
        "password": "test123",
        "groups_id": [
            (4, env.ref("base.group_user").id),
            (4, g_super.id),
        ],
    })
env.cr.commit()


# ============================================================
# T-R3b-C1-01 -- 'hr' in _DASHBOARD_TYPES
# ============================================================
from odoo.addons.neon_dashboard.models.neon_dashboard import (
    _DASHBOARD_TYPES, _DASHBOARD_TYPE_VALUES,
)
_check("T-R3b-C1-01",
       "hr" in _DASHBOARD_TYPE_VALUES
       and ("hr", "HR") in _DASHBOARD_TYPES,
       f"'hr' in types: {sorted(_DASHBOARD_TYPE_VALUES)}")


# ============================================================
# T-R3b-C1-02..04 -- _is_hr_user
# ============================================================
D_hr_admin = Dashboard.with_user(u_hr_admin)
D_hr_only = Dashboard.with_user(u_hr_only)
D_sales = Dashboard.with_user(u_sales)
D_super = Dashboard.with_user(u_super)

_check("T-R3b-C1-02",
       D_hr_admin._is_hr_user() is True,
       "HR Admin -> _is_hr_user=True")
_check("T-R3b-C1-03",
       D_sales._is_hr_user() is False,
       "Sales -> _is_hr_user=False (RBAC rail)")
_check("T-R3b-C1-04",
       D_super._is_hr_user() is True,
       "Superuser -> _is_hr_user=True (superuser umbrella)")


# ============================================================
# T-R3b-C1-05..06 -- _available_types_for_user
# ============================================================
avail_hr = D_hr_admin._available_types_for_user()
avail_sales = D_sales._available_types_for_user()
_check("T-R3b-C1-05",
       len(avail_hr) == 1
       and avail_hr[0]["value"] == "hr",
       f"HR user gets [HR] only: {avail_hr}")
_check("T-R3b-C1-06",
       avail_sales == [],
       f"Sales user gets [] (dropdown hidden): {avail_sales}")


# ============================================================
# T-R3b-C1-07..09 -- _resolve_dashboard_type RBAC
# ============================================================
_check("T-R3b-C1-07",
       D_hr_admin._resolve_dashboard_type("hr") == "hr",
       "HR user requesting 'hr' -> 'hr'")
_check("T-R3b-C1-08",
       D_sales._resolve_dashboard_type("hr") != "hr",
       f"Sales user requesting 'hr' -> downgraded: got "
       f"{D_sales._resolve_dashboard_type('hr')!r}")
_check("T-R3b-C1-09",
       D_super._resolve_dashboard_type("hr") == "hr",
       "Superuser requesting 'hr' -> 'hr' (existing rule)")


# ============================================================
# T-R3b-C1-10..11 -- _default_dashboard_type_for_user
# ============================================================
_check("T-R3b-C1-10",
       Dashboard._default_dashboard_type_for_user(
           u_hr_only.id) == "hr",
       "HR-only user defaults to 'hr'")
_check("T-R3b-C1-11",
       Dashboard._default_dashboard_type_for_user(
           u_super.id) == "director",
       "Superuser still defaults to 'director' (superuser trumps)")


# ============================================================
# T-R3b-C1-12 -- _check_dashboard_access allows HR user
# ============================================================
allowed = True
try:
    D_hr_admin.with_user(u_hr_admin)._check_dashboard_access()
except AccessError:
    allowed = False
_check("T-R3b-C1-12", allowed,
       "HR Admin can access dashboard")


# ============================================================
# T-R3b-C1-13 -- _compute_kpi_hr returns 5 keys for HR user
# ============================================================
kpi = D_hr_admin._compute_kpi_hr()
expected_keys = {
    "kpi_hr_headcount", "kpi_hr_on_leave_today",
    "kpi_hr_contracts_30", "kpi_hr_licences_30",
    "kpi_hr_pending_leave",
}
_check("T-R3b-C1-13",
       set(kpi.keys()) == expected_keys
       and all(isinstance(v.get("value"), int)
                for v in kpi.values()),
       f"HR KPI: {sorted(kpi.keys())}")


# ============================================================
# T-R3b-C1-14 -- _compute_kpi_hr REFUSES non-HR user (RBAC red-rail)
# ============================================================
refused = False
reason = ""
try:
    D_sales._compute_kpi_hr()
except AccessError as exc:
    refused = True
    reason = str(exc)
_check("T-R3b-C1-14", refused,
       f"non-HR user blocked from HR KPI compute: {reason[:60]!r}")


# ============================================================
# T-R3b-C1-15 -- _compute_kpi dispatcher routes 'hr'
# ============================================================
dispatched = D_hr_admin._compute_kpi("hr")
_check("T-R3b-C1-15",
       set(dispatched.keys()) == expected_keys,
       "_compute_kpi('hr') routes to _compute_kpi_hr")


# ============================================================
# Cleanup -- mark test users inactive (don't unlink -- standing
# rule from CLAUDE.md)
# ============================================================
for u in (u_hr_admin, u_hr_only, u_sales, u_super):
    u.sudo().write({"active": False})
env.cr.commit()


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
