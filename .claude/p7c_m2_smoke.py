"""Phase 7c M2 smoke -- booking model + state machine +
ACLs (11 tests).

T7c200 - booking creates with required fields
T7c201 - reference auto-generates BKG-YYYY-NNN
T7c202 - cost_amount field carries groups attribute
T7c203 - invalid state transition raises UserError
T7c204 - cost_amount negative -> ValidationError
T7c205 - scheduled_date in past -> UserError on submit
T7c206 - vendor.booking_count reflects real bookings
T7c207 - crew tier sees only own booking
T7c208 - crew tier cannot see another crew's booking
T7c209 - bookkeeper reads all + sees cost
T7c210 - lead_tech cannot see cost field (groups attr)
"""
from datetime import date, timedelta

from odoo.exceptions import (
    AccessError, UserError, ValidationError)


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Booking = env["neon.external.training.booking"]
Vendor = env["neon.external.training.vendor"]
Users = env["res.users"]


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


def _get_or_create_user(login, name, group_xmlid):
    u = Users.sudo().search(
        [("login", "=", login)], limit=1)
    if not u:
        u = Users.sudo().create({
            "name": name, "login": login,
            "password": "test123",
            "email": login + "@example.test",
        })
    elif not u.email:
        u.sudo().email = login + "@example.test"
    g = env.ref(group_xmlid, raise_if_not_found=False)
    if g and u not in g.users:
        g.sudo().write({"users": [(4, u.id)]})
    return u


u_super = _get_or_create_user(
    "p7c_m2_super", "P7c M2 Super",
    "neon_core.group_neon_superuser")
u_book = _get_or_create_user(
    "p7c_m2_book", "P7c M2 Book",
    "neon_core.group_neon_bookkeeper")
u_lead = _get_or_create_user(
    "p7c_m2_lead", "P7c M2 Lead",
    "neon_core.group_neon_lead_tech")
u_crew_a = _get_or_create_user(
    "p7c_m2_crew_a", "P7c M2 Crew A",
    "base.group_user")
u_crew_b = _get_or_create_user(
    "p7c_m2_crew_b", "P7c M2 Crew B",
    "base.group_user")
env.cr.commit()

vendor = env.ref("neon_external_training.vendor_vid")
tomorrow = date.today() + timedelta(days=1)


def _new_booking(crew_user=None, **vals):
    base = {
        "vendor_id": vendor.id,
        "course_name": "M2 probe course",
        "crew_user_id": (crew_user or u_crew_a).id,
        "scheduled_date": tomorrow,
    }
    base.update(vals)
    return Booking.sudo().create(base)


# ============================================================
print()
print("T7c200 - booking creates with required fields")
print("=" * 72)
b = _new_booking()
ok = (bool(b.id)
      and b.vendor_id == vendor
      and b.crew_user_id == u_crew_a
      and b.state == "draft")
print(f"  id: {b.id}, state: {b.state}")
print("T7c200:", "PASS" if ok else "FAIL")
results["T7c200"] = ok


# ============================================================
print()
print("T7c201 - reference auto-generates BKG-YYYY-NNN")
print("=" * 72)
import re
ok = (bool(b.reference)
      and re.match(r"^BKG-\d{4}-\d{3,}$", b.reference)
      is not None)
print(f"  reference: {b.reference!r}")
print("T7c201:", "PASS" if ok else "FAIL")
results["T7c201"] = ok


# ============================================================
print()
print("T7c202 - cost_amount field has groups attribute")
print("=" * 72)
cost_field = Booking._fields["cost_amount"]
groups = cost_field.groups or ""
ok = ("group_neon_superuser" in groups
      and "group_neon_bookkeeper" in groups)
print(f"  groups attr: {groups!r}")
print("T7c202:", "PASS" if ok else "FAIL")
results["T7c202"] = ok


# ============================================================
print()
print("T7c203 - invalid state transition raises UserError")
print("=" * 72)
b2 = _new_booking()
err, _v = _try(lambda: b2._transition_to("completed"))
ok = isinstance(err, UserError)
print(f"  UserError raised: {isinstance(err, UserError)}")
print(f"  msg: {str(err)[:140] if err else None}")
print("T7c203:", "PASS" if ok else "FAIL")
results["T7c203"] = ok


# ============================================================
print()
print("T7c204 - cost_amount negative -> ValidationError")
print("=" * 72)
err, _v = _try(lambda: _new_booking(cost_amount=-50.0))
ok = isinstance(err, ValidationError)
print(f"  ValidationError raised: "
      f"{isinstance(err, ValidationError)}")
print("T7c204:", "PASS" if ok else "FAIL")
results["T7c204"] = ok


# ============================================================
print()
print("T7c205 - scheduled_date in past -> UserError on submit")
print("=" * 72)
yesterday = date.today() - timedelta(days=1)
b_past = _new_booking(scheduled_date=yesterday)
err, _v = _try(lambda: b_past.action_submit_for_approval())
ok = isinstance(err, UserError)
print(f"  UserError raised: {isinstance(err, UserError)}")
print(f"  msg: {str(err)[:140] if err else None}")
print("T7c205:", "PASS" if ok else "FAIL")
results["T7c205"] = ok


# ============================================================
print()
print("T7c206 - vendor.booking_count reflects real bookings")
print("=" * 72)
before = vendor.booking_count
_b1 = _new_booking()
_b2 = _new_booking()
vendor.invalidate_recordset(["booking_count"])
after = vendor.booking_count
ok = after == before + 2
print(f"  before: {before}, after: {after} (expect +2)")
print("T7c206:", "PASS" if ok else "FAIL")
results["T7c206"] = ok


# ============================================================
print()
print("T7c207 - crew tier sees only own booking")
print("=" * 72)
b_a = _new_booking(crew_user=u_crew_a,
                   course_name="A's booking")
b_b = _new_booking(crew_user=u_crew_b,
                   course_name="B's booking")
env.cr.commit()
visible = Booking.with_user(u_crew_a).search(
    [("course_name", "in", ["A's booking", "B's booking"])])
ok = (b_a in visible
      and b_b not in visible)
print(f"  crew_a sees own (A): {b_a in visible}")
print(f"  crew_a blocked from B: {b_b not in visible}")
print("T7c207:", "PASS" if ok else "FAIL")
results["T7c207"] = ok


# ============================================================
print()
print("T7c208 - crew tier cannot see another crew's booking")
print("=" * 72)
err, _v = _try(lambda: b_b.with_user(u_crew_a).read(
    ["course_name"]))
# The record may simply be filtered out (returns empty) or
# raise AccessError; either is acceptable as "cannot see".
filtered_out = False
if err is None:
    visible_b = Booking.with_user(u_crew_a).browse(b_b.id)
    filtered_out = not visible_b.exists() or len(
        Booking.with_user(u_crew_a).search(
            [("id", "=", b_b.id)])) == 0
ok = isinstance(err, AccessError) or filtered_out
print(f"  AccessError or filtered out: {ok}")
print(f"  err: {type(err).__name__ if err else 'None'}")
print("T7c208:", "PASS" if ok else "FAIL")
results["T7c208"] = ok


# ============================================================
print()
print("T7c209 - bookkeeper reads all + sees cost field")
print("=" * 72)
b_paid = _new_booking(cost_amount=250.0)
env.cr.commit()
try:
    with env.cr.savepoint():
        res = b_paid.with_user(u_book).read(
            ["reference", "cost_amount", "currency_id"])
    book_can_read = bool(res)
    book_sees_cost = "cost_amount" in res[0]
except AccessError as e:
    book_can_read = False
    book_sees_cost = False
ok = book_can_read and book_sees_cost
print(f"  book read OK: {book_can_read}")
print(f"  cost_amount in result: {book_sees_cost}")
print("T7c209:", "PASS" if ok else "FAIL")
results["T7c209"] = ok


# ============================================================
print()
print("T7c210 - lead_tech cannot see cost field "
      "(groups attr)")
print("=" * 72)
# Odoo's `groups` attribute on a field excludes it from
# results when the requesting user isn't in any of the
# listed groups. read() called with the field name raises
# AccessError; default read() (no field list) silently
# excludes.
err, val = _try(lambda: b_paid.with_user(u_lead).read(
    ["cost_amount"]))
# Read without specifying cost_amount -- should succeed but
# cost field absent.
res_default = b_paid.with_user(u_lead).read()
cost_absent = "cost_amount" not in (
    res_default[0] if res_default else {})
ok = (isinstance(err, AccessError)
      or (err is None and cost_absent))
print(f"  explicit cost read: "
      f"{type(err).__name__ if err else 'OK (returned)'}")
print(f"  cost_amount absent in default read: {cost_absent}")
print("T7c210:", "PASS" if ok else "FAIL")
results["T7c210"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7c200", "T7c201", "T7c202", "T7c203", "T7c204",
         "T7c205", "T7c206", "T7c207", "T7c208", "T7c209",
         "T7c210"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
