"""Phase 7c M7 smoke -- notification stubs + 3d cron
(9 tests).

T7c700 - _notify_booking_confirmed fires on action_approve
         (chatter message on booking with stub marker)
T7c701 - _notify_attendance_recorded fires on
         action_mark_attended
T7c702 - _notify_cert_issued fires on action_mark_cert_issued
T7c703 - stub marker '[Notification stub - Phase 9 will
         send]' present in message bodies (Phase 9 grep
         regression)
T7c704 - channels recorded per event (whatsapp / email /
         both)
T7c705 - _cron_send_3d_reminders selects exactly bookings
         3 days out
T7c706 - cron skips bookings not in 'booked' state
T7c707 - ir.cron record exists + active=True after install
T7c708 - _notify_send uses sudo() on message_post (per
         reference doc)
"""
import inspect
from datetime import date, timedelta

from odoo.exceptions import UserError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Booking = env["neon.external.training.booking"]
Vendor = env["neon.external.training.vendor"]
CertType = env["neon.training.certification.type"]
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
    "p7c_m7_super", "P7c M7 Super",
    "neon_core.group_neon_superuser")
u_crew = _get_or_create_user(
    "p7c_m7_crew", "P7c M7 Crew",
    "base.group_user")
# Robin + Munashe so M3 activity routing doesn't crash
_get_or_create_user(
    "robin@neonhiring.co.zw", "Robin (test)",
    "neon_core.group_neon_superuser")
_get_or_create_user(
    "munashe@neonhiring.co.zw", "Munashe (test)",
    "neon_core.group_neon_superuser")
env.cr.commit()

vendor = env.ref("neon_external_training.vendor_vid")
cert_type = CertType.search([], limit=1)
tomorrow = date.today() + timedelta(days=1)

_STUB_MARKER = "[Notification stub - Phase 9 will send]"


def _new_draft(course="probe"):
    return Booking.sudo().create({
        "vendor_id": vendor.id,
        "course_name": course,
        "crew_user_id": u_crew.id,
        "scheduled_date": tomorrow,
        "cert_type_id": cert_type.id,
    })


def _chatter_bodies(b):
    return [m.body or "" for m in b.message_ids]


# ============================================================
print()
print("T7c700 - _notify_booking_confirmed fires on approve")
print("=" * 72)
b1 = _new_draft(course="T7c700")
b1.with_user(u_crew).action_submit_for_approval()
n_msgs_pre = len(b1.message_ids)
b1.with_user(u_super).action_approve()
new_bodies = _chatter_bodies(b1)
booking_confirmed_msg = [
    m for m in new_bodies
    if "external_booking_confirmed" in m]
ok = bool(booking_confirmed_msg)
print(f"  chatter messages: {len(b1.message_ids)}")
print(f"  booking_confirmed event in chatter: {ok}")
print("T7c700:", "PASS" if ok else "FAIL")
results["T7c700"] = ok


# ============================================================
print()
print("T7c701 - _notify_attendance_recorded fires on attended")
print("=" * 72)
b1.with_user(u_super).action_mark_attended()
new_bodies = _chatter_bodies(b1)
attended_msg = [
    m for m in new_bodies
    if "external_booking_attended" in m]
ok = bool(attended_msg)
print(f"  attended event in chatter: {ok}")
print("T7c701:", "PASS" if ok else "FAIL")
results["T7c701"] = ok


# ============================================================
print()
print("T7c702 - _notify_cert_issued fires on cert_issued")
print("=" * 72)
b1.with_user(u_super).action_mark_completed()
b1.with_user(u_super).action_mark_cert_issued()
new_bodies = _chatter_bodies(b1)
cert_msg = [
    m for m in new_bodies
    if "external_booking_cert_issued" in m]
ok = bool(cert_msg)
print(f"  cert_issued event in chatter: {ok}")
print("T7c702:", "PASS" if ok else "FAIL")
results["T7c702"] = ok


# ============================================================
print()
print("T7c703 - stub marker present in all event bodies")
print("=" * 72)
events_to_check = [
    "external_booking_confirmed",
    "external_booking_attended",
    "external_booking_cert_issued",
]
bodies = _chatter_bodies(b1)
all_markered = True
for event in events_to_check:
    body = next((m for m in bodies if event in m), None)
    if not body or _STUB_MARKER not in body:
        all_markered = False
        print(f"  marker missing for: {event}")
ok = all_markered
print(f"  all 3 events carry the stub marker: {ok}")
print("T7c703:", "PASS" if ok else "FAIL")
results["T7c703"] = ok


# ============================================================
print()
print("T7c704 - channels recorded per event")
print("=" * 72)
# Expected channels per event:
expected = {
    "external_booking_confirmed":
        ["email", "whatsapp"],
    "external_booking_attended": ["email"],
    "external_booking_cert_issued":
        ["email", "whatsapp"],
}
all_match = True
for event, want in expected.items():
    body = next(
        (m for m in bodies if event in m), None)
    if not body:
        all_match = False
        continue
    for ch in want:
        if ch not in body:
            print(f"  {event}: missing channel '{ch}'")
            all_match = False
ok = all_match
print(f"  all events list their channels: {ok}")
print("T7c704:", "PASS" if ok else "FAIL")
results["T7c704"] = ok


# ============================================================
print()
print("T7c705 - _cron_send_3d_reminders picks exactly 3-day-"
      "out")
print("=" * 72)
three_days = date.today() + timedelta(days=3)
two_days = date.today() + timedelta(days=2)
four_days = date.today() + timedelta(days=4)

b_3 = Booking.sudo().create({
    "vendor_id": vendor.id, "course_name": "3d-out",
    "crew_user_id": u_crew.id,
    "scheduled_date": three_days,
    "state": "booked",
})
b_2 = Booking.sudo().create({
    "vendor_id": vendor.id, "course_name": "2d-out",
    "crew_user_id": u_crew.id,
    "scheduled_date": two_days,
    "state": "booked",
})
b_4 = Booking.sudo().create({
    "vendor_id": vendor.id, "course_name": "4d-out",
    "crew_user_id": u_crew.id,
    "scheduled_date": four_days,
    "state": "booked",
})

# Snapshot message-counts before cron.
def _msg_count(b):
    return len(b.message_ids)


n_3_pre = _msg_count(b_3)
n_2_pre = _msg_count(b_2)
n_4_pre = _msg_count(b_4)

Booking.sudo()._cron_send_3d_reminders()

n_3_post = _msg_count(b_3)
n_2_post = _msg_count(b_2)
n_4_post = _msg_count(b_4)

# Only b_3 should have grown.
ok = (n_3_post > n_3_pre
      and n_2_post == n_2_pre
      and n_4_post == n_4_pre)
print(f"  3-day-out msg delta: {n_3_post - n_3_pre} "
      f"(expect >0)")
print(f"  2-day-out msg delta: {n_2_post - n_2_pre} "
      f"(expect 0)")
print(f"  4-day-out msg delta: {n_4_post - n_4_pre} "
      f"(expect 0)")
print("T7c705:", "PASS" if ok else "FAIL")
results["T7c705"] = ok


# ============================================================
print()
print("T7c706 - cron skips non-'booked' state bookings")
print("=" * 72)
b_pend = Booking.sudo().create({
    "vendor_id": vendor.id, "course_name": "pending 3d",
    "crew_user_id": u_crew.id,
    "scheduled_date": three_days,
    "state": "pending_approval",
})
n_pre = _msg_count(b_pend)
Booking.sudo()._cron_send_3d_reminders()
n_post = _msg_count(b_pend)
ok = n_post == n_pre
print(f"  pending_approval msg delta: {n_post - n_pre} "
      f"(expect 0)")
print("T7c706:", "PASS" if ok else "FAIL")
results["T7c706"] = ok


# ============================================================
print()
print("T7c707 - ir.cron record exists + active=True")
print("=" * 72)
cron = env.ref(
    "neon_external_training.cron_external_training_reminder_3d",
    raise_if_not_found=False)
ok = (bool(cron)
      and cron.active is True
      and cron.interval_number == 1
      and cron.interval_type == "days")
print(f"  cron exists: {bool(cron)}")
if cron:
    print(f"  active: {cron.active}")
    print(f"  interval: {cron.interval_number} "
          f"{cron.interval_type}")
print("T7c707:", "PASS" if ok else "FAIL")
results["T7c707"] = ok


# ============================================================
print()
print("T7c708 - _notify_send uses sudo() on message_post")
print("=" * 72)
src = inspect.getsource(Booking._notify_send)
ok = ("self.sudo().message_post(" in src
      or "self.sudo(\n            ).message_post(" in src)
print(f"  sudo() before message_post: {ok}")
print("T7c708:", "PASS" if ok else "FAIL")
results["T7c708"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7c700", "T7c701", "T7c702", "T7c703",
         "T7c704", "T7c705", "T7c706", "T7c707",
         "T7c708"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
