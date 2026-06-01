"""P-B14c smoke -- quantity_on_hand field + B2 availability branch
+ back-fill script.

Covers:
- product.template.quantity_on_hand exists, default 0, Integer
- B2 SERIAL path UNCHANGED (regression pin)
- B2 QUANTITY path reads product.quantity_on_hand
- B2 BATCH path uses the same branch as quantity
- quantity_on_hand=50 + required=30 -> no deficit
- quantity_on_hand=50 + required=80 -> deficit_qty=30
- quantity_on_hand=0 + required=10 -> deficit_qty=10 (was 9 with
  the old len(units)=1 model)
- hard-unavailable unit blocks the whole quantity bucket
- back-fill parses legacy_qty=N idempotently
- back-fill dry-run writes nothing
- back-fill force=False skips already-populated products
- back-fill MAX-wins on disagreement

T-B14c-01 ... T-B14c-24.
"""
from datetime import date, datetime, time, timedelta


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-B14c -- quantity_on_hand field + B2 branch")
print("=" * 72)
results = {}

Cat = env["neon.equipment.category"]
Product = env["product.template"]
Unit = env["neon.equipment.unit"]
Movement = env["neon.equipment.movement"]
Partner = env["res.partner"]
Job = env["commercial.job"]
EventJob = env["commercial.event.job"]
Line = env["commercial.event.job.equipment.line"]
Conflict = env["neon.equipment.conflict"]

from odoo.addons.neon_jobs.models.neon_equipment_conflict import (
    ConflictEngine,
)
from odoo.addons.neon_jobs.scripts import (
    backfill_quantity_on_hand,
)


# ============================================================
# Fixture cleanup (FK-safe order: conflicts -> events -> units
# -> products)
# ============================================================
old_products = Product.sudo().search(
    [("workshop_name", "=like", "PB14C-%")])
if old_products:
    # Conflicts referencing these products
    Conflict.sudo().search([
        ("line_ids.product_template_id", "in",
         old_products.ids),
    ]).unlink()
old_events = EventJob.sudo().search(
    [("name", "=like", "PB14C EVT%")])
if old_events:
    old_events.with_context(_allow_state_write=True).write(
        {"state": "cancelled"})
    old_events.unlink()
Job.sudo().search([("name", "=like", "PB14C JOB%")]).unlink()
old_units = Unit.sudo().search(
    [("serial_number", "=like", "PB14C-%")])
if old_units:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [("unit_id", "in", old_units.ids)]).unlink()
    old_units.unlink()
old_units_q = Unit.sudo().search(
    [("product_template_id.workshop_name", "=like", "PB14C-%")])
if old_units_q:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [("unit_id", "in", old_units_q.ids)]).unlink()
    old_units_q.unlink()
Product.sudo().search(
    [("workshop_name", "=like", "PB14C-%")]).unlink()
env.cr.commit()


# ============================================================
# T-B14c-01..03 -- field surface
# ============================================================
_check("T-B14c-01",
       "quantity_on_hand" in Product._fields,
       "product.template.quantity_on_hand field present")
_check("T-B14c-02",
       Product._fields["quantity_on_hand"].type == "integer",
       f"field type = Integer (got {Product._fields['quantity_on_hand'].type})")
new_p = Product.sudo().create({
    "name": "PB14C-PROBE-DEFAULT",
    "is_workshop_item": True,
})
_check("T-B14c-03",
       new_p.quantity_on_hand == 0,
       f"default = 0 (got {new_p.quantity_on_hand})")
new_p.unlink()


# ============================================================
# Fixtures for B2 tests
# ============================================================
partner = Partner.sudo().search([], limit=1)
venue = Partner.sudo().search([("is_venue", "=", True)], limit=1)
today = date.today()
sound_cat = Cat.sudo().search([("code", "=", "sound")], limit=1)
cabling_cat = Cat.sudo().search([("code", "=", "cabling")], limit=1)

# Serial probe product (5 units owned)
p_serial = Product.sudo().create({
    "name": "PB14C-SERIAL-MIC",
    "workshop_name": "PB14C-SERIAL-MIC",
    "is_workshop_item": True,
    "equipment_category_id": sound_cat.id,
    "tracking_mode": "serial",
})
serial_units = Unit.sudo().create([{
    "product_template_id": p_serial.id,
    "serial_number": f"PB14C-SER-{i:03d}",
    "asset_tag": f"PB14C-TAG-{i:03d}",
    "condition_status": "good",
} for i in range(5)])

# Quantity probe product (1 unit row, quantity_on_hand=50)
p_qty = Product.sudo().create({
    "name": "PB14C-QTY-CABLE",
    "workshop_name": "PB14C-QTY-CABLE",
    "is_workshop_item": True,
    "equipment_category_id": cabling_cat.id,
    "tracking_mode": "quantity",
    "quantity_on_hand": 50,
})
qty_unit = Unit.sudo().create({
    "product_template_id": p_qty.id,
    "condition_status": "good",
    "notes": "legacy_qty=50; legacy_id=999",
})

# Quantity probe with quantity_on_hand=0 (legacy never set)
p_qty_zero = Product.sudo().create({
    "name": "PB14C-QTY-EMPTY",
    "workshop_name": "PB14C-QTY-EMPTY",
    "is_workshop_item": True,
    "equipment_category_id": cabling_cat.id,
    "tracking_mode": "quantity",
    "quantity_on_hand": 0,
})
qty_zero_unit = Unit.sudo().create({
    "product_template_id": p_qty_zero.id,
    "condition_status": "good",
})

# Batch probe (uses same B2 branch as quantity)
p_batch = Product.sudo().create({
    "name": "PB14C-BATCH-FIXTURE",
    "workshop_name": "PB14C-BATCH-FIXTURE",
    "is_workshop_item": True,
    "equipment_category_id": cabling_cat.id,
    "tracking_mode": "batch",
    "quantity_on_hand": 30,
})
batch_unit = Unit.sudo().create({
    "product_template_id": p_batch.id,
    "batch_code": "PB14C-BATCH-001",
    "condition_status": "good",
})
env.cr.commit()


# ============================================================
# T-B14c-04 -- B2 SERIAL path unchanged (regression pin)
# ============================================================
engine = ConflictEngine(env)
avail_serial = engine._available_for_product(p_serial.id)
_check("T-B14c-04",
       avail_serial == 5,
       f"serial path unchanged: 5 units owned -> available=5 "
       f"(got {avail_serial})")


# ============================================================
# T-B14c-05 -- B2 QUANTITY path reads quantity_on_hand
# ============================================================
avail_qty = engine._available_for_product(p_qty.id)
_check("T-B14c-05",
       avail_qty == 50,
       f"quantity path reads quantity_on_hand=50 "
       f"(got {avail_qty})")


# ============================================================
# T-B14c-06 -- B2 BATCH path same as quantity
# ============================================================
avail_batch = engine._available_for_product(p_batch.id)
_check("T-B14c-06",
       avail_batch == 30,
       f"batch path reads quantity_on_hand=30 (got {avail_batch})")


# ============================================================
# T-B14c-07 -- B2 quantity_on_hand=0 with units present -> 0
# (NOT 1 from len(units) -- the pre-B14c bug)
# ============================================================
avail_qty_zero = engine._available_for_product(p_qty_zero.id)
_check("T-B14c-07",
       avail_qty_zero == 0,
       f"quantity_on_hand=0 -> available=0 (pre-B14c reported 1 "
       f"from len(units); got {avail_qty_zero})")


# ============================================================
# T-B14c-08 -- hard-unavailable unit blocks the whole bucket
# ============================================================
qty_unit.sudo().with_context(_allow_state_write=True).write(
    {"state": "transferred"})
avail_blocked = engine._available_for_product(p_qty.id)
_check("T-B14c-08",
       avail_blocked == 0,
       f"hard-unavailable unit -> entire bucket=0 "
       f"(got {avail_blocked})")
# restore
qty_unit.sudo().with_context(_allow_state_write=True).write(
    {"state": "active"})
env.cr.commit()


# ============================================================
# T-B14c-09 -- non-good condition also blocks
# ============================================================
qty_unit.sudo().with_context(_allow_state_write=True).write(
    {"condition_status": "needs_repair"})
avail_repair = engine._available_for_product(p_qty.id)
_check("T-B14c-09",
       avail_repair == 0,
       f"non-good condition -> bucket=0 (got {avail_repair})")
qty_unit.sudo().with_context(_allow_state_write=True).write(
    {"condition_status": "good"})
env.cr.commit()


# ============================================================
# T-B14c-10..13 -- end-to-end conflict computation with quantity
# ============================================================
mA = Job.sudo().create({
    "name": "PB14C JOB A", "partner_id": partner.id,
    "state": "active", "event_date": today,
    **({"venue_id": venue.id} if venue else {}),
})
ev = EventJob.sudo().create({
    "name": "PB14C EVT A",
    "commercial_job_id": mA.id, "partner_id": partner.id,
    "load_in_start": datetime.combine(today, time(9, 0)),
    "load_out_end": datetime.combine(today, time(14, 0)),
})
ev.with_context(_allow_state_write=True).write(
    {"state": "planning"})

# Demand 30 cables (out of 50 stocked) -> NO deficit
Line.sudo().create({
    "event_job_id": ev.id,
    "product_template_id": p_qty.id,
    "quantity_planned": 30,
})
ev.flush_recordset()
Line.sudo().flush_model()
env.cr.commit()
conf = engine.run_for_event(ev, trigger_reason="manual")
qty_line = conf.line_ids.filtered(
    lambda l: l.product_template_id.id == p_qty.id)
_check("T-B14c-10",
       qty_line and qty_line.required_qty == 30
       and qty_line.available_qty == 50
       and qty_line.deficit_qty == 0
       and qty_line.status in ("surplus", "below_threshold"),
       f"quantity demand 30 / stock 50 -> no deficit; "
       f"req={qty_line.required_qty} avail={qty_line.available_qty} "
       f"deficit={qty_line.deficit_qty} status={qty_line.status}")

# Now ramp demand to 80 -> deficit 30
Line.sudo().search([
    ("event_job_id", "=", ev.id),
    ("product_template_id", "=", p_qty.id)]
).write({"quantity_planned": 80})
ev.flush_recordset()
Line.sudo().flush_model()
env.cr.commit()
conf2 = engine.run_for_event(ev, trigger_reason="manual")
qty_line2 = conf2.line_ids.filtered(
    lambda l: l.product_template_id.id == p_qty.id)
_check("T-B14c-11",
       qty_line2 and qty_line2.required_qty == 80
       and qty_line2.available_qty == 50
       and qty_line2.deficit_qty == 30
       and qty_line2.status == "deficit",
       f"quantity demand 80 / stock 50 -> deficit=30; "
       f"req={qty_line2.required_qty} avail={qty_line2.available_qty} "
       f"deficit={qty_line2.deficit_qty} status={qty_line2.status}")

# Demand exactly equal -> zero_margin
Line.sudo().search([
    ("event_job_id", "=", ev.id),
    ("product_template_id", "=", p_qty.id)]
).write({"quantity_planned": 50})
ev.flush_recordset()
Line.sudo().flush_model()
env.cr.commit()
conf3 = engine.run_for_event(ev, trigger_reason="manual")
qty_line3 = conf3.line_ids.filtered(
    lambda l: l.product_template_id.id == p_qty.id)
_check("T-B14c-12",
       qty_line3 and qty_line3.deficit_qty == 0
       and qty_line3.status in ("zero_margin",
                                  "below_threshold"),
       f"demand==stock -> zero_margin; status={qty_line3.status}")


# Pre-B14c contrast: a SERIAL product demand exceeding owned
# still computes correctly (regression pin).
Line.sudo().create({
    "event_job_id": ev.id,
    "product_template_id": p_serial.id,
    "quantity_planned": 7,
})
ev.flush_recordset()
Line.sudo().flush_model()
env.cr.commit()
conf4 = engine.run_for_event(ev, trigger_reason="manual")
serial_line = conf4.line_ids.filtered(
    lambda l: l.product_template_id.id == p_serial.id)
_check("T-B14c-13",
       serial_line and serial_line.required_qty == 7
       and serial_line.available_qty == 5
       and serial_line.deficit_qty == 2,
       f"serial path UNCHANGED: 7 demanded / 5 owned -> "
       f"deficit=2; got req={serial_line.required_qty} "
       f"avail={serial_line.available_qty} "
       f"deficit={serial_line.deficit_qty}")


# ============================================================
# T-B14c-14..16 -- back-fill script: parser
# ============================================================
_check("T-B14c-14",
       backfill_quantity_on_hand._parse_legacy_qty(
           "legacy_qty=42; legacy_id=999") == 42,
       "parser extracts 'legacy_qty=42'")
_check("T-B14c-15",
       backfill_quantity_on_hand._parse_legacy_qty(
           "no qty here") is None,
       "parser returns None when no legacy_qty")
_check("T-B14c-16",
       backfill_quantity_on_hand._parse_legacy_qty(
           "legacy_qty=999; legacy_supplier=X") == 999,
       "parser handles multi-key notes")


# ============================================================
# T-B14c-17..20 -- back-fill end-to-end
# ============================================================
# Setup: p_qty has qty_on_hand=50 already; reset to 0 + notes
# carry legacy_qty=50, then back-fill should set it back to 50
p_qty.sudo().write({"quantity_on_hand": 0})
report_dry = backfill_quantity_on_hand.backfill(
    env, execute=False)
qty_after_dry = Product.sudo().browse(p_qty.id).quantity_on_hand
_check("T-B14c-17",
       qty_after_dry == 0
       and report_dry["dry_run"] is True,
       f"dry-run writes nothing: qty={qty_after_dry} "
       f"dry_run={report_dry['dry_run']}")

# Find our WRITE plan entry
plan_for_pqty = next(
    (p for p in report_dry["plan"]
      if p["product_id"] == p_qty.id), None)
_check("T-B14c-18",
       plan_for_pqty
       and plan_for_pqty["action"] == "WRITE"
       and plan_for_pqty["new_value"] == 50,
       f"plan classifies p_qty as WRITE 50: {plan_for_pqty}")

# Execute
report_exec = backfill_quantity_on_hand.backfill(
    env, execute=True)
qty_after_exec = Product.sudo().browse(p_qty.id).quantity_on_hand
_check("T-B14c-19",
       qty_after_exec == 50
       and report_exec["dry_run"] is False
       and report_exec["by_action"].get("WRITE", 0) >= 1,
       f"execute writes: qty={qty_after_exec} "
       f"by_action={report_exec['by_action']}")

# Idempotent re-run -> NO-OP
report_rerun = backfill_quantity_on_hand.backfill(
    env, execute=True)
qty_after_rerun = Product.sudo().browse(p_qty.id).quantity_on_hand
plan_for_pqty_rerun = next(
    (p for p in report_rerun["plan"]
      if p["product_id"] == p_qty.id), None)
_check("T-B14c-20",
       qty_after_rerun == 50
       and plan_for_pqty_rerun["action"] == "NO-OP",
       f"idempotent re-run: qty={qty_after_rerun} "
       f"action={plan_for_pqty_rerun['action']}")


# ============================================================
# T-B14c-21 -- force=False skips already-populated
# ============================================================
# Set a manual value different from legacy
p_qty.sudo().write({"quantity_on_hand": 99})
report_skip = backfill_quantity_on_hand.backfill(
    env, execute=True, force=False)
qty_after_skip = Product.sudo().browse(p_qty.id).quantity_on_hand
plan_skip = next(
    (p for p in report_skip["plan"]
      if p["product_id"] == p_qty.id), None)
_check("T-B14c-21",
       qty_after_skip == 99
       and plan_skip["action"] == "SKIP"
       and "force=True" in plan_skip["reason"],
       f"force=False protects manual edits: qty={qty_after_skip} "
       f"action={plan_skip['action']} reason="
       f"{plan_skip['reason']!r}")


# ============================================================
# T-B14c-22 -- force=True overwrites
# ============================================================
report_force = backfill_quantity_on_hand.backfill(
    env, execute=True, force=True)
qty_after_force = Product.sudo().browse(p_qty.id).quantity_on_hand
_check("T-B14c-22",
       qty_after_force == 50,
       f"force=True overwrites manual: qty={qty_after_force}")


# ============================================================
# T-B14c-23 -- MAX-wins on disagreement
# ============================================================
# Add a 2nd unit with a different legacy_qty
Unit.sudo().create({
    "product_template_id": p_qty.id,
    "condition_status": "good",
    "notes": "legacy_qty=75; rogue extra row",
})
p_qty.sudo().write({"quantity_on_hand": 0})
report_max = backfill_quantity_on_hand.backfill(
    env, execute=True)
qty_after_max = Product.sudo().browse(p_qty.id).quantity_on_hand
_check("T-B14c-23",
       qty_after_max == 75,
       f"MAX-wins on disagreement: qty_on_hand={qty_after_max} "
       f"(50 vs 75 -> 75)")


# ============================================================
# T-B14c-24 -- product without legacy_qty notes left alone
# ============================================================
# p_qty_zero unit has no notes; back-fill should leave qty=0
qty_zero_after = Product.sudo().browse(
    p_qty_zero.id).quantity_on_hand
plan_zero = next(
    (p for p in report_max["plan"]
      if p["product_id"] == p_qty_zero.id), None)
_check("T-B14c-24",
       qty_zero_after == 0
       and plan_zero["action"] == "SKIP"
       and "no unit" in plan_zero["reason"].lower(),
       f"no legacy_qty -> left alone: qty={qty_zero_after} "
       f"plan={plan_zero}")


# ============================================================
# Cleanup (FK-safe order)
# ============================================================
end_products = Product.sudo().search(
    [("workshop_name", "=like", "PB14C-%")])
if end_products:
    Conflict.sudo().search([
        ("line_ids.product_template_id", "in",
         end_products.ids),
    ]).unlink()
end_events = EventJob.sudo().search(
    [("name", "=like", "PB14C EVT%")])
if end_events:
    end_events.with_context(_allow_state_write=True).write(
        {"state": "cancelled"})
    end_events.unlink()
Job.sudo().search([("name", "=like", "PB14C JOB%")]).unlink()
end_units = Unit.sudo().search(
    [("product_template_id.workshop_name", "=like", "PB14C-%")])
if end_units:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [("unit_id", "in", end_units.ids)]).unlink()
    end_units.unlink()
Product.sudo().search(
    [("workshop_name", "=like", "PB14C-%")]).unlink()
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
