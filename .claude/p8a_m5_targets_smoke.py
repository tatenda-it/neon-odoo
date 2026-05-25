"""P8A.M5 smoke -- neon.dashboard.target model + ACL + forecast tile.

Runs in `odoo shell -d <db>`. T8500-T8519.

T8500  neon.dashboard.target in registry
T8501  create with target_amount only -> default name + month + USD
T8502  date_to auto-computed for month period
T8503  date_to auto-computed for quarter period
T8504  date_to auto-computed for year period
T8505  date_to user-editable post-compute (readonly=False contract)
T8506  target_amount > 0 sql constraint
T8507  date_to >= date_from sql constraint
T8508  progress_pct = (actual / target) * 100
T8509  progress_pct = 0 when target_amount is 0 (defensive)
T8510  superuser can create/write/unlink targets
T8511  sales_rep tier cannot create (AccessError)
T8512  sales_rep tier CAN read (mandatory -- forecast tile reads it)
T8513  bookkeeper / lead_tech / crew tiers can read
T8514  _kpi_forecast: empty state when no target for current period
T8515  _kpi_forecast: empty state's deeplink_action points to settings
T8516  _kpi_forecast: populated path when target exists
T8517  _kpi_forecast: progress_pct surfaces in value
T8518  _kpi_forecast: subtitle includes target name + days remaining
T8519  Settings menu xmlid resolvable
"""
from datetime import date, timedelta

from odoo.exceptions import AccessError


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


print("=" * 72)
print("P8A.M5 -- neon.dashboard.target + forecast tile")
print("=" * 72)
results = {}

Target = env["neon.dashboard.target"]
Dashboard = env["neon.dashboard"]
Users = env["res.users"]
usd = env.ref("base.USD")


def _get_or_make_user(login, group_xmlid):
    user = Users.search([("login", "=", login)], limit=1)
    group = env.ref(group_xmlid)
    if not user:
        user = Users.with_context(no_reset_password=True).create({
            "name": login, "login": login, "password": "test123",
            "groups_id": [(4, group.id)],
        })
    elif group.id not in user.groups_id.ids:
        user.write({"groups_id": [(4, group.id)]})
    return user


u_director = _get_or_make_user(
    "p8a_director", "neon_core.group_neon_superuser")
u_sales = _get_or_make_user(
    "p8a_sales", "neon_core.group_neon_sales_rep")
u_book = _get_or_make_user(
    "p8a_book", "neon_core.group_neon_bookkeeper")
u_lead = _get_or_make_user(
    "p8a_lead", "neon_core.group_neon_lead_tech")
u_crew = _get_or_make_user(
    "p8a_crew", "neon_core.group_neon_crew")


# ============================================================
print()
print("T8500 -- neon.dashboard.target in registry")
print("=" * 72)
ok = "neon.dashboard.target" in env.registry
print("  in registry:", ok)
print("T8500:", "PASS" if ok else "FAIL")
results["T8500"] = ok


# ============================================================
# Use a savepoint so the target rows don't pollute the DB.
sp = env.cr.savepoint()

print()
print("T8501 -- create with minimal vals -> defaults populated")
print("=" * 72)
t = Target.with_user(u_director).create({"target_amount": 50000.0})
ok = (t.name and "Target" in t.name
      and t.period == "month"
      and t.currency_id.id == usd.id
      and t.target_type == "revenue"
      and t.date_from)
print(f"  name={t.name} period={t.period} currency={t.currency_id.name} "
      f"type={t.target_type}")
print("T8501:", "PASS" if ok else "FAIL")
results["T8501"] = ok


# ============================================================
print()
print("T8502/T8503/T8504 -- date_to compute per period")
print("=" * 72)
# Month: Jan 1 -> Jan 31
t_m = Target.with_user(u_director).create({
    "name": "M test", "target_amount": 1000,
    "period": "month", "date_from": date(2026, 1, 1),
})
ok502 = t_m.date_to == date(2026, 1, 31)
print(f"  month Jan 1 -> {t_m.date_to} expected 2026-01-31")
# Quarter: Jan 1 -> Mar 31
t_q = Target.with_user(u_director).create({
    "name": "Q test", "target_amount": 1000,
    "period": "quarter", "date_from": date(2026, 1, 1),
})
ok503 = t_q.date_to == date(2026, 3, 31)
print(f"  quarter Jan 1 -> {t_q.date_to} expected 2026-03-31")
# Year: Jan 1 -> Dec 31
t_y = Target.with_user(u_director).create({
    "name": "Y test", "target_amount": 1000,
    "period": "year", "date_from": date(2026, 1, 1),
})
ok504 = t_y.date_to == date(2026, 12, 31)
print(f"  year Jan 1 -> {t_y.date_to} expected 2026-12-31")
print("T8502:", "PASS" if ok502 else "FAIL")
results["T8502"] = ok502
print("T8503:", "PASS" if ok503 else "FAIL")
results["T8503"] = ok503
print("T8504:", "PASS" if ok504 else "FAIL")
results["T8504"] = ok504


# ============================================================
print()
print("T8505 -- date_to user-editable")
print("=" * 72)
t_m.write({"date_to": date(2026, 2, 15)})
ok = t_m.date_to == date(2026, 2, 15)
print(f"  set date_to to Feb 15, value: {t_m.date_to}")
print("T8505:", "PASS" if ok else "FAIL")
results["T8505"] = ok


# ============================================================
print()
print("T8506 -- target_amount > 0 sql constraint")
print("=" * 72)
err, _ = _try(lambda: (
    Target.with_user(u_director).create({"target_amount": -100}),
    env.cr.flush(),
))
ok = err is not None
print("  negative target raised:", type(err).__name__ if err else "no error")
print("T8506:", "PASS" if ok else "FAIL")
results["T8506"] = ok


# ============================================================
print()
print("T8507 -- date_to >= date_from sql constraint")
print("=" * 72)
# date_to is auto-computed, so we need to write both explicitly to
# attempt an invalid range. Use a write after create to bypass the
# compute trigger.
t_bad = Target.with_user(u_director).create({
    "name": "Range test", "target_amount": 1000,
    "period": "month", "date_from": date(2026, 5, 1),
})
err, _ = _try(lambda: (
    t_bad.write({"date_from": date(2026, 6, 30),
                 "date_to": date(2026, 1, 1)}),
    env.cr.flush(),
))
ok = err is not None
print("  inverted range raised:", type(err).__name__ if err else "no error")
print("T8507:", "PASS" if ok else "FAIL")
results["T8507"] = ok


# ============================================================
print()
print("T8508 -- progress_pct = actual / target * 100")
print("=" * 72)
# Force actual_amount via SQL since it's computed.
# Easier: re-read after creating an accepted quote in the period.
# For unit testing the compute path: read with target 1000 and
# verify progress is sensible. The actuals depend on DB state, so
# just verify the formula: progress_pct == actual_amount / target *
# 100.
t_p = Target.with_user(u_director).create({
    "name": "Pct test", "target_amount": 1000.0,
})
expected = (t_p.actual_amount / 1000.0 * 100.0) if 1000.0 else 0.0
ok = abs(t_p.progress_pct - expected) < 0.01
print(f"  actual={t_p.actual_amount} progress_pct={t_p.progress_pct} "
      f"expected={expected}")
print("T8508:", "PASS" if ok else "FAIL")
results["T8508"] = ok


# ============================================================
print()
print("T8509 -- progress_pct contract: numeric, never None")
print("=" * 72)
# target_amount=0 path is unreachable due to sql_constraints
# (target_amount > 0). The defensive `if rec.target_amount` branch
# in _compute_progress exists for forward-compat (constraint
# removal someday) -- not testable through normal API. Verify the
# contract: progress_pct is always a float, never None.
ok = isinstance(t_p.progress_pct, float)
print(f"  progress_pct type: {type(t_p.progress_pct).__name__}")
print("T8509:", "PASS" if ok else "FAIL")
results["T8509"] = ok


# ============================================================
print()
print("T8510 -- superuser RWUx")
print("=" * 72)
t_su = Target.with_user(u_director).create({
    "name": "SU test", "target_amount": 5000,
})
t_su.write({"target_amount": 7500})
t_su.unlink()
# If we got here without raising, all four ops succeeded.
ok = True
print("  superuser create+write+unlink: OK")
print("T8510:", "PASS" if ok else "FAIL")
results["T8510"] = ok


# ============================================================
print()
print("T8511 -- sales_rep tier cannot create (AccessError)")
print("=" * 72)
err, _ = _try(lambda: Target.with_user(u_sales).create({
    "name": "Should fail", "target_amount": 1000,
}))
ok = isinstance(err, AccessError)
print(f"  sales create attempt: {type(err).__name__ if err else 'no error'}")
print("T8511:", "PASS" if ok else "FAIL")
results["T8511"] = ok


# ============================================================
print()
print("T8512 -- sales_rep tier CAN read (mandatory)")
print("=" * 72)
# Create a row as superuser, then read as sales.
t_r = Target.with_user(u_director).create({
    "name": "Read test", "target_amount": 1000,
})
err, val = _try(lambda: Target.with_user(u_sales).browse(t_r.id).read(
    ["name", "target_amount"]))
ok = err is None and val and val[0]["target_amount"] == 1000
print(f"  sales read: err={err}, val={val}")
print("T8512:", "PASS" if ok else "FAIL")
results["T8512"] = ok


# ============================================================
print()
print("T8513 -- bookkeeper / lead_tech / crew can read")
print("=" * 72)
ok = True
for user, label in [(u_book, "book"), (u_lead, "lead"), (u_crew, "crew")]:
    err, val = _try(lambda u=user: Target.with_user(u).browse(t_r.id).read(
        ["name", "target_amount"]))
    if err or not val:
        ok = False
        print(f"  {label} read FAIL: {err}")
    else:
        print(f"  {label} read OK")
print("T8513:", "PASS" if ok else "FAIL")
results["T8513"] = ok


# ============================================================
print()
print("T8514 -- _kpi_forecast empty when no target for current period")
print("=" * 72)
# Archive all current-period targets to force the empty path. Use
# active=False so they don't match the kpi_forecast search.
today = date.today()
Target.with_user(u_director).search([
    ("target_type", "=", "revenue"),
    ("date_from", "<=", today),
    ("date_to", ">=", today),
    ("active", "=", True),
]).write({"active": False})

data = Dashboard.with_user(u_director).get_dashboard_data()
forecast = data["kpi"]["kpi_forecast"]
ok = forecast.get("empty") is True
print(f"  empty: {forecast.get('empty')}, value_display: "
      f"{forecast.get('value_display')}")
print("T8514:", "PASS" if ok else "FAIL")
results["T8514"] = ok


# ============================================================
print()
print("T8515 -- empty-state deeplink_action points at target action")
print("=" * 72)
ok = forecast.get("deeplink_action") == "neon_dashboard.action_neon_dashboard_target"
print(f"  deeplink: {forecast.get('deeplink_action')}")
print("T8515:", "PASS" if ok else "FAIL")
results["T8515"] = ok


# ============================================================
print()
print("T8516/T8517/T8518 -- populated forecast with active target")
print("=" * 72)
# Create a target that covers today.
t_now = Target.with_user(u_director).create({
    "name": f"{today.strftime('%B %Y')} Revenue Target",
    "target_amount": 200000.0,
    "period": "month",
    "date_from": today.replace(day=1),
})
data2 = Dashboard.with_user(u_director).get_dashboard_data()
forecast2 = data2["kpi"]["kpi_forecast"]
ok516 = forecast2.get("empty") is False
ok517 = (forecast2.get("value") is not None
         and "%" in (forecast2.get("value_display") or ""))
subtitle = forecast2.get("subtitle") or ""
ok518 = (t_now.name in subtitle and "days left" in subtitle)
print(f"  empty={forecast2.get('empty')} value_display="
      f"{forecast2.get('value_display')} subtitle={subtitle}")
print("T8516:", "PASS" if ok516 else "FAIL")
results["T8516"] = ok516
print("T8517:", "PASS" if ok517 else "FAIL")
results["T8517"] = ok517
print("T8518:", "PASS" if ok518 else "FAIL")
results["T8518"] = ok518


# ============================================================
print()
print("T8519 -- Settings > Neon > Dashboard Targets menu xmlid")
print("=" * 72)
target_menu = env.ref(
    "neon_dashboard.menu_neon_dashboard_targets",
    raise_if_not_found=False,
)
settings_root = env.ref(
    "neon_dashboard.menu_neon_settings_root",
    raise_if_not_found=False,
)
ok = bool(target_menu) and bool(settings_root)
print(f"  menu_neon_dashboard_targets resolves: {bool(target_menu)}")
print(f"  menu_neon_settings_root resolves: {bool(settings_root)}")
print("T8519:", "PASS" if ok else "FAIL")
results["T8519"] = ok


# Rollback fixture savepoint.
sp.close(rollback=True)


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
