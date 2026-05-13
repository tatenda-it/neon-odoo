"""P4.M3 smoke — Dashboard tile + role-aware filters.

T179 Manager opens Action Centre → search_default_all_open = 1.
T180 Crew Leader → search_default_my_lead_tech_open = 1.
T181 Sales → search_default_my_sales_open = 1.
T182 get_dashboard_tile_items honors limit=5 and ordering.
T183 Dashboard tile excludes done/cancelled items.
T184 Urgency filter domains evaluate without error per role.
T185 can_close compute: manager True; non-assignee non-manager False;
     assignee True.
T186 Filter combinations work via search() with multiple domains.
T187 Dashboard tile empty state: user with no open items → empty
     recordset, dashboard count == 0.
"""
from odoo import fields
from odoo.exceptions import AccessError, UserError


print("=" * 72)
print("SETUP")
print("=" * 72)

sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
crew_leader = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
crew_only = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
print("users: sales=", sales.login, " mgr=", manager.login,
      " lead=", crew_leader.login, " crew=", crew_only.login)

# Clean prior P4M3 fixtures
prior = env["action.centre.item"].sudo().search(
    [("title", "like", "P4M3FIX%")])
print("cleaning", len(prior), "prior items")
prior.unlink()
env.cr.commit()


def _make(title, assignee=None, due=None, state=None, priority="medium",
          item_type="task", user=None):
    Item = env["action.centre.item"]
    if user:
        Item = Item.with_user(user)
    vals = {
        "title": "P4M3FIX " + title,
        "priority": priority,
        "item_type": item_type,
    }
    if assignee:
        vals["primary_assignee_id"] = assignee.id
    if due:
        vals["due_date"] = due
    item = Item.create(vals)
    if state == "in_progress":
        item.with_user(manager).action_mark_in_progress()
    elif state == "done":
        item.with_user(manager).action_mark_done()
    return item


results = {}

# ============================================================
print()
print("=" * 72)
print("T179 - Manager → search_default_all_open")
print("=" * 72)
act = env["action.centre.item"].with_user(
    manager).action_open_action_centre()
ctx = act.get("context", {})
print("  context keys:", sorted(ctx.keys()))
ok = ctx.get("search_default_all_open") == 1
print("T179:", "PASS" if ok else "FAIL")
results["T179"] = ok


# ============================================================
print()
print("=" * 72)
print("T180 - Crew Leader → search_default_my_lead_tech_open")
print("=" * 72)
act = env["action.centre.item"].with_user(
    crew_leader).action_open_action_centre()
ctx = act.get("context", {})
print("  context keys:", sorted(ctx.keys()))
# crew_leader does NOT have manager group, so should hit the lead path
ok = ctx.get("search_default_my_lead_tech_open") == 1 \
    and not ctx.get("search_default_all_open")
print("T180:", "PASS" if ok else "FAIL")
results["T180"] = ok


# ============================================================
print()
print("=" * 72)
print("T181 - Sales → search_default_my_sales_open")
print("=" * 72)
act = env["action.centre.item"].with_user(
    sales).action_open_action_centre()
ctx = act.get("context", {})
print("  context keys:", sorted(ctx.keys()))
ok = ctx.get("search_default_my_sales_open") == 1 \
    and not ctx.get("search_default_my_lead_tech_open") \
    and not ctx.get("search_default_all_open")
print("T181:", "PASS" if ok else "FAIL")
results["T181"] = ok


# ============================================================
print()
print("=" * 72)
print("T182 - get_dashboard_tile_items honors limit + ordering")
print("=" * 72)
# Build 7 items for crew_leader. Mix priorities and due_dates to
# stress the ordering. All assigned to crew_leader.
items = []
now = fields.Datetime.now()
past = fields.Datetime.subtract(now, days=2)
future = fields.Datetime.add(now, days=2)
items.append(_make("T182_a_low_future", assignee=crew_leader,
                    due=future, priority="low"))
items.append(_make("T182_b_high_overdue", assignee=crew_leader,
                    due=past, priority="high"))
items.append(_make("T182_c_urgent_today", assignee=crew_leader,
                    due=now, priority="urgent"))
items.append(_make("T182_d_med_nodate", assignee=crew_leader,
                    priority="medium"))
items.append(_make("T182_e_low_overdue", assignee=crew_leader,
                    due=past, priority="low"))
items.append(_make("T182_f_high_future", assignee=crew_leader,
                    due=future, priority="high"))
items.append(_make("T182_g_urgent_overdue", assignee=crew_leader,
                    due=past, priority="urgent"))
top5 = env["action.centre.item"].with_user(
    crew_leader).get_dashboard_tile_items(limit=5)
print("  top5 titles:", top5.mapped("title"))
ok = len(top5) == 5
# Verify ordering: priority desc, then due_date asc.
# So urgent items come first, then high, then medium, then low.
priorities_seen = top5.mapped("priority")
# First entries should be urgent
ok = ok and priorities_seen[0] == "urgent"
print("  priorities in order:", priorities_seen)
print("T182:", "PASS" if ok else "FAIL")
results["T182"] = ok


# ============================================================
print()
print("=" * 72)
print("T183 - Dashboard tile excludes done/cancelled")
print("=" * 72)
# Close one of crew_leader's items
item_to_close = items[0]  # T182_a
item_to_close.with_user(crew_leader).action_mark_done()
top5_after = env["action.centre.item"].with_user(
    crew_leader).get_dashboard_tile_items(limit=10)
ok = item_to_close not in top5_after \
    and all(it.state in ("open", "in_progress") for it in top5_after)
print("  done item present?", item_to_close in top5_after, "(want False)")
print("  all returned items open/in_progress?",
      all(it.state in ("open", "in_progress") for it in top5_after))
print("T183:", "PASS" if ok else "FAIL")
results["T183"] = ok


# ============================================================
print()
print("=" * 72)
print("T184 - Urgency filter domains evaluate without error")
print("=" * 72)
from datetime import date, timedelta
today = date.today()
today_str = today.strftime("%Y-%m-%d")
week_end = (today + timedelta(days=7)).strftime("%Y-%m-%d 23:59:59")
domains = {
    "overdue": [("due_date", "!=", False),
                ("due_date", "<", today_str),
                ("state", "not in", ("done", "cancelled"))],
    "due_today": [("due_date", ">=", today_str + " 00:00:00"),
                  ("due_date", "<=", today_str + " 23:59:59")],
    "due_this_week": [("due_date", ">=", today_str + " 00:00:00"),
                      ("due_date", "<=", week_end)],
    "high_priority": [("priority", "in", ("high", "urgent"))],
    "my_items_uid": [("primary_assignee_id", "=", crew_leader.id)],
}
ok = True
for name, dom in domains.items():
    for u in (sales, crew_leader, manager):
        try:
            n = env["action.centre.item"].with_user(u).search_count(dom)
            print(f"  {name:18} as {u.login:13}: count={n}")
        except Exception as e:
            print(f"  {name} as {u.login}: FAILED -> {type(e).__name__}: {str(e)[:80]}")
            ok = False
print("T184:", "PASS" if ok else "FAIL")
results["T184"] = ok


# ============================================================
print()
print("=" * 72)
print("T185 - can_close compute matrix")
print("=" * 72)
test_item = _make("T185_item", assignee=crew_leader)
# manager → True
test_item.invalidate_recordset()
mgr_can = test_item.with_user(manager).can_close
# assignee (crew_leader) → True
lead_can = test_item.with_user(crew_leader).can_close
# sales (not assignee, not manager) → False
sales_can = test_item.with_user(sales).can_close
print("  manager can_close:  ", mgr_can, "(want True)")
print("  assignee can_close: ", lead_can, "(want True)")
print("  sales can_close:    ", sales_can, "(want False)")
ok = mgr_can is True and lead_can is True and sales_can is False
print("T185:", "PASS" if ok else "FAIL")
results["T185"] = ok


# ============================================================
print()
print("=" * 72)
print("T186 - Filter combinations evaluate correctly")
print("=" * 72)
# Build a fixture matrix
overdue_dt = fields.Datetime.subtract(now, days=3)
combo_overdue_urgent = _make("T186_overdue_urgent",
                              assignee=crew_leader,
                              due=overdue_dt, priority="urgent")
combo_overdue_low = _make("T186_overdue_low",
                            assignee=crew_leader,
                            due=overdue_dt, priority="low")
combo_future_urgent = _make("T186_future_urgent",
                              assignee=crew_leader,
                              due=future, priority="urgent")
overdue_high_pri = env["action.centre.item"].with_user(crew_leader).search([
    ("due_date", "!=", False),
    ("due_date", "<", today_str),
    ("state", "not in", ("done", "cancelled")),
    ("priority", "in", ("high", "urgent")),
])
ok = (
    combo_overdue_urgent in overdue_high_pri
    and combo_overdue_low not in overdue_high_pri
    and combo_future_urgent not in overdue_high_pri
)
print("  overdue+urgent in combo set?", combo_overdue_urgent in overdue_high_pri)
print("  overdue+low in combo set?   ", combo_overdue_low in overdue_high_pri,
      "(want False)")
print("  future+urgent in combo set? ", combo_future_urgent in overdue_high_pri,
      "(want False)")
print("T186:", "PASS" if ok else "FAIL")
results["T186"] = ok


# ============================================================
print()
print("=" * 72)
print("T187 - Dashboard tile empty state (helper + dashboard create)")
print("=" * 72)
# Phase 1: helper returns empty for a user with no assigned items.
# p2m75_other is crew-tier — it can't access the dashboard but the
# helper itself respects ir.rule + assignee filter and returns [].
other = env["res.users"].search([("login", "=", "p2m75_other")], limit=1)
helper_ok = False
if other:
    other_top = env["action.centre.item"].with_user(
        other).get_dashboard_tile_items(limit=5)
    helper_ok = (len(other_top) == 0)
    print("  helper as p2m75_other (no items): size=",
          len(other_top), "(want 0)")
else:
    print("  helper test SKIP — p2m75_other missing")

# Phase 2: dashboard create + tile count == 0 for a user-tier user
# with no assigned items. We re-purpose 'manager' after temporarily
# unassigning everything they own (then restore via SAVEPOINT-style
# manual undo since odoo shell commits per statement). Cleanest is
# to find or create a dashboard-eligible user with zero items.
#
# Manager has historically been an assignee in the smoke fixtures
# (T163 from p4m1). Reassign manager's items to sales for the
# duration of T187, then restore.
mgr_items = env["action.centre.item"].sudo().search(
    [("primary_assignee_id", "=", manager.id),
     ("state", "in", ("open", "in_progress"))])
print("  manager-assigned open items pre-T187:", len(mgr_items))
# Snapshot for restore
snapshot = [(it.id, it.primary_assignee_id.id) for it in mgr_items]
mgr_items.with_user(manager).write({"primary_assignee_id": sales.id})
# Also clear any escalated_to=manager
esc_items = env["action.centre.item"].sudo().search(
    [("escalated_to_id", "=", manager.id),
     ("state", "in", ("open", "in_progress"))])
esc_snapshot = [(it.id, it.escalated_to_id.id) for it in esc_items]
esc_items.sudo().write({"escalated_to_id": False})

# Now manager has zero items. Open dashboard.
Dashboard = env["commercial.job.dashboard"].with_user(manager)
Dashboard.search([("create_uid", "=", manager.id)]).unlink()
dash = Dashboard.create({})
dash.invalidate_recordset()
dashboard_ok = (
    dash.my_action_items_count == 0
    and not dash.my_action_items_top5
)
print("  dashboard count: ", dash.my_action_items_count, "(want 0)")
print("  dashboard top5 ids:", dash.my_action_items_top5.ids,
      "(want [])")

# Restore
for item_id, assignee_id in snapshot:
    env["action.centre.item"].browse(item_id).sudo().write(
        {"primary_assignee_id": assignee_id})
for item_id, escalated_id in esc_snapshot:
    env["action.centre.item"].browse(item_id).sudo().write(
        {"escalated_to_id": escalated_id})

ok = helper_ok and dashboard_ok
print("T187:", "PASS" if ok else "FAIL")
results["T187"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T179", "T180", "T181", "T182", "T183", "T184", "T185",
         "T186", "T187"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.commit()
