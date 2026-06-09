"""P5.M6 smoke — equipment transfer flow.

T320 wizard initiates transfer; movement spawned with state=pending
T321 initiate authority — manager passes
T322 initiate authority — Lead Tech (crew_leader group) passes
T323 initiate authority — regular crew blocked
T324 accept authority — destination Crew Chief passes; reservation
     + transfer_in companion + unit checked_out on destination
T325 accept authority — non-destination user blocked
T326 decline returns unit to source; chatter post; transfer_in
     marked as decline-return via transfer_out_movement_id
T327 same-state no-op — accept on already-accepted raises
T328 cron fires transfer_pending for >24h pending transfer
T329 auto-close transfer_pending on accept
T330 auto-close transfer_pending on decline
T331 bulk atomicity — one bad unit rolls back the whole batch
T332 self-transfer (source == destination) blocked
"""
from datetime import datetime, timedelta
from odoo.exceptions import UserError


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

Reservation = env["neon.equipment.reservation"]
Unit = env["neon.equipment.unit"]
Line = env["commercial.event.job.equipment.line"]
Movement = env["neon.equipment.movement"]
EventJob = env["commercial.event.job"]
Crew = env["commercial.job.crew"]
Product = env["product.template"]
Item = env["action.centre.item"]
Wizard = env["neon.equipment.transfer.wizard"]

manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
lead = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
crew = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
other_crew = env["res.users"].search(
    [("login", "=", "p2m75_other")], limit=1)
sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)

# Pick source + destination commercial_jobs. Make crew chiefs.
source_ej = EventJob.sudo().search([], limit=1, order="id desc")
parent_job = source_ej.commercial_job_id
other_job = env["commercial.job"].sudo().search(
    [("id", "!=", parent_job.id)], limit=1, order="id")
assert source_ej and parent_job and other_job

# Fresh destination event_job under other_job (rolls back at end)
dest_ej = EventJob.sudo().create({"commercial_job_id": other_job.id})

# Upsert crew chiefs: p2m75_crew on SOURCE (parent_job),
# p2m75_other on DESTINATION (other_job).
Crew.sudo().search(
    [("job_id", "in", (parent_job.id, other_job.id))]).write(
    {"is_crew_chief": False})


def _set_crew_chief(job, user):
    existing = Crew.sudo().search([
        ("job_id", "=", job.id),
        ("partner_id", "=", user.partner_id.id),
    ], limit=1)
    if existing:
        existing.write({"user_id": user.id, "is_crew_chief": True})
    else:
        Crew.sudo().create({
            "job_id": job.id,
            "user_id": user.id,
            "partner_id": user.partner_id.id,
            "is_crew_chief": True,
        })


_set_crew_chief(parent_job, crew)
_set_crew_chief(other_job, other_crew)

# Sweep any orphan movements + items from earlier smoke iterations.
orphan_mvts = Movement.sudo().search(
    [("actor_id", "in", (manager.id, lead.id, crew.id,
                         other_crew.id, sales.id))])
if orphan_mvts:
    orphan_mvts.with_context(_allow_movement_write=True).unlink()
orphan_items = Item.sudo().search([
    ("trigger_type", "in", ("transfer_pending",)),
])
if orphan_items:
    orphan_items.with_context(_allow_state_write=True).unlink()
env.cr.commit()

# Build a serial-product pool with ≥1 active unit per product — each
# transfer fixture consumes 1 unit, and there are 13 tests.
def _find_pool(min_units, target_count):
    found = []
    for p in Product.sudo().search([
            ("is_workshop_item", "=", True),
            ("tracking_mode", "=", "serial"),
            ("workshop_name", "not ilike", "P5M%_TEST"),
            ("workshop_name", "not ilike", "P5M%_T28%"),
    ], order="id"):
        active = Unit.sudo().search_count([
            ("product_template_id", "=", p.id),
            ("state", "=", "active"),
        ])
        if active >= min_units:
            found.append(p)
            if len(found) >= target_count:
                break
    return found


products_pool = _find_pool(min_units=1, target_count=18)
assert len(products_pool) >= 15, (
    "Need ≥15 distinct serial products with ≥1 active unit each "
    "(14 tests; T331 consumes 3 + T333 adds 1); got %d." % len(products_pool))
_pool_iter = iter(products_pool)
print("source_ej:", source_ej.name, "dest_ej:", dest_ej.name)
print("crew chiefs: parent_job=", crew.login,
      " other_job=", other_crew.login)


def _make_checked_out_unit():
    """Build a fresh M5 chain on source_ej producing one checked_out
    unit: line → auto-reservation → allocate → checkout. Returns the
    (line, unit) pair. Uses the next product from the pool."""
    p = next(_pool_iter)
    line = Line.sudo().create({
        "event_job_id": source_ej.id,
        "product_template_id": p.id,
        "quantity_planned": 1,
    })
    line.action_allocate_units()
    line.with_user(manager).action_checkout()
    line.invalidate_recordset()
    return line, line.reservation_ids[0].unit_id


def _initiate_one(actor=None):
    """Helper: build a fixture + initiate transfer of its single
    unit to dest_ej. Returns the (line, unit, movement) triple."""
    line, unit = _make_checked_out_unit()
    user = actor or manager
    mvts = source_ej.with_user(user)._initiate_transfer(
        units=unit, destination=dest_ej)
    return line, unit, mvts


# ============================================================
print()
print("=" * 72)
print("T320 - wizard initiates transfer (transfer_out + pending)")
print("=" * 72)
line320, unit320 = _make_checked_out_unit()
wiz320 = Wizard.with_user(manager).create({
    "source_event_job_id": source_ej.id,
    "destination_event_job_id": dest_ej.id,
    "unit_ids": [(6, 0, [unit320.id])],
})
wiz320.action_confirm()
unit320.invalidate_recordset()
mvt320 = Movement.sudo().search([
    ("unit_id", "=", unit320.id),
    ("movement_type", "=", "transfer_out"),
], limit=1, order="id desc")
ok = (
    bool(mvt320)
    and mvt320.transfer_state == "pending"
    and mvt320.destination_event_job_id == dest_ej
    and unit320.state == "transferred"
)
print("  movement:", mvt320.name if mvt320 else None,
      " state:", mvt320.transfer_state if mvt320 else None)
print("  unit state:", unit320.state, "(want transferred)")
print("T320:", "PASS" if ok else "FAIL")
results["T320"] = ok


# ============================================================
print()
print("=" * 72)
print("T321 - initiate authority — manager passes")
print("=" * 72)
err, mvts321 = _try(lambda: _initiate_one(actor=manager))
ok = err is None and mvts321 and len(mvts321[2]) == 1
print("  err:", type(err).__name__ if err else None)
print("T321:", "PASS" if ok else "FAIL")
results["T321"] = ok


# ============================================================
print()
print("=" * 72)
print("T322 - initiate authority — Lead Tech (crew_leader) passes")
print("=" * 72)
err, mvts322 = _try(lambda: _initiate_one(actor=lead))
ok = err is None and mvts322 and len(mvts322[2]) == 1
print("  err:", type(err).__name__ if err else None)
print("T322:", "PASS" if ok else "FAIL")
results["T322"] = ok


# ============================================================
print()
print("=" * 72)
print("T323 - initiate authority — sales (no chief, no group) blocked")
print("=" * 72)
line323, unit323 = _make_checked_out_unit()
err, _v = _try(lambda: source_ej.with_user(sales)._initiate_transfer(
    units=unit323, destination=dest_ej))
ok = isinstance(err, UserError) and "authoris" in str(err).lower()
print("  raised:", type(err).__name__ if err else None)
print("  msg excerpt:", (str(err) or "")[:120])
print("T323:", "PASS" if ok else "FAIL")
results["T323"] = ok


# ============================================================
print()
print("=" * 72)
print("T324 - accept authority — destination Crew Chief passes")
print("=" * 72)
line324, unit324, mvts324 = _initiate_one(actor=manager)
mvt324 = mvts324[0]
mvt324.with_user(other_crew).action_accept_transfer()
mvt324.invalidate_recordset()
unit324.invalidate_recordset()
# Verify: state accepted, unit checked_out, new transfer_in movement
companion = Movement.sudo().search([
    ("transfer_out_movement_id", "=", mvt324.id),
    ("movement_type", "=", "transfer_in"),
], limit=1)
# Verify new fulfilled reservation on destination
new_res = Reservation.sudo().search([
    ("unit_id", "=", unit324.id),
    ("event_job_id", "=", dest_ej.id),
    ("state", "=", "fulfilled"),
], limit=1)
ok = (
    mvt324.transfer_state == "accepted"
    and unit324.state == "checked_out"
    and bool(companion)
    and bool(new_res)
)
print("  transfer_state:", mvt324.transfer_state)
print("  unit state:", unit324.state, "(want checked_out)")
print("  transfer_in companion:", companion.name if companion else None)
print("  new dest reservation:", new_res.name if new_res else None)
print("T324:", "PASS" if ok else "FAIL")
results["T324"] = ok


# ============================================================
print()
print("=" * 72)
print("T325 - accept authority — non-destination user blocked")
print("=" * 72)
line325, unit325, mvts325 = _initiate_one(actor=manager)
mvt325 = mvts325[0]
# p2m75_crew is chief on SOURCE, not destination → blocked
err, _v = _try(lambda: mvt325.with_user(crew).action_accept_transfer())
ok = isinstance(err, UserError) and "authoris" in str(err).lower()
print("  raised:", type(err).__name__ if err else None)
print("T325:", "PASS" if ok else "FAIL")
results["T325"] = ok


# ============================================================
print()
print("=" * 72)
print("T326 - decline returns unit to source + chatter + companion")
print("=" * 72)
line326, unit326, mvts326 = _initiate_one(actor=manager)
mvt326 = mvts326[0]
source_msgs_before = len(source_ej.message_ids)
mvt326.with_user(other_crew).action_decline_transfer(
    reason="No room at venue")
mvt326.invalidate_recordset()
unit326.invalidate_recordset()
source_ej.invalidate_recordset()
companion = Movement.sudo().search([
    ("transfer_out_movement_id", "=", mvt326.id),
    ("movement_type", "=", "transfer_in"),
], limit=1)
decline_chatter = source_ej.message_ids.filtered(
    lambda m: m.body and "declined" in m.body.lower())
ok = (
    mvt326.transfer_state == "declined"
    and unit326.state == "checked_out"
    and bool(companion)
    and bool(decline_chatter)
)
print("  transfer_state:", mvt326.transfer_state)
print("  unit state:", unit326.state, "(want checked_out, back on source)")
print("  decline-return companion:",
      companion.name if companion else None)
print("  decline chatter on source?", bool(decline_chatter))
print("T326:", "PASS" if ok else "FAIL")
results["T326"] = ok


# ============================================================
print()
print("=" * 72)
print("T327 - accept on already-accepted transfer raises")
print("=" * 72)
line327, unit327, mvts327 = _initiate_one(actor=manager)
mvt327 = mvts327[0]
mvt327.with_user(other_crew).action_accept_transfer()
# Try accepting again — should raise
err, _v = _try(lambda: mvt327.with_user(
    other_crew).action_accept_transfer())
ok = isinstance(err, UserError) and "already" in str(err).lower()
print("  raised:", type(err).__name__ if err else None)
print("  msg excerpt:", (str(err) or "")[:120])
print("T327:", "PASS" if ok else "FAIL")
results["T327"] = ok


# ============================================================
print()
print("=" * 72)
print("T328 - cron fires transfer_pending for >24h pending")
print("=" * 72)
line328, unit328, mvts328 = _initiate_one(actor=manager)
mvt328 = mvts328[0]
# Backdate create_date via raw SQL so the 24h filter fires
cutoff = datetime.utcnow() - timedelta(hours=25)
env.cr.execute(
    "UPDATE neon_equipment_movement SET create_date = %s WHERE id = %s",
    (cutoff, mvt328.id),
)
mvt328.invalidate_recordset()
# Run the cron evaluator
env["action.centre.item"].sudo()._cron_evaluate_time_based_triggers()
source_model = env["ir.model"].sudo()._get("neon.equipment.movement")
items328 = Item.sudo().search([
    ("trigger_type", "=", "transfer_pending"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", mvt328.id),
])
ok = bool(items328)
print("  items spawned:", len(items328), "(want >=1)")
if items328:
    print("  sample title:", items328[0].title)
print("T328:", "PASS" if ok else "FAIL")
results["T328"] = ok


# ============================================================
print()
print("=" * 72)
print("T329 - auto-close transfer_pending on acceptance")
print("=" * 72)
# Continue from T328's setup
mvt328.with_user(other_crew).action_accept_transfer()
open_items_329 = Item.sudo().search([
    ("trigger_type", "=", "transfer_pending"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", mvt328.id),
    ("state", "in", ("open", "in_progress")),
])
closed_items_329 = Item.sudo().search([
    ("trigger_type", "=", "transfer_pending"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", mvt328.id),
    ("state", "=", "cancelled"),
])
ok = not open_items_329 and bool(closed_items_329)
print("  open items after accept:", len(open_items_329), "(want 0)")
print("  closed items after accept:",
      len(closed_items_329), "(want >=1)")
print("T329:", "PASS" if ok else "FAIL")
results["T329"] = ok


# ============================================================
print()
print("=" * 72)
print("T330 - auto-close transfer_pending on decline")
print("=" * 72)
line330, unit330, mvts330 = _initiate_one(actor=manager)
mvt330 = mvts330[0]
env.cr.execute(
    "UPDATE neon_equipment_movement SET create_date = %s WHERE id = %s",
    (cutoff, mvt330.id),
)
mvt330.invalidate_recordset()
env["action.centre.item"].sudo()._cron_evaluate_time_based_triggers()
mvt330.with_user(other_crew).action_decline_transfer(reason="venue full")
open_items_330 = Item.sudo().search([
    ("trigger_type", "=", "transfer_pending"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", mvt330.id),
    ("state", "in", ("open", "in_progress")),
])
closed_items_330 = Item.sudo().search([
    ("trigger_type", "=", "transfer_pending"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", mvt330.id),
    ("state", "=", "cancelled"),
])
ok = not open_items_330 and bool(closed_items_330)
print("  open after decline:", len(open_items_330), "(want 0)")
print("  closed after decline:",
      len(closed_items_330), "(want >=1)")
print("T330:", "PASS" if ok else "FAIL")
results["T330"] = ok


# ============================================================
print()
print("=" * 72)
print("T331 - bulk atomicity: one bad unit rolls back the batch")
print("=" * 72)
# Build three checked_out units
fixtures_331 = [_make_checked_out_unit() for _ in range(3)]
units_331 = [u for _l, u in fixtures_331]
# Move one unit out of 'checked_out' to break the batch
bad_unit = units_331[1]
bad_unit._do_transition("maintenance")
# Snapshot movement count
mv_count_before = Movement.sudo().search_count([])
err, _v = _try(lambda: source_ej.with_user(manager)._initiate_transfer(
    units=env["neon.equipment.unit"].browse([u.id for u in units_331]),
    destination=dest_ej))
mv_count_after = Movement.sudo().search_count([])
for u in units_331:
    u.invalidate_recordset()
ok = (
    isinstance(err, UserError)
    and mv_count_after == mv_count_before  # no new movements
    and units_331[0].state == "checked_out"  # unaffected
    and units_331[1].state == "maintenance"  # the bad one
    and units_331[2].state == "checked_out"  # unaffected
)
print("  raised:", type(err).__name__ if err else None)
print("  movements before/after:", mv_count_before, "/", mv_count_after)
print("  unit states:",
      [u.state for u in units_331], "(want checked_out, maintenance, checked_out)")
print("T331:", "PASS" if ok else "FAIL")
results["T331"] = ok


# ============================================================
print()
print("=" * 72)
print("T332 - self-transfer (source == destination) blocked")
print("=" * 72)
line332, unit332 = _make_checked_out_unit()
err, _v = _try(lambda: source_ej.with_user(manager)._initiate_transfer(
    units=unit332, destination=source_ej))
ok = isinstance(err, UserError) and "same" in str(err).lower()
print("  raised:", type(err).__name__ if err else None)
print("  msg excerpt:", (str(err) or "")[:120])
print("T332:", "PASS" if ok else "FAIL")
results["T332"] = ok


# ============================================================
print()
print("=" * 72)
print("T333 - accept transfer into an UNDATED destination (no "
      "event_date/schedule) succeeds; reserve_from < reserve_to")
print("=" * 72)
# Regression for the 2026-06-09 _accept_atomic window bug
# [tag:odoo-datetime-now-equal-strict-check]: a destination with an
# empty reservation window made the accept default both ends to
# Datetime.now() (equal, second-truncated) -> CHECK (from<to) violation.
from unittest.mock import patch  # noqa: E402

line333, unit333 = _make_checked_out_unit()
dest333 = EventJob.sudo().create({"commercial_job_id": other_job.id})
mvts333 = source_ej.with_user(manager)._initiate_transfer(
    units=unit333, destination=dest333)
mvt333 = mvts333[0]
# Force the empty-window branch. event_date is a stored related off
# commercial_job (required + NOT NULL) so it can't be NULLed on the dest;
# stub the window helper to return (None, None) for this accept — the
# same "reach the code path" affordance T328 uses with raw-SQL date
# backdating. Pre-fix, _accept_atomic defaulted BOTH ends to now()
# (equal) -> CHECK (reserve_from < reserve_to) IntegrityError. The fix
# anchors reserve_from=now(), reserve_to=rf+1h.
with patch.object(dest333.__class__, "_reservation_window_for_autocreate",
                  return_value=(False, False)):
    err333, _v = _try(
        lambda: mvt333.with_user(manager).action_accept_transfer())
new_res333 = Reservation.sudo().search([
    ("unit_id", "=", unit333.id),
    ("event_job_id", "=", dest333.id),
    ("state", "=", "fulfilled"),
], limit=1)
delta333 = (
    (new_res333.reserve_to - new_res333.reserve_from)
    if (new_res333 and new_res333.reserve_from and new_res333.reserve_to)
    else None)
ok = (
    err333 is None
    and bool(new_res333)
    and bool(new_res333.reserve_from)
    and bool(new_res333.reserve_to)
    and new_res333.reserve_from < new_res333.reserve_to
    and delta333 == timedelta(hours=1)
)
print("  accept error:", type(err333).__name__ if err333 else None,
      "(want None — pre-fix this raised an IntegrityError on the CHECK)")
if new_res333:
    print("  reserve_from:", new_res333.reserve_from,
          " reserve_to:", new_res333.reserve_to,
          " delta:", delta333, "(want 1:00:00)")
print("T333:", "PASS" if ok else "FAIL")
results["T333"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T320", "T321", "T322", "T323", "T324", "T325", "T326",
         "T327", "T328", "T329", "T330", "T331", "T332", "T333"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
