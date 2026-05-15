"""P5.M5 smoke — equipment lines, auto-reservation, unit allocation,
checkout with authority enforcement, movement audit, atomic rollback.

T300 create equipment.line on event_job → state='planned', co=0
T301 auto-create reservations on new event_job creation
T302 reservation.unit_id NULL ok in soft_hold; write confirmed raises
T303 line.action_allocate_units binds units to reservations
T304 line.action_allocate_units fails when not enough units available
T305 checkout authority — manager passes
T306 checkout authority — Lead Tech (crew_leader group) passes
T307 checkout authority — Crew Chief on THIS event_job passes
T308 checkout authority — Crew Chief on ANOTHER job blocked
T309 checkout authority — regular crew (no chief flag) blocked
T310 checkout creates one movement record per reservation
T311 atomic checkout rolls back when one unit is in wrong state
T312 reservation moves confirmed → fulfilled; line moves planned → fulfilled
"""
from odoo.exceptions import UserError, ValidationError


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

manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
lead = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
crew = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
other_crew = env["res.users"].search([("login", "=", "p2m75_other")], limit=1)
sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
print("users found:", bool(manager), bool(lead), bool(crew),
      bool(other_crew), bool(sales))

ej = EventJob.sudo().search([], limit=1, order="id desc")
parent_job = ej.commercial_job_id
assert ej and parent_job, "Need an event_job with a parent commercial_job"
print("ej:", ej.name, " parent_job:", parent_job.name)

# Reserve a second commercial_job for T308's "other job" chief check
other_job = env["commercial.job"].sudo().search(
    [("id", "!=", parent_job.id)], limit=1, order="id")
assert other_job, "Need a second commercial_job for T308"

# Make p2m75_crew Crew Chief on parent_job; p2m75_other Crew Chief on
# other_job. The crew table has UNIQUE(job_id, partner_id), so we
# upsert: update existing rows when present, create new ones when not.
# All changes roll back via env.cr.rollback() at the end of the smoke.
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

# Test products — testing-kit lighting products each have ~8 serial
# units. Authority + checkout tests below allocate ~3 units each and
# CONSUME them (checkout moves units 'reserved' → 'checked_out', no
# easy way to recycle). Build a pool of products with ≥3 active units
# so each test gets its own product slice.
def _find_product_pool(min_units, target_count):
    found = []
    for p in Product.sudo().search([
            ("is_workshop_item", "=", True),
            ("tracking_mode", "=", "serial"),
            # Skip smoke leftovers from earlier P5 milestones
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

products_pool = _find_product_pool(min_units=3, target_count=12)
assert len(products_pool) >= 10, (
    "Need ≥10 distinct serial products with ≥3 active units "
    "(7 for T305-T312 + 1 primary + 2 for T317/T318); "
    "got %d. Re-run the testing kit." % len(products_pool))
product = products_pool[0]  # used by T300 / T301 / T303
_pool_iter = iter(products_pool[1:])
print("product pool:", [p.workshop_name or p.name
                        for p in products_pool])
print("primary product:", product.workshop_name or product.name)

# Clean any prior P5M5 lines on these event_jobs. Also sweep any
# orphan movements left from earlier smoke iterations that aborted
# before reaching the trailing rollback — those rows pin the test
# users via actor_id FK and break unrelated suites' user teardown.
Line.sudo().search([
    ("event_job_id", "in", (ej.id,)),
    ("product_template_id", "=", product.id),
]).unlink()
orphan_mvts = Movement.sudo().search(
    [("actor_id", "in", (manager.id, lead.id, crew.id,
                         other_crew.id, sales.id))])
if orphan_mvts:
    orphan_mvts.with_context(_allow_movement_write=True).unlink()
env.cr.commit()


# ============================================================
print()
print("=" * 72)
print("T300 - create equipment.line on event_job")
print("=" * 72)
line300 = Line.sudo().create({
    "event_job_id": ej.id,
    "product_template_id": product.id,
    "quantity_planned": 3,
})
ok = (
    line300.state == "planned"
    and line300.quantity_checked_out == 0
    and line300.quantity_remaining == 3
)
print("  state:", line300.state, "(want planned)")
print("  qty_checked_out:", line300.quantity_checked_out, "(want 0)")
print("  qty_remaining:", line300.quantity_remaining, "(want 3)")
print("T300:", "PASS" if ok else "FAIL")
results["T300"] = ok


# ============================================================
print()
print("=" * 72)
print("T301 - auto-create reservations on new event_job creation")
print("=" * 72)
ej_new = EventJob.sudo().create({
    "commercial_job_id": parent_job.id,
    "equipment_line_ids": [(0, 0, {
        "product_template_id": product.id,
        "quantity_planned": 3,
    })],
})
ej_new.invalidate_recordset()
new_lines = ej_new.equipment_line_ids
new_reservations = new_lines.mapped("reservation_ids")
ok = (
    len(new_lines) == 1
    and len(new_reservations) == 3
    and all(r.state == "soft_hold" for r in new_reservations)
    and all(not r.unit_id for r in new_reservations)
)
print("  lines:", len(new_lines), "(want 1)")
print("  reservations:", len(new_reservations), "(want 3)")
print("  states:", [r.state for r in new_reservations])
print("  unit_ids set?:", [bool(r.unit_id) for r in new_reservations])
print("T301:", "PASS" if ok else "FAIL")
results["T301"] = ok


# ============================================================
print()
print("=" * 72)
print("T302 - reservation.unit_id relaxed in soft_hold; required for confirmed")
print("=" * 72)
# A unit-less soft_hold already exists from T301. Try to flip its
# state directly to 'confirmed' without setting unit_id.
r302 = new_reservations[0]
err, _v = _try(lambda: r302.write({"state": "confirmed"}))
ok = (
    isinstance(err, (UserError, ValidationError))
    and "unit" in str(err).lower()
)
print("  unit-less soft_hold exists?",
      r302.state == "soft_hold" and not r302.unit_id)
print("  confirm without unit raised:",
      type(err).__name__ if err else None)
print("T302:", "PASS" if ok else "FAIL")
results["T302"] = ok


# ============================================================
print()
print("=" * 72)
print("T303 - line.action_allocate_units binds units to reservations")
print("=" * 72)
# Use new_lines[0] from T301 which has 3 unit-less soft_holds
line303 = new_lines[0]
err, bound = _try(lambda: line303.action_allocate_units())
line303.invalidate_recordset()
bound_count = len(bound) if bound else 0
ok = (
    err is None
    and bound_count == 3
    and all(r.unit_id for r in line303.reservation_ids)
    and all(r.state == "confirmed" for r in line303.reservation_ids)
)
print("  err:", type(err).__name__ if err else None)
print("  bound:", bound_count, "(want 3)")
print("  unit_ids:",
      [r.unit_id.serial_number for r in line303.reservation_ids])
print("  states:",
      [r.state for r in line303.reservation_ids])
print("T303:", "PASS" if ok else "FAIL")
results["T303"] = ok


# ============================================================
print()
print("=" * 72)
print("T304 - allocate fails when not enough units available")
print("=" * 72)
# Find a product with very few units, build a line with planned >
# than available
small_product = Product.sudo().search([
    ("is_workshop_item", "=", True),
    ("tracking_mode", "=", "serial"),
], limit=1, order="id desc")
# Use an absurdly large planned qty to guarantee shortfall
line304_ej = EventJob.sudo().create({
    "commercial_job_id": parent_job.id,
    "equipment_line_ids": [(0, 0, {
        "product_template_id": small_product.id,
        "quantity_planned": 9999,
    })],
})
line304 = line304_ej.equipment_line_ids
err, _v = _try(lambda: line304.action_allocate_units())
ok = isinstance(err, UserError) and "unit" in str(err).lower()
print("  raised:", type(err).__name__ if err else None)
print("  msg excerpt:", (str(err) or "")[:120])
print("T304:", "PASS" if ok else "FAIL")
results["T304"] = ok


# ============================================================
# Helper: build a fresh allocated line for each authority test so
# checkout in one test doesn't pollute the next. Each call consumes
# a distinct product from the pool so allocations don't collide
# (checkout moves units to 'checked_out' and there's no recycle path
# within the smoke).
def _make_allocated_line(qty=3, event_job=None):
    target_ej = event_job or ej
    p = next(_pool_iter)
    # Post-hotfix (17.0.4.0.7): line.create() now auto-spawns
    # quantity_planned soft_hold reservations. No manual seeding
    # required — just create the line and allocate.
    line = Line.sudo().create({
        "event_job_id": target_ej.id,
        "product_template_id": p.id,
        "quantity_planned": qty,
    })
    line.action_allocate_units()
    return line


# ============================================================
print()
print("=" * 72)
print("T305 - checkout authority — manager passes")
print("=" * 72)
line305 = _make_allocated_line()
err, _v = _try(lambda: line305.with_user(manager).action_checkout())
line305.invalidate_recordset()
ok = (
    err is None
    and line305.quantity_checked_out == 3
    and line305.state == "fulfilled"
)
print("  err:", type(err).__name__ if err else None)
print("  qty_checked_out:", line305.quantity_checked_out)
print("  state:", line305.state)
print("T305:", "PASS" if ok else "FAIL")
results["T305"] = ok


# ============================================================
print()
print("=" * 72)
print("T306 - checkout authority — Lead Tech (crew_leader) passes")
print("=" * 72)
line306 = _make_allocated_line()
err, _v = _try(lambda: line306.with_user(lead).action_checkout())
ok = err is None
print("  err:", type(err).__name__ if err else None)
print("T306:", "PASS" if ok else "FAIL")
results["T306"] = ok


# ============================================================
print()
print("=" * 72)
print("T307 - checkout authority — Crew Chief on this event passes")
print("=" * 72)
line307 = _make_allocated_line()
err, _v = _try(lambda: line307.with_user(crew).action_checkout())
ok = err is None
print("  err:", type(err).__name__ if err else None)
print("T307:", "PASS" if ok else "FAIL")
results["T307"] = ok


# ============================================================
print()
print("=" * 72)
print("T308 - checkout authority — Crew Chief on another job blocked")
print("=" * 72)
line308 = _make_allocated_line()
err, _v = _try(lambda: line308.with_user(other_crew).action_checkout())
ok = isinstance(err, UserError) and "authoris" in str(err).lower()
print("  raised:", type(err).__name__ if err else None)
print("T308:", "PASS" if ok else "FAIL")
results["T308"] = ok


# ============================================================
print()
print("=" * 72)
print("T309 - checkout authority — regular crew (no chief) blocked")
print("=" * 72)
# Re-use sales who is NOT a chief and NOT in manager/crew_leader
line309 = _make_allocated_line()
err, _v = _try(lambda: line309.with_user(sales).action_checkout())
ok = isinstance(err, UserError) and "authoris" in str(err).lower()
print("  raised:", type(err).__name__ if err else None)
print("T309:", "PASS" if ok else "FAIL")
results["T309"] = ok


# ============================================================
print()
print("=" * 72)
print("T310 - checkout creates one movement record per reservation")
print("=" * 72)
line310 = _make_allocated_line()
res_ids = line310.reservation_ids.ids
line310.with_user(manager).action_checkout()
movements = Movement.sudo().search([
    ("reservation_id", "in", res_ids),
    ("movement_type", "=", "checkout"),
])
ok = (
    len(movements) == 3
    and all(m.name.startswith("MV-") for m in movements)
    and all(m.actor_id == manager for m in movements)
)
print("  movements:", len(movements), "(want 3)")
print("  sample name:", movements[0].name if movements else None)
print("T310:", "PASS" if ok else "FAIL")
results["T310"] = ok


# ============================================================
print()
print("=" * 72)
print("T311 - atomic rollback when one unit is in wrong state")
print("=" * 72)
line311 = _make_allocated_line()
# Manually move one unit out of 'reserved' → 'maintenance' so
# unit._do_transition('checked_out') raises mid-batch
bad_unit = line311.reservation_ids[0].unit_id
bad_unit._do_transition("maintenance")
movements_before = Movement.sudo().search_count([
    ("equipment_line_id", "=", line311.id)])
err, _v = _try(lambda: line311.with_user(manager).action_checkout())
line311.invalidate_recordset()
movements_after = Movement.sudo().search_count([
    ("equipment_line_id", "=", line311.id)])
ok = (
    err is not None
    and movements_after == movements_before
    and all(r.state == "confirmed" for r in line311.reservation_ids)
)
print("  raised:", type(err).__name__ if err else None)
print("  movements before:", movements_before,
      " after:", movements_after, "(want equal)")
print("  reservation states (all confirmed?):",
      sorted(set(line311.reservation_ids.mapped("state"))))
print("T311:", "PASS" if ok else "FAIL")
results["T311"] = ok


# ============================================================
print()
print("=" * 72)
print("T312 - state transitions: reservation + line on checkout")
print("=" * 72)
line312 = _make_allocated_line()
res_states_before = sorted(set(line312.reservation_ids.mapped("state")))
unit_states_before = sorted(set(line312.reservation_ids.mapped("unit_id.state")))
line312.with_user(manager).action_checkout()
line312.invalidate_recordset()
res_states_after = sorted(set(line312.reservation_ids.mapped("state")))
unit_states_after = sorted(set(line312.reservation_ids.mapped("unit_id.state")))
ok = (
    res_states_before == ["confirmed"]
    and res_states_after == ["fulfilled"]
    and unit_states_before == ["reserved"]
    and unit_states_after == ["checked_out"]
    and line312.state == "fulfilled"
)
print("  res states:", res_states_before, "->", res_states_after)
print("  unit states:", unit_states_before, "->", unit_states_after)
print("  line state:", line312.state, "(want fulfilled)")
print("T312:", "PASS" if ok else "FAIL")
results["T312"] = ok


# ============================================================
# P5.M5 hotfix (17.0.4.0.7) — auto-reservation on line.create() +
# write() reconciliation when quantity_planned changes.
# ============================================================
print()
print("=" * 72)
print("T313 - auto-reservation fires when a line is added to an existing event_job")
print("=" * 72)
ej_t313 = EventJob.sudo().create({
    "commercial_job_id": parent_job.id,
})
line313 = Line.sudo().create({
    "event_job_id": ej_t313.id,
    "product_template_id": product.id,
    "quantity_planned": 3,
})
line313.invalidate_recordset()
ok = (
    len(line313.reservation_ids) == 3
    and all(r.state == "soft_hold" for r in line313.reservation_ids)
    and all(not r.unit_id for r in line313.reservation_ids)
    and all(r.equipment_line_id == line313 for r in line313.reservation_ids)
)
print("  reservations:", len(line313.reservation_ids), "(want 3)")
print("  states:", [r.state for r in line313.reservation_ids])
print("  unit_ids:", [bool(r.unit_id) for r in line313.reservation_ids])
print("T313:", "PASS" if ok else "FAIL")
results["T313"] = ok


# ============================================================
print()
print("=" * 72)
print("T314 - autocreate is idempotent (calling twice doesn't double up)")
print("=" * 72)
ej_t313._autocreate_reservations_for_lines(line313)
line313.invalidate_recordset()
ok = len(line313.reservation_ids) == 3  # still 3, not 6
print("  reservations after 2nd call:",
      len(line313.reservation_ids), "(want 3)")
print("T314:", "PASS" if ok else "FAIL")
results["T314"] = ok


# ============================================================
print()
print("=" * 72)
print("T315 - quantity UP spawns extra soft_holds (3 -> 5)")
print("=" * 72)
line315 = Line.sudo().create({
    "event_job_id": ej_t313.id,
    "product_template_id": product.id,
    "quantity_planned": 3,
})
before = len(line315.reservation_ids)
line315.write({"quantity_planned": 5})
line315.invalidate_recordset()
after = len(line315.reservation_ids)
soft_holds = line315.reservation_ids.filtered(lambda r: r.state == "soft_hold")
ok = before == 3 and after == 5 and len(soft_holds) == 5
print("  reservations: ", before, "->", after, "(want 3->5)")
print("  all soft_hold?", len(soft_holds) == 5)
print("T315:", "PASS" if ok else "FAIL")
results["T315"] = ok


# ============================================================
print()
print("=" * 72)
print("T316 - quantity DOWN cancels open soft_holds (3 -> 1)")
print("=" * 72)
line316 = Line.sudo().create({
    "event_job_id": ej_t313.id,
    "product_template_id": product.id,
    "quantity_planned": 3,
})
line316.write({"quantity_planned": 1})
line316.invalidate_recordset()
states = [r.state for r in line316.reservation_ids]
soft = [s for s in states if s == "soft_hold"]
cancelled = [s for s in states if s == "cancelled"]
ok = len(soft) == 1 and len(cancelled) == 2
print("  states:", sorted(states), "(want 1 soft_hold + 2 cancelled)")
print("T316:", "PASS" if ok else "FAIL")
results["T316"] = ok


# ============================================================
print()
print("=" * 72)
print("T317 - quantity DOWN cancels OPEN soft_holds preferentially "
      "(allocated preserved)")
print("=" * 72)
# Pick a product from the pool that still has ≥2 active units
p_t317 = next(_pool_iter)
line317 = Line.sudo().create({
    "event_job_id": ej_t313.id,
    "product_template_id": p_t317.id,
    "quantity_planned": 3,
})
# Partially allocate: bind 2 units, leaving 1 open soft_hold
two_units_t317 = Unit.sudo().search([
    ("product_template_id", "=", p_t317.id),
    ("state", "=", "active"),
], limit=2)
line317._bind_units_to_reservations(two_units_t317)
line317.invalidate_recordset()
# Pre-state: 2 confirmed (with units) + 1 open soft_hold
pre_states = sorted([(r.state, bool(r.unit_id))
                     for r in line317.reservation_ids])
# Now shrink to 2 — should cancel the lone soft_hold, leave confirmed alone
line317.write({"quantity_planned": 2})
line317.invalidate_recordset()
post = line317.reservation_ids
post_confirmed = post.filtered(
    lambda r: r.state == "confirmed" and r.unit_id)
post_cancelled = post.filtered(lambda r: r.state == "cancelled")
post_soft_hold = post.filtered(lambda r: r.state == "soft_hold")
ok = (
    len(post_confirmed) == 2
    and len(post_cancelled) == 1
    and len(post_soft_hold) == 0
)
print("  pre-state:", pre_states)
print("  post-state: confirmed=%d cancelled=%d soft_hold=%d" % (
    len(post_confirmed), len(post_cancelled), len(post_soft_hold)))
print("T317:", "PASS" if ok else "FAIL")
results["T317"] = ok


# ============================================================
print()
print("=" * 72)
print("T318 - quantity DOWN below allocated raises UserError")
print("=" * 72)
p_t318 = next(_pool_iter)
line318 = Line.sudo().create({
    "event_job_id": ej_t313.id,
    "product_template_id": p_t318.id,
    "quantity_planned": 3,
})
two_units_t318 = Unit.sudo().search([
    ("product_template_id", "=", p_t318.id),
    ("state", "=", "active"),
], limit=2)
line318._bind_units_to_reservations(two_units_t318)
line318.invalidate_recordset()
# 2 confirmed (allocated) + 1 open soft_hold; try to shrink to 1
err, _v = _try(lambda: line318.write({"quantity_planned": 1}))
line318.invalidate_recordset()
post_states = sorted(line318.reservation_ids.mapped("state"))
ok = (
    isinstance(err, UserError)
    and "allocated" in str(err).lower()
    and line318.quantity_planned == 3  # unchanged
    and post_states == ["confirmed", "confirmed", "soft_hold"]
)
print("  raised:", type(err).__name__ if err else None)
print("  msg excerpt:", (str(err) or "")[:140])
print("  qty_planned after (want unchanged 3):", line318.quantity_planned)
print("  reservation states (want unchanged):", post_states)
print("T318:", "PASS" if ok else "FAIL")
results["T318"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T300", "T301", "T302", "T303", "T304", "T305", "T306",
         "T307", "T308", "T309", "T310", "T311", "T312",
         "T313", "T314", "T315", "T316", "T317", "T318"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
