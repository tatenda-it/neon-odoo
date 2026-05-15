"""P5.M4 smoke — equipment reservation + conflict detection +
Action Centre 'equipment_conflict' trigger wiring.

T290 create reservation: state=soft_hold, name RES-NNNNNN
T291 SQL CHECK reserve_from < reserve_to enforced
T292 action_confirm: soft_hold -> confirmed; mail.thread tracks state
T293 action_fulfil: confirmed -> fulfilled
T294 illegal transition: fulfilled -> confirmed raises
T295 overlap on same unit -> has_conflict True on both
T296 no overlap on same unit -> has_conflict False
T297 cancelled peer ignored by conflict detection
T298 Action Centre 'equipment_conflict' item spawned on conflict
T299 Action Centre item auto-closes when conflict resolves
"""
from datetime import datetime
from psycopg2 import IntegrityError
from odoo.exceptions import UserError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Reservation = env["neon.equipment.reservation"]
Unit = env["neon.equipment.unit"]
EventJob = env["commercial.event.job"]
Item = env["action.centre.item"]

# Pick a workable event_job — any existing one works for these tests
ej = EventJob.sudo().search([], limit=1, order="id desc")
assert ej, "No commercial.event.job found — seed something first"
print("event_job:", ej.name, " event_date:", ej.event_date)

# Pick two distinct serial-tracked units for isolation
unit_a = Unit.sudo().search(
    [("serial_number", "!=", False)], limit=1, order="id")
unit_b = Unit.sudo().search(
    [("serial_number", "!=", False), ("id", "!=", unit_a.id)],
    limit=1, order="id")
assert unit_a and unit_b, "Need two distinct units; testing kit not seeded?"
print("unit_a:", unit_a.display_name, " unit_b:", unit_b.display_name)

# Clean any prior P5M4 reservations on these units so reruns are clean
prior = Reservation.sudo().search([
    ("unit_id", "in", (unit_a.id, unit_b.id)),
    ("event_job_id", "=", ej.id),
])
prior.unlink()
env.cr.commit()


# Tiny helper — datetimes are easier to read this way
def DT(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001 — broad on purpose
        return (e, None)


# ============================================================
print()
print("=" * 72)
print("T290 - create reservation: state=soft_hold, name RES-NNNNNN")
print("=" * 72)
r290 = Reservation.sudo().create({
    "event_job_id": ej.id,
    "unit_id": unit_a.id,
    "reserve_from": DT("2026-06-01 08:00:00"),
    "reserve_to": DT("2026-06-02 18:00:00"),
})
ok = (
    r290.state == "soft_hold"
    and r290.name.startswith("RES-")
    and len(r290.name) >= 8  # "RES-" + 4+ digits
)
print("  name:", r290.name, "(want RES-NNNNNN)")
print("  state:", r290.state, "(want soft_hold)")
print("T290:", "PASS" if ok else "FAIL")
results["T290"] = ok


# ============================================================
print()
print("=" * 72)
print("T291 - SQL CHECK: reserve_from >= reserve_to raises")
print("=" * 72)
err, _v = _try(lambda: Reservation.sudo().create({
    "event_job_id": ej.id,
    "unit_id": unit_a.id,
    "reserve_from": DT("2026-06-05 18:00:00"),
    "reserve_to": DT("2026-06-05 08:00:00"),  # before reserve_from
}))
ok = (
    isinstance(err, IntegrityError)
    or (err and "check_dates" in str(err).lower())
    or (err and "reservation start" in str(err).lower())
)
print("  raised:", type(err).__name__ if err else None)
print("  msg excerpt:", (str(err) or "")[:120])
print("T291:", "PASS" if ok else "FAIL")
results["T291"] = ok


# ============================================================
print()
print("=" * 72)
print("T292 - action_confirm: soft_hold -> confirmed")
print("=" * 72)
msg_count_pre = len(r290.message_ids)
r290.action_confirm()
env.cr.precommit.run()  # flush mail.thread state tracking
r290.invalidate_recordset()
tracking_msgs = r290.message_ids.filtered(
    lambda m: m.tracking_value_ids and any(
        t.field_id.name == "state" for t in m.tracking_value_ids))
ok = (
    r290.state == "confirmed"
    and len(tracking_msgs) >= 1
)
print("  state:", r290.state, "(want confirmed)")
print("  tracking msgs:", len(tracking_msgs))
print("T292:", "PASS" if ok else "FAIL")
results["T292"] = ok


# ============================================================
print()
print("=" * 72)
print("T293 - action_fulfil: confirmed -> fulfilled")
print("=" * 72)
r290.action_fulfil()
r290.invalidate_recordset()
ok = r290.state == "fulfilled"
print("  state:", r290.state, "(want fulfilled)")
print("T293:", "PASS" if ok else "FAIL")
results["T293"] = ok


# ============================================================
print()
print("=" * 72)
print("T294 - illegal transition fulfilled -> confirmed raises")
print("=" * 72)
err, _v = _try(lambda: r290._do_transition("confirmed"))
ok = isinstance(err, UserError) and "illegal" in str(err).lower()
print("  raised:", type(err).__name__ if err else None)
print("  msg excerpt:", (str(err) or "")[:120])
print("T294:", "PASS" if ok else "FAIL")
results["T294"] = ok


# ============================================================
print()
print("=" * 72)
print("T295 - overlap on same unit -> has_conflict True on both")
print("=" * 72)
# Use unit_b which has no prior reservations; pick a fresh window
res_a = Reservation.sudo().create({
    "event_job_id": ej.id,
    "unit_id": unit_b.id,
    "reserve_from": DT("2026-06-10 08:00:00"),
    "reserve_to": DT("2026-06-12 18:00:00"),
    "state": "confirmed",
})
res_b = Reservation.sudo().create({
    "event_job_id": ej.id,
    "unit_id": unit_b.id,
    "reserve_from": DT("2026-06-11 08:00:00"),  # overlaps Mon-Wed
    "reserve_to": DT("2026-06-13 18:00:00"),
    "state": "confirmed",
})
res_a.invalidate_recordset()
res_b.invalidate_recordset()
ok = (
    res_a.has_conflict is True
    and res_b.has_conflict is True
    and res_b in res_a.conflicting_reservation_ids
    and res_a in res_b.conflicting_reservation_ids
)
print("  res_a has_conflict:", res_a.has_conflict, "(want True)")
print("  res_b has_conflict:", res_b.has_conflict, "(want True)")
print("  cross-references:",
      res_b in res_a.conflicting_reservation_ids,
      res_a in res_b.conflicting_reservation_ids)
print("T295:", "PASS" if ok else "FAIL")
results["T295"] = ok


# ============================================================
print()
print("=" * 72)
print("T296 - no overlap on same unit -> has_conflict False")
print("=" * 72)
# Cancel the conflict pair to avoid polluting subsequent tests
res_a.action_cancel()
res_b.action_cancel()
res_a.invalidate_recordset()
res_b.invalidate_recordset()

# Two disjoint windows on unit_b
res_c = Reservation.sudo().create({
    "event_job_id": ej.id,
    "unit_id": unit_b.id,
    "reserve_from": DT("2026-07-01 08:00:00"),
    "reserve_to": DT("2026-07-02 18:00:00"),
    "state": "confirmed",
})
res_d = Reservation.sudo().create({
    "event_job_id": ej.id,
    "unit_id": unit_b.id,
    "reserve_from": DT("2026-07-05 08:00:00"),  # 3 days gap
    "reserve_to": DT("2026-07-06 18:00:00"),
    "state": "confirmed",
})
res_c.invalidate_recordset()
res_d.invalidate_recordset()
ok = (
    res_c.has_conflict is False
    and res_d.has_conflict is False
)
print("  res_c has_conflict:", res_c.has_conflict, "(want False)")
print("  res_d has_conflict:", res_d.has_conflict, "(want False)")
print("T296:", "PASS" if ok else "FAIL")
results["T296"] = ok


# ============================================================
print()
print("=" * 72)
print("T297 - cancelled peer ignored by conflict detection")
print("=" * 72)
res_c.action_cancel()
res_d.action_cancel()

# Fresh pair: confirmed + overlapping-but-cancelled
res_e = Reservation.sudo().create({
    "event_job_id": ej.id,
    "unit_id": unit_b.id,
    "reserve_from": DT("2026-08-01 08:00:00"),
    "reserve_to": DT("2026-08-03 18:00:00"),
    "state": "confirmed",
})
res_f = Reservation.sudo().create({
    "event_job_id": ej.id,
    "unit_id": unit_b.id,
    "reserve_from": DT("2026-08-02 08:00:00"),  # overlaps res_e
    "reserve_to": DT("2026-08-04 18:00:00"),
    "state": "confirmed",
})
# Cancel the second one — res_e's has_conflict should drop to False
res_f.action_cancel()
res_e.invalidate_recordset()
res_f.invalidate_recordset()
ok = (
    res_e.has_conflict is False  # cancelled peer doesn't count
    and res_f.has_conflict is False  # cancelled itself
)
print("  res_e has_conflict (confirmed):", res_e.has_conflict, "(want False)")
print("  res_f has_conflict (cancelled):", res_f.has_conflict, "(want False)")
print("T297:", "PASS" if ok else "FAIL")
results["T297"] = ok


# ============================================================
print()
print("=" * 72)
print("T298 - Action Centre 'equipment_conflict' item spawned")
print("=" * 72)
res_e.action_cancel()  # clean res_e too

# Now create a fresh overlap to spawn the trigger
res_g = Reservation.sudo().create({
    "event_job_id": ej.id,
    "unit_id": unit_b.id,
    "reserve_from": DT("2026-09-10 08:00:00"),
    "reserve_to": DT("2026-09-12 18:00:00"),
    "state": "confirmed",
})
res_h = Reservation.sudo().create({
    "event_job_id": ej.id,
    "unit_id": unit_b.id,
    "reserve_from": DT("2026-09-11 08:00:00"),
    "reserve_to": DT("2026-09-13 18:00:00"),
    "state": "confirmed",
})
source_model = env["ir.model"].sudo()._get("neon.equipment.reservation")
items_g = Item.sudo().search([
    ("trigger_type", "=", "equipment_conflict"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", res_g.id),
    ("state", "in", ("open", "in_progress")),
])
items_h = Item.sudo().search([
    ("trigger_type", "=", "equipment_conflict"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", res_h.id),
    ("state", "in", ("open", "in_progress")),
])
ok = bool(items_g) and bool(items_h)
print("  items on res_g:", len(items_g), "(want >=1)")
print("  items on res_h:", len(items_h), "(want >=1)")
if items_g:
    print("  sample title:", items_g[0].title)
print("T298:", "PASS" if ok else "FAIL")
results["T298"] = ok


# ============================================================
print()
print("=" * 72)
print("T299 - Action Centre item auto-closes when conflict resolves")
print("=" * 72)
res_h.action_cancel()
res_g.invalidate_recordset()
# Reservation should no longer have conflict; its open item should
# have auto-closed (alert with auto_close_when_condition_clears=True).
items_g_after = Item.sudo().search([
    ("trigger_type", "=", "equipment_conflict"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", res_g.id),
    ("state", "in", ("open", "in_progress")),
])
items_g_closed = Item.sudo().search([
    ("trigger_type", "=", "equipment_conflict"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", res_g.id),
    ("state", "=", "cancelled"),
])
ok = (
    res_g.has_conflict is False
    and not items_g_after
    and bool(items_g_closed)
)
print("  res_g.has_conflict:", res_g.has_conflict, "(want False)")
print("  open items on res_g:", len(items_g_after), "(want 0)")
print("  closed items on res_g:", len(items_g_closed), "(want >=1)")
print("T299:", "PASS" if ok else "FAIL")
results["T299"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T290", "T291", "T292", "T293", "T294", "T295", "T296",
         "T297", "T298", "T299"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
