"""P8A.M1 smoke -- neon.dashboard model + lazy create + layout seed
+ ACL fences.

Runs in `odoo shell -d <db>`. T8100-T8119.

T8100  neon.dashboard exists in registry
T8101  default layouts seeded (5 rows -- director / sales /
       bookkeeper / lead_tech / tech)
T8102  director seed has 14 widget entries
T8103  sales seed has 9 widget entries
T8104  bookkeeper seed has 8 widget entries
T8105  lead_tech seed has 7 widget entries
T8106  tech seed has 4 widget entries
T8107  get_or_create_for_user creates a row for a new user+type
T8108  get_or_create_for_user is idempotent (second call returns same row)
T8109  unique(user, type) constraint blocks duplicate director dashboards
T8110  _seed_default_layout materialises the right widget set
T8111  _default_dashboard_type_for_user: superuser -> director
T8112  _default_dashboard_type_for_user: bookkeeper -> bookkeeper
T8113  _default_dashboard_type_for_user: sales_rep -> sales
T8114  _default_dashboard_type_for_user: lead_tech -> lead_tech
T8115  _default_dashboard_type_for_user: crew -> tech
T8116  preferred_dashboard_type override wins over tier-walk
T8117  mandatory widget kpi_cash cannot be hidden (silently restored)
T8118  mandatory widget kpi_ar_overdue cannot be hidden
T8119  mandatory widget block_alerts cannot be hidden
"""
from odoo.exceptions import AccessError, ValidationError


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


print("=" * 72)
print("P8A.M1 -- neon.dashboard model + lazy create + layout seed")
print("=" * 72)
results = {}

Dashboard = env["neon.dashboard"]
Default = env["neon.dashboard.default.layout"]
UserLayout = env["neon.dashboard.user.layout"]
Users = env["res.users"]


# ----------------------------------------------------------------------
# Fixture: dedicated p8a_* test users, one per tier. Create-or-get so
# repeat runs reuse the same uids (matches the persistence convention
# from CLAUDE.md). NEVER touches the existing p2m75_* fixtures.
# ----------------------------------------------------------------------
_TIER_LOGIN_MAP = [
    ("p8a_director", "neon_core.group_neon_superuser"),
    ("p8a_book",     "neon_core.group_neon_bookkeeper"),
    ("p8a_sales",    "neon_core.group_neon_sales_rep"),
    ("p8a_lead",     "neon_core.group_neon_lead_tech"),
    ("p8a_crew",     "neon_core.group_neon_crew"),
]


def _get_or_make_user(login, group_xmlid):
    user = Users.search([("login", "=", login)], limit=1)
    group = env.ref(group_xmlid)
    if not user:
        user = Users.with_context(no_reset_password=True).create({
            "name": login,
            "login": login,
            "password": "test123",
            "groups_id": [(4, group.id)],
        })
    else:
        # Idempotent: ensure the tier group is present even if the
        # user existed from a prior run that pre-dated the dashboard
        # module install.
        if group.id not in user.groups_id.ids:
            user.write({"groups_id": [(4, group.id)]})
    return user


tier_users = {
    login: _get_or_make_user(login, xmlid)
    for login, xmlid in _TIER_LOGIN_MAP
}
u_director = tier_users["p8a_director"]
u_book = tier_users["p8a_book"]
u_sales = tier_users["p8a_sales"]
u_lead = tier_users["p8a_lead"]
u_crew = tier_users["p8a_crew"]


# ============================================================
print()
print("T8100 -- neon.dashboard model in registry")
print("=" * 72)
ok = "neon.dashboard" in env.registry
print("  registry has neon.dashboard:", ok)
print("T8100:", "PASS" if ok else "FAIL")
results["T8100"] = ok


# ============================================================
print()
print("T8101 -- default_layouts.xml seeded 5 rows")
print("=" * 72)
seeds = Default.search([])
type_set = set(seeds.mapped("dashboard_type"))
expected = {"director", "sales", "bookkeeper", "lead_tech", "tech"}
ok = type_set == expected
print("  seeded types:", sorted(type_set))
print("T8101:", "PASS" if ok else "FAIL")
results["T8101"] = ok


# ============================================================
def _seed_count(dashboard_type):
    seed = Default.search([("dashboard_type", "=", dashboard_type)], limit=1)
    return len(seed.layout_line_ids)


# P8B: sales 9->12, bookkeeper 8->13, lead_tech 7->11 (new variant
# KPI tiles + blocks). Director (14) + tech (4) unchanged.
for tnum, dtype, expected_count in [
    ("T8102", "director", 14),
    ("T8103", "sales", 12),
    ("T8104", "bookkeeper", 13),
    ("T8105", "lead_tech", 11),
    ("T8106", "tech", 4),
]:
    print()
    print(f"{tnum} -- {dtype} seed has {expected_count} widget entries")
    print("=" * 72)
    actual = _seed_count(dtype)
    ok = actual == expected_count
    print(f"  {dtype} widget count:", actual, "expected:", expected_count)
    print(f"{tnum}:", "PASS" if ok else "FAIL")
    results[tnum] = ok


# ============================================================
print()
print("T8107 -- get_or_create_for_user creates row for new user")
print("=" * 72)
# Clean any pre-existing director row for u_book so we test creation.
Dashboard.sudo().search(
    [("user_id", "=", u_book.id),
     ("dashboard_type", "=", "director")]).unlink() \
    if Dashboard.sudo().search(
        [("user_id", "=", u_book.id),
         ("dashboard_type", "=", "director")]) else None
d = Dashboard.sudo().get_or_create_for_user(
    user_id=u_book.id, dashboard_type="director")
ok = bool(d.id) and d.user_id.id == u_book.id and d.dashboard_type == "director"
print("  created id:", d.id, "user:", d.user_id.login, "type:", d.dashboard_type)
print("T8107:", "PASS" if ok else "FAIL")
results["T8107"] = ok


# ============================================================
print()
print("T8108 -- get_or_create_for_user idempotent")
print("=" * 72)
d_first = Dashboard.sudo().get_or_create_for_user(
    user_id=u_book.id, dashboard_type="director")
d_second = Dashboard.sudo().get_or_create_for_user(
    user_id=u_book.id, dashboard_type="director")
ok = d_first.id == d_second.id
print("  first id:", d_first.id, "second id:", d_second.id)
print("T8108:", "PASS" if ok else "FAIL")
results["T8108"] = ok


# ============================================================
print()
print("T8109 -- unique(user, type) constraint blocks duplicates")
print("=" * 72)
# A second create with same (user, type) must raise IntegrityError on flush.
err, _ = _try(lambda: (
    Dashboard.sudo().create({
        "user_id": u_book.id, "dashboard_type": "director"}),
    env.cr.flush(),
))
ok = err is not None
print("  duplicate raised:", type(err).__name__ if err else "no error")
print("T8109:", "PASS" if ok else "FAIL")
results["T8109"] = ok


# ============================================================
print()
print("T8110 -- _seed_default_layout materialises matching widget set")
print("=" * 72)
# P8B.M1: sales seed reworked to 12 entries (6 KPIs + 6 blocks).
# Create a fresh sales dashboard for u_sales and check the materialised
# layout matches the new widget set.
Dashboard.sudo().search([
    ("user_id", "=", u_sales.id),
    ("dashboard_type", "=", "sales")]).unlink()
d_sales = Dashboard.sudo().get_or_create_for_user(
    user_id=u_sales.id, dashboard_type="sales")
layout_keys = set(d_sales.layout_ids.mapped("widget_key"))
expected_sales = {"kpi_pipeline", "kpi_leads", "kpi_hot_deals",
                  "kpi_aging_quotes", "kpi_won_mtd", "kpi_win_rate",
                  "block_sales", "block_hot_deals", "block_aging_quotes",
                  "block_alerts", "block_tasks", "block_ai_insights"}
ok = layout_keys == expected_sales
print("  layout keys:", sorted(layout_keys))
print("T8110:", "PASS" if ok else "FAIL")
results["T8110"] = ok


# ============================================================
for tnum, user, expected_type in [
    ("T8111", u_director, "director"),
    ("T8112", u_book, "bookkeeper"),
    ("T8113", u_sales, "sales"),
    ("T8114", u_lead, "lead_tech"),
    ("T8115", u_crew, "tech"),
]:
    print()
    print(f"{tnum} -- _default_dashboard_type_for_user: "
          f"{user.login} -> {expected_type}")
    print("=" * 72)
    actual = Dashboard._default_dashboard_type_for_user(user.id)
    ok = actual == expected_type
    print(f"  {user.login} default:", actual)
    print(f"{tnum}:", "PASS" if ok else "FAIL")
    results[tnum] = ok


# ============================================================
print()
print("T8116 -- preferred_dashboard_type override wins")
print("=" * 72)
# u_sales naturally maps to 'sales'. Set preferred to 'lead_tech'.
u_sales.write({"preferred_dashboard_type": "lead_tech"})
actual = Dashboard._default_dashboard_type_for_user(u_sales.id)
ok = actual == "lead_tech"
print("  with preferred=lead_tech, default:", actual)
# Clean up so subsequent tests / smoke cycles see baseline.
u_sales.write({"preferred_dashboard_type": False})
print("T8116:", "PASS" if ok else "FAIL")
results["T8116"] = ok


# ============================================================
def _mandatory_test(tnum, widget_key):
    """Mandatory widget can't be hidden -- write must succeed but the
    record's visible flag must remain True (silent restore + log)."""
    print()
    print(f"{tnum} -- mandatory widget {widget_key} cannot be hidden")
    print("=" * 72)
    # Ensure u_director has a director dashboard with this widget.
    d = Dashboard.sudo().get_or_create_for_user(
        user_id=u_director.id, dashboard_type="director")
    line = d.layout_ids.filtered(lambda l: l.widget_key == widget_key)
    if not line:
        print(f"  no {widget_key} line for u_director; skipping")
        results[tnum] = False
        return
    line.sudo().write({"visible": False})
    # Re-read from DB to verify the constrains restored it.
    line.invalidate_recordset(["visible"])
    ok = line.visible is True
    print(f"  {widget_key} visible after write(False):", line.visible)
    print(f"{tnum}:", "PASS" if ok else "FAIL")
    results[tnum] = ok


_mandatory_test("T8117", "kpi_cash")
_mandatory_test("T8118", "kpi_ar_overdue")
_mandatory_test("T8119", "block_alerts")


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
