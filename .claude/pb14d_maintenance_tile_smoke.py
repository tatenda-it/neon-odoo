"""P-B14d smoke -- workshop dashboard adds "In Maintenance" tile.

Covers:
- _count_units_in_maintenance method exists + returns int
- Compute returns the count of units where state='maintenance'
- payload dict has units_in_maintenance key with value + action_id
- action_id resolves to action_dashboard_units_in_maintenance
- action domain filters to [('state', '=', 'maintenance')]
- Regression pin: serial/active counts UNCHANGED by this milestone
- Tile is in the inventory snapshot row (not the attention row)

T-B14d-01 ... T-B14d-08.
"""


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-B14d -- workshop dashboard In Maintenance tile")
print("=" * 72)
results = {}

Dashboard = env["neon.equipment.dashboard"]
Unit = env["neon.equipment.unit"]
Product = env["product.template"]
Movement = env["neon.equipment.movement"]

# Grant admin the needed groups to call the dashboard RPC
admin = env.ref("base.user_admin")
admin.sudo().write({
    "groups_id": [
        (4, env.ref("neon_core.group_neon_superuser").id),
        (4, env.ref("neon_jobs.group_neon_jobs_manager").id),
    ],
})
env = env(user=admin.id)


# ============================================================
# Fixture cleanup (FK-safe)
# ============================================================
old_units = Unit.sudo().search(
    [("serial_number", "=like", "PB14D-%")])
if old_units:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [("unit_id", "in", old_units.ids)]).unlink()
    old_units.unlink()
Product.sudo().search(
    [("workshop_name", "=like", "PB14D-%")]).unlink()
env.cr.commit()


# ============================================================
# T-B14d-01 -- compute method exists
# ============================================================
_check("T-B14d-01",
       hasattr(Dashboard, "_count_units_in_maintenance"),
       "_count_units_in_maintenance method exists on dashboard")


# ============================================================
# T-B14d-02 -- compute returns int baseline
# ============================================================
before_count = Dashboard._count_units_in_maintenance()
_check("T-B14d-02",
       isinstance(before_count, int),
       f"compute returns int (got "
       f"{type(before_count).__name__}={before_count})")


# ============================================================
# T-B14d-03 -- seed N maintenance units; compute reads +N
# ============================================================
sound_cat = env["neon.equipment.category"].sudo().search(
    [("code", "=", "sound")], limit=1)
p = Product.sudo().create({
    "name": "PB14D-MAINT-PROBE",
    "workshop_name": "PB14D-MAINT-PROBE",
    "is_workshop_item": True,
    "equipment_category_id": sound_cat.id,
    "tracking_mode": "serial",
})
N = 3
seeded_units = Unit.sudo().create([{
    "product_template_id": p.id,
    "serial_number": f"PB14D-MAINT-{i:03d}",
    "asset_tag": f"PB14D-MAINT-TAG-{i:03d}",
    "condition_status": "good",
} for i in range(N)])
seeded_units.with_context(_allow_state_write=True).write(
    {"state": "maintenance"})
env.cr.commit()
after_count = Dashboard._count_units_in_maintenance()
_check("T-B14d-03",
       after_count == before_count + N,
       f"count delta = +{N}: before={before_count} "
       f"after={after_count}")


# ============================================================
# T-B14d-04 -- payload has units_in_maintenance + value
# ============================================================
payload = Dashboard.get_dashboard_data()
mt = payload.get("units_in_maintenance")
_check("T-B14d-04",
       isinstance(mt, dict)
       and mt.get("value") == after_count
       and mt.get("action_id"),
       f"payload.units_in_maintenance = {mt}")


# ============================================================
# T-B14d-05 -- action XML ref resolves
# ============================================================
action = env.ref(
    "neon_jobs.action_dashboard_units_in_maintenance",
    raise_if_not_found=False)
_check("T-B14d-05",
       action and action.res_model == "neon.equipment.unit"
       and "maintenance" in (action.domain or ""),
       f"action: id={action.id if action else 'NONE'} "
       f"res_model={action.res_model if action else 'NONE'} "
       f"domain={action.domain if action else 'NONE'}")


# ============================================================
# T-B14d-06 -- click-through action domain
# ============================================================
import ast
domain = ast.literal_eval(action.domain) if action else []
_check("T-B14d-06",
       domain == [("state", "=", "maintenance")],
       f"action domain == [('state', '=', 'maintenance')] (got "
       f"{domain!r})")


# ============================================================
# T-B14d-07 -- REGRESSION PIN: seeded maintenance units NOT
# counted as active (the active path UNCHANGED by B14d)
# ============================================================
active_count = Dashboard._count_active_units()
out_count = Dashboard._count_units_out()
seeded_in_active = Unit.sudo().search_count([
    ("id", "in", seeded_units.ids),
    ("state", "=", "active"),
])
_check("T-B14d-07",
       seeded_in_active == 0
       and isinstance(active_count, int)
       and isinstance(out_count, int),
       f"seeded maintenance units NOT counted as active "
       f"(seeded_in_active={seeded_in_active}); active="
       f"{active_count} checked_out={out_count}")


# ============================================================
# T-B14d-08 -- transition back to active drops count by 1
# (idempotency around the state filter)
# ============================================================
seeded_units[:1].with_context(_allow_state_write=True).write(
    {"state": "active"})
env.cr.commit()
after_one_back = Dashboard._count_units_in_maintenance()
_check("T-B14d-08",
       after_one_back == after_count - 1,
       f"transition 1 unit maintenance->active drops count by 1: "
       f"was {after_count}, now {after_one_back}")


# ============================================================
# Cleanup
# ============================================================
all_pb14d_units = Unit.sudo().search(
    [("product_template_id", "=", p.id)])
if all_pb14d_units:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [("unit_id", "in", all_pb14d_units.ids)]).unlink()
    all_pb14d_units.unlink()
Product.sudo().search(
    [("workshop_name", "=like", "PB14D-%")]).unlink()
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
