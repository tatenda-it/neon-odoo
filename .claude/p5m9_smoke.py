"""P5.M9 smoke — repair + incident workflows.

T380 create repair_order on damaged unit → state='open', REP-NNNNNN
T381 repair lifecycle: open → diagnosed → quoted → approved → in_progress → completed
T382 completed repair transitions unit maintenance → active
T383 cancellation: manager cancels mid-flow
T384 action_approve blocked for non-manager
T385 action_complete_repair requires actual_cost
T386 create incident → state='open', INC-NNNNNN
T387 incident open → under_investigation → resolved_recovered (unit → active)
T388 incident resolve_writeoff → unit → decommissioned
T389 incident resolve_claim requires insurance_claim_ref
T390 P5.M7 incident_link path now creates real incident
T391 stock_take_line action_open_repair_order
T392 stock_take_line action_open_incident
T393 incident_open Action Centre item fires on incident create
T394 incident_open auto-closes on resolution
T395 repair_stalled cron fires for >7-day open repairs
T396 repair_stalled auto-closes when repair completes
T397 stock_take_unresolved cron fires for >7-day discrepancies
T398 stock_take_unresolved auto-closes when line.resolved=True
T399 cross-model linkage: incident.repair_order_ids One2many
"""
import base64
from datetime import datetime, timedelta, date
from io import BytesIO

from PIL import Image as PILImage

from odoo.exceptions import UserError


_buf = BytesIO()
PILImage.new("RGBA", (1, 1)).save(_buf, format="PNG")
DUMMY_PHOTO = base64.b64encode(_buf.getvalue())


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Repair = env["neon.equipment.repair.order"]
Incident = env["neon.equipment.incident"]
Unit = env["neon.equipment.unit"]
StockTake = env["neon.equipment.stock.take"]
StockLine = env["neon.equipment.stock.take.line"]
Item = env["action.centre.item"]
Category = env["neon.equipment.category"]
EventJob = env["commercial.event.job"]
Crew = env["commercial.job.crew"]
Line = env["commercial.event.job.equipment.line"]
Reservation = env["neon.equipment.reservation"]

manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
crew = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)

# Walk-through helper: pick a unit currently in 'active' state and
# manually transition to 'damaged' to seed repair fixtures. Each test
# gets a fresh unit.
active_pool = Unit.sudo().search([("state", "=", "active")], limit=40)
assert len(active_pool) >= 20, (
    "Need ≥20 active units to seed repair / incident fixtures; "
    "got %d." % len(active_pool))


def _damaged_unit():
    """Pop an active unit, transition to damaged, return it."""
    global active_pool
    unit = active_pool[0]
    active_pool = active_pool[1:]
    unit.sudo()._do_transition("damaged")
    return unit


# Sweep prior orphan repairs / incidents from previous smoke runs.
# These would otherwise pin units in odd states.
Repair.sudo().search([
    ("create_uid", "=", manager.id)]).unlink()
Incident.sudo().search([
    ("create_uid", "=", manager.id)]).unlink()
env.cr.commit()


# ============================================================
print()
print("=" * 72)
print("T380 - create repair_order on damaged unit")
print("=" * 72)
u380 = _damaged_unit()
r380 = Repair.sudo().create({
    "unit_id": u380.id,
    "fault_description": "Mixer channel 3 dead",
})
ok = (
    r380.state == "open"
    and r380.name.startswith("REP-")
    and r380.unit_id == u380
)
print("  name:", r380.name, " state:", r380.state)
print("T380:", "PASS" if ok else "FAIL")
results["T380"] = ok


# ============================================================
print()
print("=" * 72)
print("T381 - repair lifecycle: open → diagnosed → quoted → approved → in_progress → completed")
print("=" * 72)
u381 = _damaged_unit()
r381 = Repair.sudo().create({
    "unit_id": u381.id,
    "fault_description": "PSU smoked",
})
r381.write({"diagnosis_notes": "PSU board replacement required"})
r381.action_diagnose()
r381.write({"estimated_cost": 250.0})
r381.action_quote()
r381.with_user(manager).action_approve()
r381.action_start_repair()
u381.invalidate_recordset()
assert u381.state == "maintenance", "Unit should be maintenance after start"
r381.write({"actual_cost": 275.0})
r381.action_complete_repair()
u381.invalidate_recordset()
ok = r381.state == "completed" and u381.state == "active"
print("  final repair state:", r381.state)
print("  final unit state:", u381.state, "(want active)")
print("T381:", "PASS" if ok else "FAIL")
results["T381"] = ok


# ============================================================
print()
print("=" * 72)
print("T382 - completed repair transitions unit maintenance → active")
print("=" * 72)
# Already validated in T381 — keep as a focused assertion
ok = u381.state == "active"
print("  unit:", u381.display_name, " state:", u381.state)
print("T382:", "PASS" if ok else "FAIL")
results["T382"] = ok


# ============================================================
print()
print("=" * 72)
print("T383 - repair cancellation by manager (mid-flow)")
print("=" * 72)
u383 = _damaged_unit()
r383 = Repair.sudo().create({
    "unit_id": u383.id,
    "fault_description": "Display dim, deferred",
})
r383.with_user(manager).action_cancel()
ok = r383.state == "cancelled"
print("  state:", r383.state)
print("T383:", "PASS" if ok else "FAIL")
results["T383"] = ok


# ============================================================
print()
print("=" * 72)
print("T384 - action_approve blocked for non-manager")
print("=" * 72)
u384 = _damaged_unit()
r384 = Repair.sudo().create({
    "unit_id": u384.id,
    "fault_description": "Knob loose",
    "diagnosis_notes": "Replace pot",
    "estimated_cost": 30.0,
})
r384.action_diagnose()
r384.action_quote()
err, _v = _try(lambda: r384.with_user(sales).action_approve())
ok = isinstance(err, UserError) and "manager" in str(err).lower()
print("  raised:", type(err).__name__ if err else None)
print("T384:", "PASS" if ok else "FAIL")
results["T384"] = ok


# ============================================================
print()
print("=" * 72)
print("T385 - action_complete_repair requires actual_cost")
print("=" * 72)
u385 = _damaged_unit()
r385 = Repair.sudo().create({
    "unit_id": u385.id,
    "fault_description": "Fader scratchy",
    "diagnosis_notes": "Clean + DeoxIT",
    "estimated_cost": 15.0,
})
r385.action_diagnose()
r385.action_quote()
r385.with_user(manager).action_approve()
r385.action_start_repair()
# No actual_cost — complete should raise
err, _v = _try(lambda: r385.action_complete_repair())
ok = isinstance(err, UserError) and "actual cost" in str(err).lower()
print("  raised:", type(err).__name__ if err else None)
print("T385:", "PASS" if ok else "FAIL")
results["T385"] = ok


# ============================================================
print()
print("=" * 72)
print("T386 - create incident on a unit")
print("=" * 72)
u386 = active_pool[0]
active_pool = active_pool[1:]
i386 = Incident.sudo().create({
    "unit_id": u386.id,
    "incident_type": "loss",
    "description": "Mic disappeared at venue strike",
})
ok = (
    i386.state == "open"
    and i386.name.startswith("INC-")
)
print("  name:", i386.name, " state:", i386.state)
print("T386:", "PASS" if ok else "FAIL")
results["T386"] = ok


# ============================================================
print()
print("=" * 72)
print("T387 - incident → under_investigation → resolved_recovered (unit → active)")
print("=" * 72)
u387 = _damaged_unit()
i387 = Incident.sudo().create({
    "unit_id": u387.id,
    "incident_type": "accident",
    "description": "Dropped, knob broken",
})
i387.action_investigate()
i387.with_user(manager).action_resolve_recovered()
u387.invalidate_recordset()
ok = (
    i387.state == "resolved_recovered"
    and u387.state == "active"
)
print("  incident state:", i387.state)
print("  unit state:", u387.state, "(want active)")
print("T387:", "PASS" if ok else "FAIL")
results["T387"] = ok


# ============================================================
print()
print("=" * 72)
print("T388 - incident resolve_writeoff → unit decommissioned")
print("=" * 72)
u388 = active_pool[0]
active_pool = active_pool[1:]
i388 = Incident.sudo().create({
    "unit_id": u388.id,
    "incident_type": "theft",
    "description": "Stolen from the load-in van",
})
i388.action_investigate()
i388.with_user(manager).action_resolve_writeoff(
    reason="Police report filed; not recovered")
u388.invalidate_recordset()
ok = (
    i388.state == "resolved_writeoff"
    and u388.state == "decommissioned"
)
print("  incident state:", i388.state)
print("  unit state:", u388.state, "(want decommissioned)")
print("T388:", "PASS" if ok else "FAIL")
results["T388"] = ok


# ============================================================
print()
print("=" * 72)
print("T389 - incident resolve_claim requires insurance_claim_ref")
print("=" * 72)
u389 = active_pool[0]
active_pool = active_pool[1:]
i389 = Incident.sudo().create({
    "unit_id": u389.id,
    "incident_type": "fire",
    "description": "Generator backfeed damaged amp",
})
i389.action_investigate()
# No claim ref → should raise
err, _v = _try(lambda: i389.with_user(manager).action_resolve_claim())
ok_raise = (
    isinstance(err, UserError)
    and "insurance" in str(err).lower()
)
# Now with claim ref → succeeds
i389.with_user(manager).action_resolve_claim(claim_ref="ZW-CLM-12345")
u389.invalidate_recordset()
ok = (
    ok_raise
    and i389.state == "resolved_claim"
    and i389.insurance_claim_ref == "ZW-CLM-12345"
    and u389.state == "decommissioned"
)
print("  raise without ref:", type(err).__name__ if err else None)
print("  incident state with ref:", i389.state)
print("T389:", "PASS" if ok else "FAIL")
results["T389"] = ok


# ============================================================
print()
print("=" * 72)
print("T390 - P5.M7 incident_link path creates real incident")
print("=" * 72)
# Build an M5 chain: line → reservation → allocate → checkout
ej390 = EventJob.sudo().search([], limit=1, order="id desc")
parent_job = ej390.commercial_job_id
# Pick a product with enough active units
product390 = env["product.template"].sudo().search([
    ("is_workshop_item", "=", True),
    ("tracking_mode", "=", "serial"),
    ("workshop_name", "not ilike", "P5M%_TEST"),
], limit=1)
line390 = Line.sudo().create({
    "event_job_id": ej390.id,
    "product_template_id": product390.id,
    "quantity_planned": 1,
})
line390.action_allocate_units()
line390.with_user(manager).action_checkout()
line390.invalidate_recordset()
u390 = line390.reservation_ids[0].unit_id

# Open the check-in wizard with incident_link resolution
Wizard = env["neon.equipment.checkin.wizard"]
wiz390 = Wizard.with_user(manager).with_context(
    default_event_job_id=ej390.id,
    default_line_id=line390.id,
).create({})
wiz390.checkin_line_ids[0].write({
    "condition_at_event": "missing",
    "resolution_path": "incident_link",
    "photo": DUMMY_PHOTO,
    "resolution_notes": "Crew can't locate after strike",
})
wiz390.action_confirm()
u390.invalidate_recordset()
i390 = Incident.sudo().search([
    ("unit_id", "=", u390.id),
    ("incident_type", "=", "loss"),
    ("state", "=", "open"),
], limit=1, order="id desc")
res390 = line390.reservation_ids[0]
res390.invalidate_recordset()
ok = (
    bool(i390)
    and i390.name.startswith("INC-")
    and u390.state == "checked_out"
    and res390.late_return_pending is True
)
print("  incident created:", i390.name if i390 else None)
print("  unit state:", u390.state, "(want checked_out)")
print("  res.late_return_pending:", res390.late_return_pending)
print("T390:", "PASS" if ok else "FAIL")
results["T390"] = ok


# ============================================================
# Build a stock_take with a few discrepancy lines for T391-T398
sound_cat = env.ref("neon_jobs.equipment_category_sound")
trussing_cat = env.ref("neon_jobs.equipment_category_trussing")
st_session = StockTake.sudo()._create_session(
    session_type="ad_hoc",
    category_ids=trussing_cat,  # Standard category (no high-impact noise)
)
assert len(st_session.line_ids) >= 4, (
    "Need ≥4 Trussing-category lines for T391-T398; got %d." %
    len(st_session.line_ids))


# ============================================================
print()
print("=" * 72)
print("T391 - stock_take_line action_open_repair_order")
print("=" * 72)
line391 = st_session.line_ids[0]
# Attest with discrepancy (damaged condition)
line391.action_attest(
    found_state=line391.expected_state,
    physical_condition="damaged",
)
line391.invalidate_recordset()
assert line391.has_discrepancy
r391 = line391.action_open_repair_order(
    fault_description="Truss leg bent at left junction")
line391.invalidate_recordset()
ok = (
    bool(r391)
    and r391.unit_id == line391.unit_id
    and r391.source_stock_take_line_id == line391
    and line391.resolved is True
    and line391.resolution_method == "repair_opened"
)
print("  repair created:", r391.name if r391 else None)
print("  line.resolved:", line391.resolved,
      " method:", line391.resolution_method)
print("T391:", "PASS" if ok else "FAIL")
results["T391"] = ok


# ============================================================
print()
print("=" * 72)
print("T392 - stock_take_line action_open_incident")
print("=" * 72)
line392 = st_session.line_ids[1]
line392.action_attest(
    found_state="checked_out" if line392.expected_state != "checked_out"
    else "damaged",
)
line392.invalidate_recordset()
assert line392.has_discrepancy
i392 = line392.action_open_incident(
    description="Missing from rack; last seen at venue",
    incident_type="loss")
line392.invalidate_recordset()
ok = (
    bool(i392)
    and i392.unit_id == line392.unit_id
    and i392.source_stock_take_line_id == line392
    and line392.resolved is True
    and line392.resolution_method == "incident_opened"
)
print("  incident created:", i392.name if i392 else None)
print("  line.resolved:", line392.resolved,
      " method:", line392.resolution_method)
print("T392:", "PASS" if ok else "FAIL")
results["T392"] = ok


# ============================================================
print()
print("=" * 72)
print("T393 - incident_open Action Centre item fires on create")
print("=" * 72)
source_model = env["ir.model"].sudo()._get(
    "neon.equipment.incident")
items393 = Item.sudo().search([
    ("trigger_type", "=", "incident_open"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", i392.id),
    ("state", "in", ("open", "in_progress")),
])
ok = bool(items393)
print("  items on incident:", len(items393), "(want >=1)")
if items393:
    print("  sample title:", items393[0].title)
print("T393:", "PASS" if ok else "FAIL")
results["T393"] = ok


# ============================================================
print()
print("=" * 72)
print("T394 - incident_open auto-closes on resolution")
print("=" * 72)
i392.action_investigate()
i392.with_user(manager).action_resolve_recovered()
open_items_394 = Item.sudo().search([
    ("trigger_type", "=", "incident_open"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", i392.id),
    ("state", "in", ("open", "in_progress")),
])
closed_items_394 = Item.sudo().search([
    ("trigger_type", "=", "incident_open"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", i392.id),
    ("state", "=", "cancelled"),
])
ok = not open_items_394 and bool(closed_items_394)
print("  open after resolve:", len(open_items_394), "(want 0)")
print("  closed after resolve:", len(closed_items_394), "(want >=1)")
print("T394:", "PASS" if ok else "FAIL")
results["T394"] = ok


# ============================================================
print()
print("=" * 72)
print("T395 - repair_stalled cron fires for >7-day open repairs")
print("=" * 72)
u395 = _damaged_unit()
r395 = Repair.sudo().create({
    "unit_id": u395.id,
    "fault_description": "Stalled repair fixture",
})
# Backdate write_date to >7 days ago via SQL
cutoff = datetime.utcnow() - timedelta(days=8)
env.cr.execute(
    "UPDATE neon_equipment_repair_order SET write_date = %s WHERE id = %s",
    (cutoff, r395.id),
)
r395.invalidate_recordset()
env["action.centre.item"].sudo()._cron_evaluate_time_based_triggers()
source_model_rep = env["ir.model"].sudo()._get(
    "neon.equipment.repair.order")
items395 = Item.sudo().search([
    ("trigger_type", "=", "repair_stalled"),
    ("source_model_id", "=", source_model_rep.id),
    ("source_id", "=", r395.id),
])
ok = bool(items395)
print("  items:", len(items395), "(want >=1)")
if items395:
    print("  sample title:", items395[0].title)
print("T395:", "PASS" if ok else "FAIL")
results["T395"] = ok


# ============================================================
print()
print("=" * 72)
print("T396 - repair_stalled auto-closes when repair completes")
print("=" * 72)
r395.write({
    "diagnosis_notes": "Quick fix",
    "estimated_cost": 10.0,
})
r395.action_diagnose()
r395.action_quote()
r395.with_user(manager).action_approve()
r395.action_start_repair()
r395.write({"actual_cost": 10.0})
r395.action_complete_repair()
open_items_396 = Item.sudo().search([
    ("trigger_type", "=", "repair_stalled"),
    ("source_model_id", "=", source_model_rep.id),
    ("source_id", "=", r395.id),
    ("state", "in", ("open", "in_progress")),
])
closed_items_396 = Item.sudo().search([
    ("trigger_type", "=", "repair_stalled"),
    ("source_model_id", "=", source_model_rep.id),
    ("source_id", "=", r395.id),
    ("state", "=", "cancelled"),
])
ok = not open_items_396 and bool(closed_items_396)
print("  open after complete:", len(open_items_396), "(want 0)")
print("  closed after complete:", len(closed_items_396), "(want >=1)")
print("T396:", "PASS" if ok else "FAIL")
results["T396"] = ok


# ============================================================
print()
print("=" * 72)
print("T397 - stock_take_unresolved cron fires for >7-day discrepancies")
print("=" * 72)
line397 = st_session.line_ids[2]
line397.action_attest(
    found_state=line397.expected_state,
    physical_condition="damaged",
)
line397.invalidate_recordset()
assert line397.has_discrepancy
# Backdate create_date
env.cr.execute(
    "UPDATE neon_equipment_stock_take_line SET create_date = %s WHERE id = %s",
    (cutoff, line397.id),
)
line397.invalidate_recordset()
env["action.centre.item"].sudo()._cron_evaluate_time_based_triggers()
source_model_line = env["ir.model"].sudo()._get(
    "neon.equipment.stock.take.line")
items397 = Item.sudo().search([
    ("trigger_type", "=", "stock_take_unresolved"),
    ("source_model_id", "=", source_model_line.id),
    ("source_id", "=", line397.id),
])
ok = bool(items397)
print("  items:", len(items397), "(want >=1)")
if items397:
    print("  sample title:", items397[0].title)
print("T397:", "PASS" if ok else "FAIL")
results["T397"] = ok


# ============================================================
print()
print("=" * 72)
print("T398 - stock_take_unresolved auto-closes when resolved")
print("=" * 72)
line397.action_resolve(notes="Reconciled with movement log",
                       method="reconciled")
open_items_398 = Item.sudo().search([
    ("trigger_type", "=", "stock_take_unresolved"),
    ("source_model_id", "=", source_model_line.id),
    ("source_id", "=", line397.id),
    ("state", "in", ("open", "in_progress")),
])
closed_items_398 = Item.sudo().search([
    ("trigger_type", "=", "stock_take_unresolved"),
    ("source_model_id", "=", source_model_line.id),
    ("source_id", "=", line397.id),
    ("state", "=", "cancelled"),
])
ok = not open_items_398 and bool(closed_items_398)
print("  open after resolve:", len(open_items_398), "(want 0)")
print("  closed after resolve:", len(closed_items_398), "(want >=1)")
print("T398:", "PASS" if ok else "FAIL")
results["T398"] = ok


# ============================================================
print()
print("=" * 72)
print("T399 - cross-model linkage: incident.repair_order_ids")
print("=" * 72)
u399 = active_pool[0]
active_pool = active_pool[1:]
i399 = Incident.sudo().create({
    "unit_id": u399.id,
    "incident_type": "accident",
    "description": "Multi-stage failure",
})
r399a = Repair.sudo().create({
    "unit_id": u399.id,
    "incident_id": i399.id,
    "fault_description": "Step 1 — replace fuse",
})
r399b = Repair.sudo().create({
    "unit_id": u399.id,
    "incident_id": i399.id,
    "fault_description": "Step 2 — replace pre-amp",
})
i399.invalidate_recordset()
ok = (
    len(i399.repair_order_ids) == 2
    and r399a in i399.repair_order_ids
    and r399b in i399.repair_order_ids
)
print("  linked repairs:", len(i399.repair_order_ids), "(want 2)")
print("T399:", "PASS" if ok else "FAIL")
results["T399"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = [f"T{i}" for i in range(380, 400)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
