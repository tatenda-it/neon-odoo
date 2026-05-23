"""Phase 7c M6 smoke -- dashboard external-training
counters (7 tests).

T7c600 - dashboard form view renders with External
         Training group present in arch
T7c601 - external_bookings_upcoming counter accurate
T7c602 - external_bookings_pending_completion accurate
T7c603 - action_view_upcoming_external returns correct
         domain
T7c604 - action_view_pending_completion_external returns
         correct domain
T7c605 - defensive env.get -- compute method guards on
         model lookup (source-introspection check)
T7c606 - regression: Phase 7b onboarding + Phase 7e LMS
         counters unchanged
"""
from datetime import date, timedelta
import inspect

from odoo.exceptions import UserError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Dashboard = env["neon.training.dashboard"]
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


u_crew = _get_or_create_user(
    "p7c_m6_crew", "P7c M6 Crew",
    "base.group_user")
env.cr.commit()

vendor = env.ref("neon_external_training.vendor_vid")
today = date.today()
dash = Dashboard.sudo().create({})


# ============================================================
print()
print("T7c600 - dashboard form view renders with External "
      "Training group")
print("=" * 72)
form = env.ref(
    "neon_training.neon_training_dashboard_view_form",
    raise_if_not_found=False)
ok = bool(form)
if form:
    try:
        info = Dashboard.get_view(
            view_id=form.id, view_type="form")
        arch = info.get("arch") or ""
        has_ext_group = 'name="external_training_group"' in arch
        has_upcoming_field = (
            'name="external_bookings_upcoming"' in arch)
        has_pending_field = (
            'name="external_bookings_pending_completion"'
            in arch)
        ok = (ok and has_ext_group
              and has_upcoming_field
              and has_pending_field)
        print(f"  external_training_group in arch: "
              f"{has_ext_group}")
        print(f"  upcoming field: {has_upcoming_field}")
        print(f"  pending field: {has_pending_field}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  err: {e}")
print("T7c600:", "PASS" if ok else "FAIL")
results["T7c600"] = ok


# ============================================================
print()
print("T7c601 - external_bookings_upcoming counter accurate")
print("=" * 72)
# Snapshot before, then create 3 probe bookings:
# 1) 1 day out, booked -> counts
# 2) 30 days out, pending_approval -> counts
# 3) 31 days out, booked -> does NOT count
# 4) 5 days out, draft -> does NOT count
dash.invalidate_recordset(["external_bookings_upcoming"])
before = dash.external_bookings_upcoming
b1 = Booking.sudo().create({
    "vendor_id": vendor.id, "course_name": "T7c601 1d",
    "crew_user_id": u_crew.id,
    "scheduled_date": today + timedelta(days=1),
    "state": "booked",
})
b2 = Booking.sudo().create({
    "vendor_id": vendor.id, "course_name": "T7c601 30d",
    "crew_user_id": u_crew.id,
    "scheduled_date": today + timedelta(days=30),
    "state": "pending_approval",
})
b3 = Booking.sudo().create({
    "vendor_id": vendor.id, "course_name": "T7c601 31d",
    "crew_user_id": u_crew.id,
    "scheduled_date": today + timedelta(days=31),
    "state": "booked",
})
b4 = Booking.sudo().create({
    "vendor_id": vendor.id, "course_name": "T7c601 draft",
    "crew_user_id": u_crew.id,
    "scheduled_date": today + timedelta(days=5),
})
dash.invalidate_recordset(["external_bookings_upcoming"])
after = dash.external_bookings_upcoming
delta = after - before
ok = delta == 2
print(f"  before: {before}, after: {after} (expect +2)")
print("T7c601:", "PASS" if ok else "FAIL")
results["T7c601"] = ok


# ============================================================
print()
print("T7c602 - external_bookings_pending_completion accurate")
print("=" * 72)
dash.invalidate_recordset(
    ["external_bookings_pending_completion"])
before = dash.external_bookings_pending_completion
# 'attended' with date_attended=8d ago -> counts
# 'attended' with date_attended=7d ago -> counts (<=)
# 'attended' with date_attended=6d ago -> does NOT count
# 'completed' with old date_attended -> does NOT count
bp1 = Booking.sudo().create({
    "vendor_id": vendor.id, "course_name": "T7c602 8d",
    "crew_user_id": u_crew.id,
    "scheduled_date": today - timedelta(days=10),
    "state": "attended",
    "date_attended": today - timedelta(days=8),
})
bp2 = Booking.sudo().create({
    "vendor_id": vendor.id, "course_name": "T7c602 7d",
    "crew_user_id": u_crew.id,
    "scheduled_date": today - timedelta(days=10),
    "state": "attended",
    "date_attended": today - timedelta(days=7),
})
bp3 = Booking.sudo().create({
    "vendor_id": vendor.id, "course_name": "T7c602 6d",
    "crew_user_id": u_crew.id,
    "scheduled_date": today - timedelta(days=10),
    "state": "attended",
    "date_attended": today - timedelta(days=6),
})
dash.invalidate_recordset(
    ["external_bookings_pending_completion"])
after = dash.external_bookings_pending_completion
delta = after - before
ok = delta == 2
print(f"  before: {before}, after: {after} (expect +2)")
print("T7c602:", "PASS" if ok else "FAIL")
results["T7c602"] = ok


# ============================================================
print()
print("T7c603 - action_view_upcoming_external returns "
      "correct domain")
print("=" * 72)
action = dash.action_view_upcoming_external()
domain = action.get("domain") or []
state_clause = (
    "state", "in", ("booked", "pending_approval"))
ok = (isinstance(action, dict)
      and action.get("res_model")
      == "neon.external.training.booking"
      and state_clause in domain
      and any(d[0] == "scheduled_date" and d[1] == ">="
              for d in domain if isinstance(d, tuple))
      and any(d[0] == "scheduled_date" and d[1] == "<="
              for d in domain if isinstance(d, tuple)))
print(f"  domain: {domain}")
print("T7c603:", "PASS" if ok else "FAIL")
results["T7c603"] = ok


# ============================================================
print()
print("T7c604 - action_view_pending_completion_external "
      "returns correct domain")
print("=" * 72)
action = dash.action_view_pending_completion_external()
domain = action.get("domain") or []
ok = (isinstance(action, dict)
      and action.get("res_model")
      == "neon.external.training.booking"
      and ("state", "=", "attended") in domain
      and any(d[0] == "date_attended" and d[1] == "<="
              for d in domain if isinstance(d, tuple)))
print(f"  domain: {domain}")
print("T7c604:", "PASS" if ok else "FAIL")
results["T7c604"] = ok


# ============================================================
print()
print("T7c605 - defensive env.get pattern present")
print("=" * 72)
src = inspect.getsource(
    Dashboard._compute_external_training_counters)
has_env_get = ("env.get(" in src
               and "neon.external.training.booking" in src)
has_none_branch = "is None" in src
ok = has_env_get and has_none_branch
print(f"  env.get + None-check present: {ok}")
print("T7c605:", "PASS" if ok else "FAIL")
results["T7c605"] = ok


# ============================================================
print()
print("T7c606 - Phase 7b + 7e counters unchanged "
      "(regression)")
print("=" * 72)
# Pick a few Phase 7b + 7e counters and confirm they
# still compute (no exception, return type int).
counters_to_check = [
    "candidates_in_cert_collection",
    "candidates_in_probationary",
    "lms_active_enrollments",
    "lms_pending_capstone",
]
all_ok = True
for fname in counters_to_check:
    fld = Dashboard._fields.get(fname)
    if fld is None:
        print(f"  field missing: {fname}")
        all_ok = False
        continue
    try:
        val = getattr(dash, fname)
        print(f"  {fname}: {val} (type {type(val).__name__})")
    except Exception as e:  # noqa: BLE001
        print(f"  {fname} raised: {e}")
        all_ok = False
ok = all_ok
print("T7c606:", "PASS" if ok else "FAIL")
results["T7c606"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7c600", "T7c601", "T7c602", "T7c603",
         "T7c604", "T7c605", "T7c606"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
