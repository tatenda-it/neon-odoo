"""P5.M10 smoke — Workshop Dashboard backend (13 tests).

OWL component is JS — covered by browser smoke after commit. These
tests cover the @api.model count helpers, get_dashboard_data wire
shape, and ir.actions.act_window resolution.

T400  dashboard model exists and is callable
T401  _count_active_units matches Unit.search_count(state='active')
T402  _count_units_out matches Unit.search_count(state='checked_out')
T403  _count_reservations_next_7days filters to active holds in window
T404  _count_pending_transfers matches Movement transfer_state='pending'
T405  _count_late_returns matches late_return_pending=True
T406  _count_equipment_conflicts_open matches widened state filter
T407  _count_stock_discrepancies_open matches unresolved discrepancies
T408  _count_repair_orders_open uses _NON_TERMINAL_STATES
T409  _count_incidents_open excludes resolved_* + cancelled
T410  _count_high_impact_30d window: 35-day line NOT counted
T411  get_dashboard_data wire shape — 10 keys + last_updated
T412  every action_id resolves to a valid ir.actions.act_window
T413  AccessError on get_dashboard_data for crew tier
T414  Manager passes (no error, returns dict)
T415  Crew Leader passes (no error, returns dict)
T416  Other non-allowed user blocked
T417  Server-action wrapper .run() as manager — returns client-action dict
T418  Server-action wrapper .run() as crew — AccessError
T419  Server-action wrapper .run() as crew_leader — returns client-action dict
"""
from datetime import datetime, timedelta

from odoo.exceptions import AccessError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Dashboard = env["neon.equipment.dashboard"]
Unit = env["neon.equipment.unit"]
Reservation = env["neon.equipment.reservation"]
Movement = env["neon.equipment.movement"]
Item = env["action.centre.item"]
StockTake = env["neon.equipment.stock.take"]
StockLine = env["neon.equipment.stock.take.line"]
Repair = env["neon.equipment.repair.order"]
Incident = env["neon.equipment.incident"]
ActWindow = env["ir.actions.act_window"]
Category = env["neon.equipment.category"]

manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
lead = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
crew_user = env["res.users"].search(
    [("login", "=", "p2m75_crew")], limit=1)
other_user = env["res.users"].search(
    [("login", "=", "p2m75_other")], limit=1)
assert manager, "p2m75_mgr seed user missing"
assert lead, "p2m75_lead seed user missing"
assert crew_user, "p2m75_crew seed user missing"
assert other_user, "p2m75_other seed user missing"


# ============================================================
print()
print("=" * 72)
print("T400 - dashboard model exists and is callable")
print("=" * 72)
try:
    # Model lookup + a trivial @api.model call to confirm
    # registration + ACL load order.
    assert Dashboard._name == "neon.equipment.dashboard"
    _ = Dashboard.sudo()._count_active_units()
    ok = True
except Exception as e:  # noqa: BLE001
    print("  raised:", type(e).__name__, str(e)[:200])
    ok = False
print("  model:", Dashboard._name)
print("T400:", "PASS" if ok else "FAIL")
results["T400"] = ok


# ============================================================
print()
print("=" * 72)
print("T401 - _count_active_units matches search_count")
print("=" * 72)
expected = Unit.sudo().search_count([("state", "=", "active")])
got = Dashboard.sudo()._count_active_units()
ok = (got == expected)
print("  expected:", expected, " got:", got)
print("T401:", "PASS" if ok else "FAIL")
results["T401"] = ok


# ============================================================
print()
print("=" * 72)
print("T402 - _count_units_out matches search_count")
print("=" * 72)
expected = Unit.sudo().search_count([("state", "=", "checked_out")])
got = Dashboard.sudo()._count_units_out()
ok = (got == expected)
print("  expected:", expected, " got:", got)
print("T402:", "PASS" if ok else "FAIL")
results["T402"] = ok


# ============================================================
print()
print("=" * 72)
print("T403 - _count_reservations_next_7days filters by window + state")
print("=" * 72)
now = datetime.utcnow()
# Build the same domain as the helper.
expected = Reservation.sudo().search_count([
    ("state", "in", ("soft_hold", "confirmed")),
    ("reserve_from", ">=", now),
    ("reserve_from", "<=", now + timedelta(days=7)),
])
got = Dashboard.sudo()._count_reservations_next_7days()
# Within 1 second tolerance — helper computes now() itself, so the
# match must be exact under normal conditions but allow a 2-second
# drift if the search and helper straddle a second boundary.
ok = abs(got - expected) <= 1
print("  expected:", expected, " got:", got)
print("T403:", "PASS" if ok else "FAIL")
results["T403"] = ok


# ============================================================
print()
print("=" * 72)
print("T404 - _count_pending_transfers matches transfer_state='pending'")
print("=" * 72)
expected = Movement.sudo().search_count(
    [("transfer_state", "=", "pending")])
got = Dashboard.sudo()._count_pending_transfers()
ok = (got == expected)
print("  expected:", expected, " got:", got)
print("T404:", "PASS" if ok else "FAIL")
results["T404"] = ok


# ============================================================
print()
print("=" * 72)
print("T405 - _count_late_returns matches late_return_pending=True")
print("=" * 72)
expected = Reservation.sudo().search_count(
    [("late_return_pending", "=", True)])
got = Dashboard.sudo()._count_late_returns()
ok = (got == expected)
print("  expected:", expected, " got:", got)
print("T405:", "PASS" if ok else "FAIL")
results["T405"] = ok


# ============================================================
print()
print("=" * 72)
print("T406 - _count_equipment_conflicts_open widened to (open, in_progress)")
print("=" * 72)
baseline = Dashboard.sudo()._count_equipment_conflicts_open()
# Seed two items — one 'open', one 'in_progress'. Both must count.
seed_a = Item.sudo().create({
    "title": "P5.M10 smoke — conflict open",
    "trigger_type": "equipment_conflict",
    "state": "open",
    "item_type": "task",
})
seed_b = Item.sudo().create({
    "title": "P5.M10 smoke — conflict in_progress",
    "trigger_type": "equipment_conflict",
    "state": "in_progress",
    "item_type": "task",
})
# And a 'done' item — must NOT count.
seed_c = Item.sudo().create({
    "title": "P5.M10 smoke — conflict done",
    "trigger_type": "equipment_conflict",
    "state": "done",
    "item_type": "task",
})
after = Dashboard.sudo()._count_equipment_conflicts_open()
ok = (after - baseline == 2)
print("  baseline:", baseline, " after +2 open/in_progress +1 done:", after)
print("T406:", "PASS" if ok else "FAIL")
results["T406"] = ok


# ============================================================
print()
print("=" * 72)
print("T407 - _count_stock_discrepancies_open matches unresolved")
print("=" * 72)
expected = StockLine.sudo().search_count([
    ("has_discrepancy", "=", True),
    ("resolved", "=", False),
])
got = Dashboard.sudo()._count_stock_discrepancies_open()
ok = (got == expected)
print("  expected:", expected, " got:", got)
print("T407:", "PASS" if ok else "FAIL")
results["T407"] = ok


# ============================================================
print()
print("=" * 72)
print("T408 - _count_repair_orders_open uses _NON_TERMINAL_STATES")
print("=" * 72)
non_terminal = ("open", "diagnosed", "quoted", "approved", "in_progress")
expected = Repair.sudo().search_count([("state", "in", non_terminal)])
got = Dashboard.sudo()._count_repair_orders_open()
ok = (got == expected)
print("  expected:", expected, " got:", got)
print("T408:", "PASS" if ok else "FAIL")
results["T408"] = ok


# ============================================================
print()
print("=" * 72)
print("T409 - _count_incidents_open excludes resolved_* + cancelled")
print("=" * 72)
terminal = (
    "resolved_recovered", "resolved_writeoff",
    "resolved_claim", "cancelled")
expected = Incident.sudo().search_count([("state", "not in", terminal)])
got = Dashboard.sudo()._count_incidents_open()
ok = (got == expected)
print("  expected:", expected, " got:", got)
print("T409:", "PASS" if ok else "FAIL")
results["T409"] = ok


# ============================================================
print()
print("=" * 72)
print("T410 - _count_high_impact_30d window: 35-day line NOT counted")
print("=" * 72)
# Need a high-impact category to seed lines that compute as
# is_high_impact=True. Find or create one.
hi_cat = Category.sudo().search([("is_high_impact", "=", True)], limit=1)
assert hi_cat, "Need at least one high-impact equipment category seeded"

# Pull two active units in that category.
hi_units = Unit.sudo().search([
    ("equipment_category_id", "=", hi_cat.id),
    ("state", "in", ("active", "reserved", "maintenance")),
], limit=2)
assert len(hi_units) >= 2, (
    "Need >=2 units in a high-impact category to seed T410; got %d"
    % len(hi_units))

baseline = Dashboard.sudo()._count_high_impact_30d()

# Create an ad-hoc stock take in_progress so we can attach lines.
take_t410 = StockTake.sudo().create({"session_type": "ad_hoc"})
take_t410.action_start()

# Attach two lines via the model directly. Set physical_condition=damaged
# to force has_discrepancy=True (a high-impact damaged line is a
# high-impact discrepancy).
line_recent = StockLine.sudo().create({
    "stock_take_id": take_t410.id,
    "unit_id": hi_units[0].id,
    "expected_state": hi_units[0].state,
    "expected_location": hi_units[0].workshop_location or "",
})
line_recent.action_attest(
    found_state=hi_units[0].state,
    found_location=hi_units[0].workshop_location or "",
    physical_condition="damaged",
)

line_old = StockLine.sudo().create({
    "stock_take_id": take_t410.id,
    "unit_id": hi_units[1].id,
    "expected_state": hi_units[1].state,
    "expected_location": hi_units[1].workshop_location or "",
})
line_old.action_attest(
    found_state=hi_units[1].state,
    found_location=hi_units[1].workshop_location or "",
    physical_condition="damaged",
)

# Backdate the second line to 35 days ago — must be excluded.
cutoff_35d = datetime.utcnow() - timedelta(days=35)
env.cr.execute(
    "UPDATE neon_equipment_stock_take_line SET create_date = %s WHERE id = %s",
    (cutoff_35d, line_old.id),
)
line_recent.invalidate_recordset()
line_old.invalidate_recordset()

# Sanity — both must compute as high-impact discrepancies.
assert line_recent.is_high_impact, "line_recent should be high-impact"
assert line_recent.has_discrepancy, "line_recent should be discrepancy"
assert line_old.is_high_impact, "line_old should be high-impact"
assert line_old.has_discrepancy, "line_old should be discrepancy"

after = Dashboard.sudo()._count_high_impact_30d()
ok = (after - baseline == 1)
print("  baseline:", baseline, " after +1 recent (30d) +1 backdated (35d):",
      after, "(want baseline+1)")
print("T410:", "PASS" if ok else "FAIL")
results["T410"] = ok


# ============================================================
print()
print("=" * 72)
print("T411 - get_dashboard_data wire shape (10 keys + last_updated)")
print("=" * 72)
data = Dashboard.sudo().get_dashboard_data()
expected_keys = {
    "active_units", "units_out", "reservations_next_7days",
    "pending_transfers", "late_returns",
    "equipment_conflicts_open", "stock_discrepancies_open",
    "repair_orders_open", "incidents_open", "high_impact_30d",
    "last_updated",
}
got_keys = set(data.keys())
shape_ok = (got_keys == expected_keys)
# Each tile sub-dict must have value + action_id (last_updated is
# a string, not a sub-dict).
tile_keys = expected_keys - {"last_updated"}
sub_ok = all(
    isinstance(data[k], dict)
    and "value" in data[k]
    and "action_id" in data[k]
    and isinstance(data[k]["value"], int)
    and isinstance(data[k]["action_id"], int)
    for k in tile_keys
)
last_ok = bool(
    isinstance(data.get("last_updated"), str) and data["last_updated"])
ok = bool(shape_ok and sub_ok and last_ok)
missing = expected_keys - got_keys
extra = got_keys - expected_keys
print("  keys ok:", shape_ok,
      " missing:", sorted(missing), " extra:", sorted(extra))
print("  tile sub-dict shape ok:", sub_ok)
print("  last_updated:", data.get("last_updated"))
print("T411:", "PASS" if ok else "FAIL")
results["T411"] = ok


# ============================================================
print()
print("=" * 72)
print("T412 - every action_id resolves to a valid ir.actions.act_window")
print("=" * 72)
unresolved = []
for k in tile_keys:
    aid = data[k]["action_id"]
    act = ActWindow.sudo().browse(aid)
    if not act.exists():
        unresolved.append((k, aid))
ok = not unresolved
print("  resolved:", len(tile_keys) - len(unresolved), "/", len(tile_keys))
if unresolved:
    print("  unresolved:", unresolved)
print("T412:", "PASS" if ok else "FAIL")
results["T412"] = ok


# ============================================================
print()
print("=" * 72)
print("T413 - AccessError on get_dashboard_data for crew tier")
print("=" * 72)
try:
    env["neon.equipment.dashboard"].with_user(
        crew_user).get_dashboard_data()
    raised = None
except AccessError as e:
    raised = e
except Exception as e:  # noqa: BLE001
    raised = e
ok = isinstance(raised, AccessError)
print("  raised:", type(raised).__name__ if raised else None,
      " msg:", (str(raised) or "")[:120])
print("T413:", "PASS" if ok else "FAIL")
results["T413"] = ok


# ============================================================
print()
print("=" * 72)
print("T414 - Manager passes (returns dict)")
print("=" * 72)
try:
    data_mgr = env["neon.equipment.dashboard"].with_user(
        manager).get_dashboard_data()
    err = None
except Exception as e:  # noqa: BLE001
    data_mgr = None
    err = e
ok = (err is None and isinstance(data_mgr, dict)
      and "active_units" in data_mgr)
print("  err:", type(err).__name__ if err else None,
      " keys:", sorted(data_mgr.keys())[:3] if data_mgr else None)
print("T414:", "PASS" if ok else "FAIL")
results["T414"] = ok


# ============================================================
print()
print("=" * 72)
print("T415 - Crew Leader passes (returns dict)")
print("=" * 72)
try:
    data_lead = env["neon.equipment.dashboard"].with_user(
        lead).get_dashboard_data()
    err = None
except Exception as e:  # noqa: BLE001
    data_lead = None
    err = e
ok = (err is None and isinstance(data_lead, dict)
      and "active_units" in data_lead)
print("  err:", type(err).__name__ if err else None,
      " keys:", sorted(data_lead.keys())[:3] if data_lead else None)
print("T415:", "PASS" if ok else "FAIL")
results["T415"] = ok


# ============================================================
print()
print("=" * 72)
print("T416 - Other non-allowed user blocked")
print("=" * 72)
try:
    env["neon.equipment.dashboard"].with_user(
        other_user).get_dashboard_data()
    raised = None
except AccessError as e:
    raised = e
except Exception as e:  # noqa: BLE001
    raised = e
ok = isinstance(raised, AccessError)
print("  raised:", type(raised).__name__ if raised else None,
      " msg:", (str(raised) or "")[:120])
print("T416:", "PASS" if ok else "FAIL")
results["T416"] = ok


# ============================================================
print()
print("=" * 72)
print("T417 - Server-action wrapper .run() as manager — returns dict")
print("=" * 72)
server_action = env.ref(
    "neon_jobs.action_workshop_dashboard_server")
ctx_mgr = {
    "active_id": server_action.id,
    "active_model": "ir.actions.server",
}
try:
    res_mgr = server_action.with_user(manager).with_context(
        **ctx_mgr).run()
    err = None
except Exception as e:  # noqa: BLE001
    res_mgr = None
    err = e
ok = (err is None and isinstance(res_mgr, dict)
      and res_mgr.get("type") == "ir.actions.client"
      and res_mgr.get("tag") == "neon_workshop_dashboard")
print("  err:", type(err).__name__ if err else None,
      " result.type:", (res_mgr or {}).get("type"),
      " tag:", (res_mgr or {}).get("tag"))
print("T417:", "PASS" if ok else "FAIL")
results["T417"] = ok


# ============================================================
print()
print("=" * 72)
print("T418 - Server-action wrapper .run() as crew — AccessError")
print("=" * 72)
try:
    server_action.with_user(crew_user).with_context(
        active_id=server_action.id,
        active_model="ir.actions.server").run()
    raised = None
except AccessError as e:
    raised = e
except Exception as e:  # noqa: BLE001
    raised = e
ok = isinstance(raised, AccessError)
print("  raised:", type(raised).__name__ if raised else None,
      " msg:", (str(raised) or "")[:120])
print("T418:", "PASS" if ok else "FAIL")
results["T418"] = ok


# ============================================================
print()
print("=" * 72)
print("T419 - Server-action wrapper .run() as crew_leader — returns dict")
print("=" * 72)
try:
    res_lead = server_action.with_user(lead).with_context(
        active_id=server_action.id,
        active_model="ir.actions.server").run()
    err = None
except Exception as e:  # noqa: BLE001
    res_lead = None
    err = e
ok = (err is None and isinstance(res_lead, dict)
      and res_lead.get("type") == "ir.actions.client"
      and res_lead.get("tag") == "neon_workshop_dashboard")
print("  err:", type(err).__name__ if err else None,
      " result.type:", (res_lead or {}).get("type"),
      " tag:", (res_lead or {}).get("tag"))
print("T419:", "PASS" if ok else "FAIL")
results["T419"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = [f"T{i}" for i in range(400, 420)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
