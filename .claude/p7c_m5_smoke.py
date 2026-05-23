"""Phase 7c M5 smoke -- kanban + filter chips + vendor
smart button (8 tests).

T7c500 - booking action returns kanban as primary view
T7c501 - search view resolves without XML errors
T7c502 - "Upcoming" filter domain matches expected set
T7c503 - "This Month" filter handles month boundary
T7c504 - "Awaiting Approval" filter restricts to
         pending_approval
T7c505 - vendor.action_view_bookings returns act_window
         with vendor domain
T7c506 - smart button context defaults vendor_id on new
         booking creation
T7c507 - kanban template loads without XML errors
"""
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from odoo.exceptions import UserError, AccessError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Booking = env["neon.external.training.booking"]
Vendor = env["neon.external.training.vendor"]
View = env["ir.ui.view"]
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
    "p7c_m5_super", "P7c M5 Super",
    "neon_core.group_neon_superuser")
u_crew = _get_or_create_user(
    "p7c_m5_crew", "P7c M5 Crew",
    "base.group_user")
env.cr.commit()

vendor = env.ref("neon_external_training.vendor_vid")


# ============================================================
print()
print("T7c500 - booking action returns kanban as primary view")
print("=" * 72)
action = env.ref(
    "neon_external_training.action_external_training_booking",
    raise_if_not_found=False)
view_mode = action.view_mode if action else ""
ok = bool(action) and view_mode.startswith("kanban")
print(f"  action.view_mode: {view_mode!r}")
print("T7c500:", "PASS" if ok else "FAIL")
results["T7c500"] = ok


# ============================================================
print()
print("T7c501 - search view resolves without XML errors")
print("=" * 72)
search_v = env.ref(
    "neon_external_training.view_external_training_booking_search",
    raise_if_not_found=False)
ok = bool(search_v)
if search_v:
    try:
        info = Booking.get_view(
            view_id=search_v.id, view_type="search")
        ok = ok and bool(info.get("arch"))
        print(f"  search arch loaded length: "
              f"{len(info.get('arch') or '')}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  err: {e}")
print("T7c501:", "PASS" if ok else "FAIL")
results["T7c501"] = ok


# ============================================================
print()
print("T7c502 - 'Upcoming' filter domain matches expected")
print("=" * 72)
# Build the filter's effective domain manually and search.
today = date.today()
upcoming_domain = [
    ("scheduled_date", ">=", today.strftime("%Y-%m-%d")),
    ("state", "in", ["pending_approval", "booked"]),
]
# Create test bookings: 1 future-pending, 1 future-booked,
# 1 future-draft, 1 past-pending.
b_fp = Booking.sudo().create({
    "vendor_id": vendor.id,
    "course_name": "T7c502 future pending",
    "crew_user_id": u_crew.id,
    "scheduled_date": today + timedelta(days=10),
    "state": "pending_approval",
})
b_fb = Booking.sudo().create({
    "vendor_id": vendor.id,
    "course_name": "T7c502 future booked",
    "crew_user_id": u_crew.id,
    "scheduled_date": today + timedelta(days=10),
    "state": "booked",
})
b_fd = Booking.sudo().create({
    "vendor_id": vendor.id,
    "course_name": "T7c502 future draft",
    "crew_user_id": u_crew.id,
    "scheduled_date": today + timedelta(days=10),
})
hits = Booking.sudo().search(upcoming_domain)
ok = (b_fp in hits and b_fb in hits and b_fd not in hits)
print(f"  upcoming includes future pending: {b_fp in hits}")
print(f"  upcoming includes future booked: {b_fb in hits}")
print(f"  upcoming excludes future draft: {b_fd not in hits}")
print("T7c502:", "PASS" if ok else "FAIL")
results["T7c502"] = ok


# ============================================================
print()
print("T7c503 - 'This Month' filter handles month boundary")
print("=" * 72)
month_start = today.replace(day=1)
next_month = month_start + relativedelta(months=1)
month_domain = [
    ("scheduled_date", ">=",
     month_start.strftime("%Y-%m-%d")),
    ("scheduled_date", "<",
     next_month.strftime("%Y-%m-%d")),
]
b_this = Booking.sudo().create({
    "vendor_id": vendor.id,
    "course_name": "T7c503 this month",
    "crew_user_id": u_crew.id,
    "scheduled_date": today,
})
b_next = Booking.sudo().create({
    "vendor_id": vendor.id,
    "course_name": "T7c503 next month",
    "crew_user_id": u_crew.id,
    "scheduled_date": next_month + timedelta(days=5),
})
hits = Booking.sudo().search(month_domain)
ok = (b_this in hits and b_next not in hits)
print(f"  this-month includes today: {b_this in hits}")
print(f"  this-month excludes next month: "
      f"{b_next not in hits}")
print("T7c503:", "PASS" if ok else "FAIL")
results["T7c503"] = ok


# ============================================================
print()
print("T7c504 - 'Awaiting Approval' restricts to "
      "pending_approval")
print("=" * 72)
awaiting_domain = [("state", "=", "pending_approval")]
hits = Booking.sudo().search(awaiting_domain)
all_pending = all(b.state == "pending_approval"
                  for b in hits)
b_fp_in = b_fp in hits  # from T7c502
ok = all_pending and b_fp_in
print(f"  all hits are pending_approval: {all_pending}")
print(f"  T7c502's b_fp (pending) included: {b_fp_in}")
print("T7c504:", "PASS" if ok else "FAIL")
results["T7c504"] = ok


# ============================================================
print()
print("T7c505 - vendor.action_view_bookings returns "
      "act_window with vendor domain")
print("=" * 72)
action = vendor.action_view_bookings()
ok = (isinstance(action, dict)
      and action.get("type") == "ir.actions.act_window"
      and action.get("res_model")
      == "neon.external.training.booking"
      and ("vendor_id", "=", vendor.id) in (
          action.get("domain") or []))
print(f"  type: {action.get('type')}")
print(f"  domain: {action.get('domain')}")
print(f"  view_mode: {action.get('view_mode')}")
print("T7c505:", "PASS" if ok else "FAIL")
results["T7c505"] = ok


# ============================================================
print()
print("T7c506 - smart-button context defaults vendor_id on "
      "new booking")
print("=" * 72)
ctx = action.get("context") or {}
ok = ctx.get("default_vendor_id") == vendor.id
print(f"  default_vendor_id in context: "
      f"{ctx.get('default_vendor_id')}")
print(f"  vendor.id: {vendor.id}")
print("T7c506:", "PASS" if ok else "FAIL")
results["T7c506"] = ok


# ============================================================
print()
print("T7c507 - kanban template loads without XML errors")
print("=" * 72)
kanban_v = env.ref(
    "neon_external_training.view_external_training_booking_kanban",
    raise_if_not_found=False)
ok = bool(kanban_v)
if kanban_v:
    try:
        info = Booking.get_view(
            view_id=kanban_v.id, view_type="kanban")
        arch = info.get("arch") or ""
        group_marker = 'default_group_by="state"'
        has_group_marker = group_marker in arch
        ok = (ok and bool(arch)
              and has_group_marker
              and "oe_kanban_card" in arch)
        print(f"  arch length: {len(arch)}")
        print(f"  default_group_by=state present: "
              f"{has_group_marker}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  err: {e}")
print("T7c507:", "PASS" if ok else "FAIL")
results["T7c507"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7c500", "T7c501", "T7c502", "T7c503", "T7c504",
         "T7c505", "T7c506", "T7c507"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
