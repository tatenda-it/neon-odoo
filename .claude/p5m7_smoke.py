"""P5.M7 smoke — equipment check-in flow.

T340 wizard auto-populates from event_job's checked_out units
T341 condition='good': checked_out -> returned -> active + movement
T342 condition='damaged' without photo: UserError listing units
T343 condition='damaged' with photo: -> damaged + movement w/ photo
T344 condition='poor' + send_to_maintenance: -> maintenance
T345 condition='missing' + returned_late: reservation flagged, no state change
T346 condition='missing' + write_off: -> decommissioned, write_off movement
T347 condition='missing' + incident_link: UserError stub for P5.M9
T348 closeout BLOCKED while units still out
T349 closeout passes equipment check after write_off
T350 closeout passes equipment check after returned_late
T351 atomic bulk: one bad line rolls back the whole wizard
T352 authority — Crew Chief on this event passes
T353 authority — Crew Chief on another event blocked
T354 has_unresolved_missing recomputes incrementally
"""
import base64
from io import BytesIO
from PIL import Image
from odoo.exceptions import UserError


# Tiny valid PNG (1x1 transparent) generated via Pillow so Odoo's
# image_fix_orientation EXIF probe doesn't choke. Hand-rolled byte
# strings fail because Odoo validates via PIL on write.
_buf = BytesIO()
Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(_buf, format="PNG")
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

Reservation = env["neon.equipment.reservation"]
Unit = env["neon.equipment.unit"]
Line = env["commercial.event.job.equipment.line"]
Movement = env["neon.equipment.movement"]
EventJob = env["commercial.event.job"]
Crew = env["commercial.job.crew"]
Product = env["product.template"]
Wizard = env["neon.equipment.checkin.wizard"]

manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
lead = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
crew = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
other_crew = env["res.users"].search(
    [("login", "=", "p2m75_other")], limit=1)
sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)

source_ej = EventJob.sudo().search([], limit=1, order="id desc")
parent_job = source_ej.commercial_job_id
other_job = env["commercial.job"].sudo().search(
    [("id", "!=", parent_job.id)], limit=1, order="id")
other_ej = EventJob.sudo().create({"commercial_job_id": other_job.id})
# Dedicated event_job for T348-T350 (closeout blocker tests) so we
# can read has_unresolved_missing in isolation from the source_ej
# accumulation of T342/T347/T354 fixtures. Move it to 'completed'
# via the _allow_state_write bypass — _check_authority("closed")
# requires from-state='completed', and walking the full state
# machine from 'draft' would need a dozen unrelated fixtures.
closeout_ej = EventJob.sudo().create(
    {"commercial_job_id": parent_job.id})
closeout_ej.sudo().with_context(_allow_state_write=True).write(
    {"state": "completed",
     "gear_reconciled": True,
     "finance_handoff_complete": True})

# Upsert crew chiefs (same pattern as M6 smoke)
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

# Sweep orphans from prior aborted smoke iterations
Movement.sudo().search(
    [("actor_id", "in", (manager.id, lead.id, crew.id,
                         other_crew.id, sales.id))]
).with_context(_allow_movement_write=True).unlink()
env.cr.commit()


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


products_pool = _find_pool(min_units=3, target_count=20)
assert len(products_pool) >= 12, (
    "Need ≥12 distinct serial products with ≥3 active units each "
    "(one per test that allocates units); got %d. Other P5 smokes "
    "may have committed state — re-seed the testing kit if needed."
    % len(products_pool))
_pool_iter = iter(products_pool)
print("source_ej:", source_ej.name, "other_ej:", other_ej.name)


def _make_line_with_checked_out_units(qty=1, event_job=None):
    """Build M5 chain: line → auto-reservations → allocate → checkout.
    Returns (line, units_recordset)."""
    target = event_job or source_ej
    p = next(_pool_iter)
    line = Line.sudo().create({
        "event_job_id": target.id,
        "product_template_id": p.id,
        "quantity_planned": qty,
    })
    line.action_allocate_units()
    line.with_user(manager).action_checkout()
    line.invalidate_recordset()
    return line, line.reservation_ids.mapped("unit_id")


def _open_wizard(line=None, event_job=None, user=None):
    """Open the check-in wizard via the same context the source
    actions use. Returns the populated wizard record."""
    target_user = user or manager
    ctx = {"default_event_job_id": (event_job or source_ej).id}
    if line:
        ctx["default_line_id"] = line.id
    return Wizard.with_user(target_user).with_context(**ctx).create({})


# ============================================================
print()
print("=" * 72)
print("T340 - wizard auto-populates units for a line")
print("=" * 72)
line340, units340 = _make_line_with_checked_out_units(qty=3)
wiz340 = _open_wizard(line=line340)
wiz_unit_ids = wiz340.checkin_line_ids.mapped("unit_id.id")
ok = (
    len(wiz340.checkin_line_ids) == 3
    and set(wiz_unit_ids) == set(units340.ids)
    and all(wl.condition_at_event == "good"
            for wl in wiz340.checkin_line_ids)
)
print("  wizard lines:", len(wiz340.checkin_line_ids), "(want 3)")
print("  default conditions:",
      [wl.condition_at_event for wl in wiz340.checkin_line_ids])
print("T340:", "PASS" if ok else "FAIL")
results["T340"] = ok


# ============================================================
print()
print("=" * 72)
print("T341 - condition='good': checked_out → returned → active + movement")
print("=" * 72)
wiz340.action_confirm()
units340.invalidate_recordset()
movements341 = Movement.sudo().search([
    ("unit_id", "in", units340.ids),
    ("movement_type", "=", "checkin"),
])
ok = (
    all(u.state == "active" for u in units340)
    and len(movements341) == 3
    and all(m.condition_at_event == "good" for m in movements341)
)
print("  unit states:", [u.state for u in units340], "(want all active)")
print("  movements:", len(movements341), "(want 3)")
print("T341:", "PASS" if ok else "FAIL")
results["T341"] = ok


# ============================================================
print()
print("=" * 72)
print("T342 - condition='damaged' without photo raises UserError")
print("=" * 72)
line342, units342 = _make_line_with_checked_out_units(qty=1)
wiz342 = _open_wizard(line=line342)
wiz342.checkin_line_ids[0].write({"condition_at_event": "damaged"})
err, _v = _try(lambda: wiz342.action_confirm())
ok = (
    isinstance(err, UserError)
    and "photo" in str(err).lower()
    and units342[0].state == "checked_out"  # unchanged
)
print("  raised:", type(err).__name__ if err else None)
print("  msg excerpt:", (str(err) or "")[:140])
print("T342:", "PASS" if ok else "FAIL")
results["T342"] = ok


# ============================================================
print()
print("=" * 72)
print("T343 - condition='damaged' with photo → unit damaged + movement")
print("=" * 72)
# Reuse wizard from T342 (savepoint rolled back the failed confirm)
# but we need fresh state — open a new wizard
wiz343 = _open_wizard(line=line342)
wiz343.checkin_line_ids[0].write({
    "condition_at_event": "damaged",
    "photo": DUMMY_PHOTO,
})
wiz343.action_confirm()
units342.invalidate_recordset()
mvt343 = Movement.sudo().search([
    ("unit_id", "=", units342[0].id),
    ("movement_type", "=", "checkin"),
], limit=1, order="id desc")
ok = (
    units342[0].state == "damaged"
    and bool(mvt343)
    and mvt343.condition_at_event == "damaged"
    and bool(mvt343.photo)
)
print("  unit state:", units342[0].state, "(want damaged)")
print("  movement condition:", mvt343.condition_at_event if mvt343 else None)
print("  photo on movement?", bool(mvt343.photo) if mvt343 else None)
print("T343:", "PASS" if ok else "FAIL")
results["T343"] = ok


# ============================================================
print()
print("=" * 72)
print("T344 - condition='poor' + send_to_maintenance → unit maintenance")
print("=" * 72)
line344, units344 = _make_line_with_checked_out_units(qty=1)
wiz344 = _open_wizard(line=line344)
wiz344.checkin_line_ids[0].write({
    "condition_at_event": "poor",
    "send_to_maintenance": True,
    "photo": DUMMY_PHOTO,
})
wiz344.action_confirm()
units344.invalidate_recordset()
ok = units344[0].state == "maintenance"
print("  unit state:", units344[0].state, "(want maintenance)")
print("T344:", "PASS" if ok else "FAIL")
results["T344"] = ok


# ============================================================
print()
print("=" * 72)
print("T345 - condition='missing' + returned_late: flag reservation, no state change")
print("=" * 72)
line345, units345 = _make_line_with_checked_out_units(qty=1)
wiz345 = _open_wizard(line=line345)
wiz345.checkin_line_ids[0].write({
    "condition_at_event": "missing",
    "resolution_path": "returned_late",
    "resolution_notes": "Crew confirms in transit",
    "photo": DUMMY_PHOTO,
})
wiz345.action_confirm()
units345.invalidate_recordset()
source_ej.invalidate_recordset()
res345 = line345.reservation_ids[0]
res345.invalidate_recordset()
ok = (
    units345[0].state == "checked_out"  # unchanged
    and res345.late_return_pending is True
    and source_ej.has_unresolved_missing is False  # flag excludes it
)
print("  unit state:", units345[0].state, "(want checked_out)")
print("  res.late_return_pending:", res345.late_return_pending)
print("  ej.has_unresolved_missing:", source_ej.has_unresolved_missing,
      "(want False — flag excludes)")
print("T345:", "PASS" if ok else "FAIL")
results["T345"] = ok


# ============================================================
print()
print("=" * 72)
print("T346 - condition='missing' + write_off → decommissioned + movement")
print("=" * 72)
line346, units346 = _make_line_with_checked_out_units(qty=1)
wiz346 = _open_wizard(line=line346)
wiz346.checkin_line_ids[0].write({
    "condition_at_event": "missing",
    "resolution_path": "write_off",
    "resolution_notes": "Lost at venue",
    "photo": DUMMY_PHOTO,
})
wiz346.action_confirm()
units346.invalidate_recordset()
mvt346 = Movement.sudo().search([
    ("unit_id", "=", units346[0].id),
    ("movement_type", "=", "write_off"),
], limit=1, order="id desc")
ok = (
    units346[0].state == "decommissioned"
    and bool(mvt346)
    and mvt346.condition_at_event == "missing"
)
print("  unit state:", units346[0].state, "(want decommissioned)")
print("  write_off movement:", mvt346.name if mvt346 else None)
print("T346:", "PASS" if ok else "FAIL")
results["T346"] = ok


# ============================================================
print()
print("=" * 72)
print("T347 - condition='missing' + incident_link creates a real incident (P5.M9)")
print("=" * 72)
line347, units347 = _make_line_with_checked_out_units(qty=1)
wiz347 = _open_wizard(line=line347)
wiz347.checkin_line_ids[0].write({
    "condition_at_event": "missing",
    "resolution_path": "incident_link",
    "photo": DUMMY_PHOTO,
    "resolution_notes": "Crew can't locate after strike",
})
wiz347.action_confirm()
units347.invalidate_recordset()
Incident = env["neon.equipment.incident"]
incident347 = Incident.sudo().search([
    ("unit_id", "=", units347[0].id),
    ("incident_type", "=", "loss"),
    ("state", "=", "open"),
], limit=1, order="id desc")
res347 = line347.reservation_ids[0]
res347.invalidate_recordset()
ok = (
    bool(incident347)
    and incident347.name.startswith("INC-")
    and units347[0].state == "checked_out"  # unchanged
    and res347.late_return_pending is True
)
print("  incident created:", incident347.name if incident347 else None)
print("  unit state:", units347[0].state, "(want checked_out)")
print("  res.late_return_pending:", res347.late_return_pending)
print("T347:", "PASS" if ok else "FAIL")
results["T347"] = ok


# ============================================================
print()
print("=" * 72)
print("T348 - closeout BLOCKED while units still out")
print("=" * 72)
# Use the dedicated closeout_ej so has_unresolved_missing reflects
# ONLY this test's fixture, not leftovers from T342/T347/T354.
line348, units348 = _make_line_with_checked_out_units(
    qty=1, event_job=closeout_ej)
closeout_ej.invalidate_recordset()
err, _v = _try(lambda: closeout_ej.with_user(
    manager).action_move_to_closed())
ok = (
    closeout_ej.has_unresolved_missing is True
    and isinstance(err, UserError)
    and "Equipment Check-In" in str(err)
)
print("  has_unresolved_missing:", closeout_ej.has_unresolved_missing)
print("  raised:", type(err).__name__ if err else None)
print("  msg mentions Equipment Check-In:",
      "Equipment Check-In" in str(err) if err else None)
print("T348:", "PASS" if ok else "FAIL")
results["T348"] = ok


# ============================================================
print()
print("=" * 72)
print("T349 - closeout passes equipment check after write_off")
print("=" * 72)
# Continue with closeout_ej: write-off the unit from T348.
wiz349 = _open_wizard(line=line348, event_job=closeout_ej)
wiz349.checkin_line_ids[0].write({
    "condition_at_event": "missing",
    "resolution_path": "write_off",
    "photo": DUMMY_PHOTO,
})
wiz349.action_confirm()
closeout_ej.invalidate_recordset()
err, _v = _try(lambda: closeout_ej.with_user(
    manager).action_move_to_closed())
ok = (
    closeout_ej.has_unresolved_missing is False
    and (err is None or "Equipment Check-In" not in str(err))
)
print("  has_unresolved_missing:", closeout_ej.has_unresolved_missing,
      "(want False)")
print("  equipment text in error?:",
      "Equipment Check-In" in str(err) if err else "no error")
print("T349:", "PASS" if ok else "FAIL")
results["T349"] = ok


# ============================================================
print()
print("=" * 72)
print("T350 - closeout passes equipment check after returned_late")
print("=" * 72)
# Fresh unit on closeout_ej (T349's was decommissioned).
line350, units350 = _make_line_with_checked_out_units(
    qty=1, event_job=closeout_ej)
closeout_ej.invalidate_recordset()
# Sanity: has_unresolved_missing flipped back to True with new fixture
assert closeout_ej.has_unresolved_missing is True
wiz350 = _open_wizard(line=line350, event_job=closeout_ej)
wiz350.checkin_line_ids[0].write({
    "condition_at_event": "missing",
    "resolution_path": "returned_late",
    "resolution_notes": "Will reconcile next week",
    "photo": DUMMY_PHOTO,
})
wiz350.action_confirm()
closeout_ej.invalidate_recordset()
err, _v = _try(lambda: closeout_ej.with_user(
    manager).action_move_to_closed())
ok = (
    closeout_ej.has_unresolved_missing is False
    and (err is None or "Equipment Check-In" not in str(err))
)
print("  has_unresolved_missing:", closeout_ej.has_unresolved_missing,
      "(want False — returned_late excludes)")
print("  equipment text in error?:",
      "Equipment Check-In" in str(err) if err else "no error")
print("T350:", "PASS" if ok else "FAIL")
results["T350"] = ok


# ============================================================
print()
print("=" * 72)
print("T351 - atomic: bad line rolls back whole batch (no movements)")
print("=" * 72)
line351, units351 = _make_line_with_checked_out_units(qty=3)
wiz351 = _open_wizard(line=line351)
# Set ONE line to damaged without photo — should block the whole batch
wiz351.checkin_line_ids[0].write({"condition_at_event": "good"})
wiz351.checkin_line_ids[1].write({
    "condition_at_event": "damaged"})  # missing photo
wiz351.checkin_line_ids[2].write({"condition_at_event": "good"})
mv_count_before = Movement.sudo().search_count([
    ("unit_id", "in", units351.ids)])
err, _v = _try(lambda: wiz351.action_confirm())
mv_count_after = Movement.sudo().search_count([
    ("unit_id", "in", units351.ids)])
units351.invalidate_recordset()
ok = (
    isinstance(err, UserError)
    and mv_count_before == mv_count_after
    and all(u.state == "checked_out" for u in units351)
)
print("  raised:", type(err).__name__ if err else None)
print("  movements before/after:", mv_count_before, "/", mv_count_after)
print("  unit states unchanged?",
      all(u.state == "checked_out" for u in units351))
print("T351:", "PASS" if ok else "FAIL")
results["T351"] = ok


# ============================================================
print()
print("=" * 72)
print("T352 - authority — Crew Chief on this event passes")
print("=" * 72)
line352, units352 = _make_line_with_checked_out_units(qty=1)
wiz352 = _open_wizard(line=line352, user=crew)  # crew is chief on source
err, _v = _try(lambda: wiz352.action_confirm())
units352.invalidate_recordset()
ok = err is None and units352[0].state == "active"
print("  err:", type(err).__name__ if err else None)
print("  unit state:", units352[0].state, "(want active)")
print("T352:", "PASS" if ok else "FAIL")
results["T352"] = ok


# ============================================================
print()
print("=" * 72)
print("T353 - authority — Crew Chief on another event blocked")
print("=" * 72)
line353, units353 = _make_line_with_checked_out_units(qty=1)
wiz353 = _open_wizard(line=line353, user=other_crew)  # chief on other_job
err, _v = _try(lambda: wiz353.action_confirm())
ok = (
    isinstance(err, UserError)
    and "authoris" in str(err).lower()
)
print("  raised:", type(err).__name__ if err else None)
print("T353:", "PASS" if ok else "FAIL")
results["T353"] = ok


# ============================================================
print()
print("=" * 72)
print("T354 - has_unresolved_missing recomputes incrementally")
print("=" * 72)
line354, units354 = _make_line_with_checked_out_units(qty=3)
source_ej.invalidate_recordset()
state_pre = source_ej.has_unresolved_missing
unresolved_pre = len(source_ej.unresolved_missing_unit_ids)

# Check in unit 1 as 'good' → should be cleared from unresolved
wiz354a = _open_wizard(event_job=source_ej, user=manager)
# Wizard auto-populates ALL non-returned units. Restrict to our 3.
for wl in wiz354a.checkin_line_ids:
    if wl.unit_id.id not in units354.ids:
        wl.unlink()
# Now wizard has 3 lines. Confirm only unit 1 (drop the others)
for wl in wiz354a.checkin_line_ids[1:]:
    wl.unlink()
wiz354a.action_confirm()
source_ej.invalidate_recordset()
units354.invalidate_recordset()
unresolved_after_1 = len(source_ej.unresolved_missing_unit_ids)

# Check in unit 2 as missing+returned_late → also clears
wiz354b = _open_wizard(event_job=source_ej, user=manager)
for wl in wiz354b.checkin_line_ids:
    if wl.unit_id.id not in units354.ids:
        wl.unlink()
# Keep just the line for unit 2 (the still-checked_out one of our trio)
still_out_units = units354.filtered(lambda u: u.state == "checked_out")
keep_unit = still_out_units[0]
for wl in wiz354b.checkin_line_ids:
    if wl.unit_id.id != keep_unit.id:
        wl.unlink()
wiz354b.checkin_line_ids[0].write({
    "condition_at_event": "missing",
    "resolution_path": "returned_late",
    "photo": DUMMY_PHOTO,
})
wiz354b.action_confirm()
source_ej.invalidate_recordset()
units354.invalidate_recordset()
unresolved_after_2 = len(source_ej.unresolved_missing_unit_ids)
# Now: 1 still 'unresolved' = the unit we haven't touched yet
ok = (
    state_pre is True
    and unresolved_pre >= 3
    and unresolved_after_1 == unresolved_pre - 1
    and unresolved_after_2 == unresolved_pre - 2
)
print("  unresolved counts (initial / +1 checked-in / +1 late):",
      unresolved_pre, unresolved_after_1, unresolved_after_2)
print("T354:", "PASS" if ok else "FAIL")
results["T354"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T340", "T341", "T342", "T343", "T344", "T345", "T346",
         "T347", "T348", "T349", "T350", "T351", "T352", "T353",
         "T354"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
