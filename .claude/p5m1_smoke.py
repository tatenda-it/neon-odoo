"""P5.M1 Sub-task B — equipment register foundation smoke.

T250 9 equipment categories seeded with correct codes + tracking
T251 product.template extension fields present and queryable
T252 neon.equipment.unit model exists with 8-state machine + mixin
T253 product.template tracking_mode inherits from category default
T254 neon.equipment.unit name compute (workshop_name + serial)
T255 UNIQUE constraints on unit (serial-per-product + asset_tag)
T256 Workshop menu structure resolves (Workshop > Equipment > Units|Categories)
T257 action.centre.mixin inheritance works on equipment.unit
"""
from odoo.exceptions import ValidationError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Category = env["neon.equipment.category"]
Unit = env["neon.equipment.unit"]
Product = env["product.template"]

# Cleanup any prior P5M1 test fixtures
Product.sudo().search([("name", "like", "P5M1_TEST%")]).unlink()
env.cr.commit()


# ============================================================
print()
print("=" * 72)
print("T250 - 9 equipment categories seeded with correct codes")
print("=" * 72)
expected_codes = {
    "sound", "visual", "lighting", "cabling", "laptops",
    "staging", "dance_floor", "effects", "trussing",
}
expected_tracking = {
    "sound": "serial", "visual": "serial", "lighting": "serial",
    "laptops": "serial", "effects": "serial",
    "cabling": "quantity", "staging": "quantity",
    "dance_floor": "quantity", "trussing": "quantity",
}
all_cats = Category.search([])
codes = set(all_cats.mapped("code"))
print("  total categories:", len(all_cats), "(want >= 9)")
print("  codes:", sorted(codes))
tracking_correct = all(
    Category.search([("code", "=", c)], limit=1).default_tracking == t
    for c, t in expected_tracking.items()
)
ok = expected_codes.issubset(codes) and tracking_correct
print("  expected codes present:", expected_codes.issubset(codes))
print("  default_tracking correct:", tracking_correct)
print("T250:", "PASS" if ok else "FAIL")
results["T250"] = ok


# ============================================================
print()
print("=" * 72)
print("T251 - product.template extension fields present")
print("=" * 72)
expected_fields = {
    "is_workshop_item", "equipment_category_id", "tracking_mode",
    "workshop_name", "equipment_unit_ids",
    "total_units", "available_units",
}
present = expected_fields.intersection(Product._fields.keys())
ok = present == expected_fields
missing = expected_fields - present
print("  expected fields:", sorted(expected_fields))
print("  missing:", sorted(missing) or "(none)")
print("T251:", "PASS" if ok else "FAIL")
results["T251"] = ok


# ============================================================
print()
print("=" * 72)
print("T252 - neon.equipment.unit model exists + 8 states + mixin")
print("=" * 72)
state_field = Unit._fields["state"]
states = [s[0] for s in state_field.selection]
print("  states:", states)
expected_states = {
    "draft", "active", "reserved", "checked_out",
    "returned", "maintenance", "damaged", "decommissioned",
}
inherits = set(Unit._inherit) if isinstance(Unit._inherit, list) else {Unit._inherit}
print("  inheritance:", inherits)
ok = (
    set(states) == expected_states
    and "action.centre.mixin" in inherits
    and "mail.thread" in inherits
)
print("T252:", "PASS" if ok else "FAIL")
results["T252"] = ok


# ============================================================
print()
print("=" * 72)
print("T253 - product.template tracking_mode inherits from category")
print("=" * 72)
sound_cat = env.ref("neon_jobs.equipment_category_sound")
cabling_cat = env.ref("neon_jobs.equipment_category_cabling")
p_serial = Product.sudo().create({
    "name": "P5M1_TEST Sound Mixer",
    "is_workshop_item": True,
    "equipment_category_id": sound_cat.id,
})
p_bulk = Product.sudo().create({
    "name": "P5M1_TEST XLR Cables",
    "is_workshop_item": True,
    "equipment_category_id": cabling_cat.id,
})
ok = (
    p_serial.tracking_mode == "serial"
    and p_bulk.tracking_mode == "quantity"
)
print("  Sound product tracking:", p_serial.tracking_mode, "(want serial)")
print("  Cabling product tracking:", p_bulk.tracking_mode, "(want quantity)")
print("T253:", "PASS" if ok else "FAIL")
results["T253"] = ok


# ============================================================
print()
print("=" * 72)
print("T254 - equipment.unit name compute (workshop_name + serial)")
print("=" * 72)
p_serial.workshop_name = "P5M1_TEST QU16"
u1 = Unit.sudo().create({
    "product_template_id": p_serial.id,
    "serial_number": "NL2",
    "state": "active",
})
u2 = Unit.sudo().create({
    "product_template_id": p_serial.id,
    "asset_tag": "AC-014",
    "state": "active",
})
print("  with serial:    name =", repr(u1.name))
print("  with asset_tag: name =", repr(u2.name))
ok = (
    u1.name == "P5M1_TEST QU16 #NL2"
    and u2.name == "P5M1_TEST QU16 #AC-014"
)
print("T254:", "PASS" if ok else "FAIL")
results["T254"] = ok


# ============================================================
print()
print("=" * 72)
print("T255 - UNIQUE constraints on neon.equipment.unit")
print("=" * 72)
# Inspect the model's _sql_constraints declaratively rather than
# trying to round-trip writes-then-IntegrityError-then-rollback
# (the rollback resets the env.cr which wipes the in-progress
# test fixtures). The constraint set IS the contract.
constraint_keys = {k for k, sql, msg in Unit._sql_constraints}
expected_constraints = {"unique_serial_per_product", "unique_asset_tag"}
constraint_sql = {k: sql for k, sql, msg in Unit._sql_constraints}
print("  declared _sql_constraints:", sorted(constraint_keys))
print("  unique_serial_per_product sql:",
      constraint_sql.get("unique_serial_per_product"))
print("  unique_asset_tag sql:",
      constraint_sql.get("unique_asset_tag"))
ok = expected_constraints.issubset(constraint_keys)
# Also verify the constraints actually landed in Postgres by
# querying pg_constraint via the cursor.
env.cr.execute("""
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'neon_equipment_unit'::regclass
    AND contype = 'u'
""")
pg_constraints = {row[0] for row in env.cr.fetchall()}
print("  pg_constraint rows (UNIQUE on table):",
      sorted(pg_constraints))
ok_pg = any("unique_serial_per_product" in c for c in pg_constraints) \
    and any("unique_asset_tag" in c for c in pg_constraints)
print("  postgres has both unique indexes:", ok_pg)
ok = ok and ok_pg
print("T255:", "PASS" if ok else "FAIL")
results["T255"] = ok


# ============================================================
print()
print("=" * 72)
print("T256 - Workshop menu structure resolves")
print("=" * 72)
m_root = env.ref("neon_jobs.menu_workshop_root", raise_if_not_found=False)
m_eq = env.ref("neon_jobs.menu_workshop_equipment", raise_if_not_found=False)
m_units = env.ref("neon_jobs.menu_workshop_equipment_units", raise_if_not_found=False)
m_cats = env.ref("neon_jobs.menu_workshop_equipment_categories", raise_if_not_found=False)
print("  Workshop root:", m_root and m_root.name)
print("  Equipment parent:", m_eq and m_eq.name)
print("  Units child:", m_units and m_units.name)
print("  Categories child:", m_cats and m_cats.name)
ok = bool(m_root and m_eq and m_units and m_cats)
print("T256:", "PASS" if ok else "FAIL")
results["T256"] = ok


# ============================================================
print()
print("=" * 72)
print("T257 - action.centre.mixin inheritance works on equipment.unit")
print("=" * 72)
# Calling a mixin method as a smoke test of inheritance — without
# any P5 triggers configured yet, the call should return cleanly
# (no item created because no trigger.config for a workshop trigger).
helpers_present = (
    hasattr(u1, "_action_centre_create_item")
    and hasattr(u1, "_action_centre_close_items")
    and hasattr(u1, "_action_centre_chatter_note")
)
print("  mixin helpers callable on unit:", helpers_present)
# Try calling — should silently no-op (no config registered for
# a workshop_repair / workshop_due trigger yet).
no_op_call = True
try:
    result = u1.sudo()._action_centre_create_item("workshop_repair_test")
    # Expected: empty browse() because no trigger.config exists
    no_op_call = not result  # empty recordset is falsy
except Exception as e:
    no_op_call = False
    print("  mixin call raised:", type(e).__name__, str(e)[:80])
ok = helpers_present and no_op_call
print("  no-op call returned empty:", no_op_call)
print("T257:", "PASS" if ok else "FAIL")
results["T257"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T250", "T251", "T252", "T253", "T254", "T255", "T256", "T257"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()  # don't persist the test fixtures
