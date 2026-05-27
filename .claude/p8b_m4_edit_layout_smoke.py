"""P8B.M4 smoke -- Edit Layout (per-user hide/reorder).

T8B70-T8B93.

T8B70  is_customized field exists on neon.dashboard, default False
T8B71  get_dashboard_data payload carries is_customized
T8B72  dashboard_update_layout writes order_index + visible
T8B73  dashboard_update_layout sets is_customized=True
T8B74  dashboard_update_layout idempotent (re-apply same -> same state)
T8B75  dashboard_update_layout returns refreshed payload
T8B76  serialized layout reflects new order_index after update
T8B77  mandatory: kpi_cash cannot be hidden (re-flipped visible)
T8B78  mandatory: kpi_ar_overdue cannot be hidden
T8B79  block_alerts cannot be hidden when param False (default)
T8B80  block_alerts CAN be hidden when alerts_block_optional=True
T8B81  non-mandatory block (block_tasks) CAN be hidden
T8B82  dashboard_reset_layout deletes user rows + re-seeds
T8B83  dashboard_reset_layout flips is_customized back to False
T8B84  _accessible_dashboard_types: superuser -> all 5
T8B85  _accessible_dashboard_types: single-variant user -> 1
T8B86  apply_to_all: superuser returns applied for accessible types
T8B87  apply_to_all: copies visible/order for COMMON widget_keys
T8B88  apply_to_all: sets is_customized=True on targets
T8B89  apply_to_all: non-super -> only own type applied, others absent
T8B90  per-user isolation: user A update doesn't touch user B rows
T8B91  reset re-seed restores default size values (large on dominant)
T8B92  update_layout on a variant doesn't affect other variant's rows
T8B93  no new groups owned by neon_dashboard (M1 invariant)
"""
results = {}
print("=" * 72)
print("P8B.M4 -- Edit Layout")
print("=" * 72)

Dashboard = env["neon.dashboard"]
Users = env["res.users"]
UserLayout = env["neon.dashboard.user.layout"]
ICP = env["ir.config_parameter"]
sp = env.cr.savepoint()


def _check(tnum, cond, detail=""):
    results[tnum] = bool(cond)
    print(f"{tnum}: {'PASS' if cond else 'FAIL'} {detail}")


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


# Distinct logins from the browser smoke's p8b_m4_super / p8b_m4_book:
# the browser smoke COMMITS a customised dashboard for its fixtures
# (required for the HTTP session to see them), which would otherwise
# break T8B70b's "fresh dashboard is_customized=False" assertion when
# both run on the same DB. This python smoke rolls back, so its own
# users never persist; keeping the namespaces separate makes the
# default-False assertion deterministic regardless of run order.
u_super = _get_or_make_user("p8b_m4t_super", "neon_core.group_neon_superuser")
u_sales = _get_or_make_user("p8b_m4t_sales", "neon_core.group_neon_sales_rep")
u_lead = _get_or_make_user("p8b_m4t_lead", "neon_core.group_neon_lead_tech")


def _row(dash, key):
    return dash.layout_ids.filtered(lambda l: l.widget_key == key)[:1]


# T8B70 -- field exists.
_check("T8B70",
       "is_customized" in Dashboard._fields
       and Dashboard._fields["is_customized"].type == "boolean")

# Build a director dashboard for the superuser.
dash = Dashboard.sudo().get_or_create_for_user(
    user_id=u_super.id, dashboard_type="director")
_check("T8B70b", dash.is_customized is False, "default False")

# T8B71 -- payload carries is_customized.
data = Dashboard.with_user(u_super).get_dashboard_data(
    dashboard_type="director")
_check("T8B71", "is_customized" in data)

# T8B72/T8B73/T8B75/T8B76 -- update writes + flags + returns + order.
upd = [{"widget_key": "block_tasks", "visible": True, "order_index": 99}]
ret = Dashboard.with_user(u_super).dashboard_update_layout("director", upd)
dash.invalidate_recordset()
tasks_row = _row(dash, "block_tasks")
_check("T8B72", tasks_row and tasks_row.order_index == 99,
       f"order={tasks_row.order_index if tasks_row else None}")
_check("T8B73", dash.is_customized is True)
_check("T8B75", isinstance(ret, dict) and ret.get("is_customized") is True)
ser = [l for l in ret.get("layout", []) if l["widget_key"] == "block_tasks"]
_check("T8B76", ser and ser[0]["order_index"] == 99)

# T8B74 -- idempotent.
ret2 = Dashboard.with_user(u_super).dashboard_update_layout("director", upd)
dash.invalidate_recordset()
_check("T8B74", _row(dash, "block_tasks").order_index == 99)

# T8B77/T8B78 -- kpi mandatory cannot hide.
Dashboard.with_user(u_super).dashboard_update_layout(
    "director", [{"widget_key": "kpi_cash", "visible": False}])
dash.invalidate_recordset()
_check("T8B77", _row(dash, "kpi_cash").visible is True)
Dashboard.with_user(u_super).dashboard_update_layout(
    "director", [{"widget_key": "kpi_ar_overdue", "visible": False}])
dash.invalidate_recordset()
_check("T8B78", _row(dash, "kpi_ar_overdue").visible is True)

# T8B79 -- block_alerts mandatory when param False.
ICP.sudo().set_param("neon_dashboard.alerts_block_optional", "False")
Dashboard.with_user(u_super).dashboard_update_layout(
    "director", [{"widget_key": "block_alerts", "visible": False}])
dash.invalidate_recordset()
_check("T8B79", _row(dash, "block_alerts").visible is True)

# T8B80 -- block_alerts hideable when param True.
ICP.sudo().set_param("neon_dashboard.alerts_block_optional", "True")
Dashboard.with_user(u_super).dashboard_update_layout(
    "director", [{"widget_key": "block_alerts", "visible": False}])
dash.invalidate_recordset()
_check("T8B80", _row(dash, "block_alerts").visible is False)
ICP.sudo().set_param("neon_dashboard.alerts_block_optional", "False")

# T8B81 -- non-mandatory block hideable.
Dashboard.with_user(u_super).dashboard_update_layout(
    "director", [{"widget_key": "block_sales", "visible": False}])
dash.invalidate_recordset()
_check("T8B81", _row(dash, "block_sales").visible is False)

# T8B82/T8B83/T8B91 -- reset deletes + re-seeds + flips flag + sizes.
Dashboard.with_user(u_super).dashboard_reset_layout("director")
dash.invalidate_recordset()
_check("T8B82",
       bool(dash.layout_ids)
       and _row(dash, "block_sales").visible is True
       and _row(dash, "block_tasks").order_index != 99,
       "rows re-seeded to defaults")
_check("T8B83", dash.is_customized is False)
jobs_row = _row(dash, "block_jobs")
_check("T8B91", jobs_row and jobs_row.size == "large",
       f"block_jobs size={jobs_row.size if jobs_row else None}")

# T8B84/T8B85 -- accessible types.
acc_super = Dashboard.with_user(u_super)._accessible_dashboard_types()
_check("T8B84", set(acc_super) == {"director", "sales", "bookkeeper",
                                   "lead_tech", "tech"})
acc_lead = Dashboard.with_user(u_lead)._accessible_dashboard_types()
_check("T8B85", acc_lead == ["lead_tech"], f"{acc_lead}")

# T8B86/T8B87/T8B88 -- apply to all (superuser).
apply_upd = [{"widget_key": "block_tasks", "visible": False,
              "order_index": 50}]
res = Dashboard.with_user(u_super).dashboard_apply_layout_to_all_variants(
    "director", apply_upd)
_check("T8B86",
       res.get("director") == "applied" and res.get("sales") == "applied"
       and res.get("bookkeeper") == "applied", f"{res}")
sales_dash = Dashboard.sudo().get_or_create_for_user(
    user_id=u_super.id, dashboard_type="sales")
sales_tasks = _row(sales_dash, "block_tasks")
_check("T8B87", sales_tasks and sales_tasks.visible is False
       and sales_tasks.order_index == 50, "common widget copied")
_check("T8B88", sales_dash.is_customized is True)

# T8B89 -- non-super apply-to-all: only own type.
res_lead = Dashboard.with_user(u_lead)\
    .dashboard_apply_layout_to_all_variants("lead_tech", [])
_check("T8B89",
       res_lead.get("lead_tech") == "applied"
       and res_lead.get("sales") == "no_access"
       and res_lead.get("director") == "no_access", f"{res_lead}")

# T8B90 -- per-user isolation.
dash_sales_user = Dashboard.sudo().get_or_create_for_user(
    user_id=u_sales.id, dashboard_type="sales")
before = _row(dash_sales_user, "block_tasks").order_index
Dashboard.with_user(u_super).dashboard_update_layout(
    "sales", [{"widget_key": "block_tasks", "order_index": 77}])
dash_sales_user.invalidate_recordset()
after = _row(dash_sales_user, "block_tasks").order_index
_check("T8B90", before == after,
       f"sales-user row untouched by superuser's own sales row "
       f"({before}=={after})")

# T8B92 -- variant isolation for same user.
lead_dash = Dashboard.sudo().get_or_create_for_user(
    user_id=u_super.id, dashboard_type="lead_tech")
lead_tasks_before = _row(lead_dash, "block_tasks").order_index
Dashboard.with_user(u_super).dashboard_update_layout(
    "director", [{"widget_key": "block_tasks", "order_index": 88}])
lead_dash.invalidate_recordset()
_check("T8B92", _row(lead_dash, "block_tasks").order_index
       == lead_tasks_before, "director edit didn't touch lead_tech")

# T8B93 -- no new groups.
owned = env["ir.model.data"].search([
    ("module", "=", "neon_dashboard"), ("model", "=", "res.groups")])
_check("T8B93", len(owned) == 0, f"groups_owned={len(owned)}")

sp.close(rollback=True)
print("=" * 72)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{len(results)} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
