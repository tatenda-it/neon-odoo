"""Phase 7c integration smoke -- full booking lifecycle
end-to-end. 1 test, 10 stages.

T7cI001 -- vendor -> booking draft -> submit -> approve
(+ notify) -> cron 3d reminder (+ notify) -> attended
(+ notify) -> completed -> cert_issued (+ cert created +
notify) -> reverse pointer resolves -> final aggregates.

Exercises ~85% of Phase 7c code paths: vendor seed,
booking creation + reference sequence, state machine
(draft -> pending_approval -> booked -> attended ->
completed -> cert_issued), approval workflow + activity
routing, all 4 notification stubs, cron, cross-module cert
creation, FK reverse pointer.
"""
from datetime import date, timedelta

from odoo.exceptions import UserError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Booking = env["neon.external.training.booking"]
Vendor = env["neon.external.training.vendor"]
Cert = env["neon.training.certification"]
CertType = env["neon.training.certification.type"]
Activity = env["mail.activity"]
Users = env["res.users"]


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
    if group_xmlid:
        g = env.ref(
            group_xmlid, raise_if_not_found=False)
        if g and u not in g.users:
            g.sudo().write({"users": [(4, u.id)]})
    return u


u_super = _get_or_create_user(
    "p7c_int_super", "P7c Integration Super",
    "neon_core.group_neon_superuser")
u_crew = _get_or_create_user(
    "p7c_int_crew", "P7c Integration Crew",
    "base.group_user")
_get_or_create_user(
    "robin@neonhiring.co.zw", "Robin (test)",
    "neon_core.group_neon_superuser")
_get_or_create_user(
    "munashe@neonhiring.co.zw", "Munashe (test)",
    "neon_core.group_neon_superuser")
env.cr.commit()

_STUB_MARKER = "[Notification stub - Phase 9 will send]"
stage_results = {}


# ============================================================
print()
print("Stage 1 -- resolve vendor (Allen & Heath seed)")
print("=" * 72)
vendor = env.ref(
    "neon_external_training.vendor_allen_heath",
    raise_if_not_found=False)
ok = (bool(vendor)
      and vendor.active
      and "Allen" in (vendor.name or ""))
print(f"  vendor: {vendor.name if vendor else None}, "
      f"active={vendor.active if vendor else None}")
stage_results["s1_vendor"] = ok


# ============================================================
print()
print("Stage 2 -- create booking (draft)")
print("=" * 72)
cert_type = CertType.search([], limit=1)
assert cert_type, "expected at least one cert type seeded"
booking = Booking.sudo().create({
    "vendor_id": vendor.id,
    "course_name": "Integration smoke -- Allen & Heath SQ6",
    "crew_user_id": u_crew.id,
    "scheduled_date": date.today() + timedelta(days=30),
    "cert_type_id": cert_type.id,
})
import re
ref_ok = (booking.reference
          and re.match(r"^BKG-\d{4}-\d+$",
                       booking.reference))
ok = (bool(booking.id)
      and booking.state == "draft"
      and bool(ref_ok))
print(f"  id: {booking.id}, ref: {booking.reference!r}, "
      f"state: {booking.state}")
stage_results["s2_booking_draft"] = ok


# ============================================================
print()
print("Stage 3 -- submit_for_approval + activity routing")
print("=" * 72)
booking.with_user(u_crew).action_submit_for_approval()
booking.invalidate_recordset(["state"])
activities = Activity.sudo().search([
    ("res_model", "=", Booking._name),
    ("res_id", "=", booking.id),
])
assigned = set(activities.mapped("user_id.login"))
expected = {"robin@neonhiring.co.zw",
            "munashe@neonhiring.co.zw"}
ok = (booking.state == "pending_approval"
      and assigned == expected)
print(f"  state: {booking.state}")
print(f"  activities assigned: {sorted(assigned)}")
stage_results["s3_submit"] = ok


# ============================================================
print()
print("Stage 4 -- approve (+ notify booking_confirmed)")
print("=" * 72)
booking.with_user(u_super).action_approve()
booking.invalidate_recordset([
    "state", "approved_by_id", "approval_date"])
bodies = "\n".join(booking.message_ids.mapped("body"))
ok = (booking.state == "booked"
      and booking.approved_by_id == u_super
      and bool(booking.approval_date)
      and "external_booking_confirmed" in bodies
      and _STUB_MARKER in bodies)
print(f"  state: {booking.state}")
print(f"  approved_by: {booking.approved_by_id.login}")
print(f"  approval_date set: {bool(booking.approval_date)}")
print(f"  booking_confirmed notify in chatter: "
      f"{'external_booking_confirmed' in bodies}")
stage_results["s4_approve"] = ok


# ============================================================
print()
print("Stage 5 -- 3-day cron picks the booking (date mut)")
print("=" * 72)
# Temporarily move scheduled_date to today+3 so the cron
# picks this booking. (Real production: cron walks bookings
# whose scheduled_date naturally falls on today+3.)
orig_scheduled = booking.scheduled_date
booking.sudo().scheduled_date = (
    date.today() + timedelta(days=3))
n_msgs_pre = len(booking.message_ids)
Booking.sudo()._cron_send_3d_reminders()
booking.invalidate_recordset(["message_ids"])
bodies_after = "\n".join(
    booking.message_ids.mapped("body"))
delta = len(booking.message_ids) - n_msgs_pre
ok = (delta > 0
      and "external_booking_reminder_3d" in bodies_after)
print(f"  msgs delta: {delta} (expect >0)")
print(f"  reminder_3d notify in chatter: "
      f"{'external_booking_reminder_3d' in bodies_after}")
# Restore the original date so subsequent stages aren't
# affected by the past-date.
booking.sudo().scheduled_date = orig_scheduled
stage_results["s5_cron_reminder"] = ok


# ============================================================
print()
print("Stage 6 -- mark_attended (+ notify)")
print("=" * 72)
booking.with_user(u_super).action_mark_attended()
booking.invalidate_recordset(["state", "date_attended"])
bodies = "\n".join(booking.message_ids.mapped("body"))
ok = (booking.state == "attended"
      and booking.date_attended == date.today()
      and "external_booking_attended" in bodies)
print(f"  state: {booking.state}")
print(f"  date_attended: {booking.date_attended}")
print(f"  attended notify in chatter: "
      f"{'external_booking_attended' in bodies}")
stage_results["s6_attended"] = ok


# ============================================================
print()
print("Stage 7 -- mark_completed")
print("=" * 72)
booking.with_user(u_super).action_mark_completed()
booking.invalidate_recordset(["state", "date_completed"])
ok = (booking.state == "completed"
      and booking.date_completed == date.today())
print(f"  state: {booking.state}")
print(f"  date_completed: {booking.date_completed}")
stage_results["s7_completed"] = ok


# ============================================================
print()
print("Stage 8 -- mark_cert_issued (+ cert created + "
      "notify)")
print("=" * 72)
n_certs_before = Cert.sudo().search_count(
    [("user_id", "=", u_crew.id)])
booking.with_user(u_super).action_mark_cert_issued()
booking.invalidate_recordset(["state", "issued_cert_id"])
n_certs_after = Cert.sudo().search_count(
    [("user_id", "=", u_crew.id)])
cert = booking.issued_cert_id
bodies = "\n".join(booking.message_ids.mapped("body"))
ok = (booking.state == "cert_issued"
      and (n_certs_after - n_certs_before) == 1
      and bool(cert)
      and cert.state == "active"
      and cert.user_id == u_crew
      and cert.external_booking_id == booking
      and cert.external_trainer_name == vendor.name
      and "external_booking_cert_issued" in bodies)
print(f"  state: {booking.state}")
print(f"  cert id: {cert.id if cert else None}")
print(f"  cert state: {cert.state if cert else None}")
print(f"  cert external_trainer_name: "
      f"{cert.external_trainer_name if cert else None}")
print(f"  cert_issued notify in chatter: "
      f"{'external_booking_cert_issued' in bodies}")
stage_results["s8_cert_issued"] = ok


# ============================================================
print()
print("Stage 9 -- reverse pointer resolves "
      "(cert.external_booking_id -> booking)")
print("=" * 72)
found = Cert.sudo().search(
    [("external_booking_id", "=", booking.id)])
ok = (cert in found and len(found) == 1)
print(f"  cert.external_booking_id back-resolves: "
      f"{cert in found}")
stage_results["s9_reverse"] = ok


# ============================================================
print()
print("Stage 10 -- final aggregates")
print("=" * 72)
expected_events = {
    "external_booking_confirmed",
    "external_booking_reminder_3d",
    "external_booking_attended",
    "external_booking_cert_issued",
}
bodies = "\n".join(booking.message_ids.mapped("body"))
events_found = {
    ev for ev in expected_events if ev in bodies}
stub_count = bodies.count(_STUB_MARKER)
ok = (
    booking.state == "cert_issued"
    and cert.state == "active"
    and cert.external_booking_id == booking
    and events_found == expected_events
    and stub_count == 4)
print(f"  booking state: {booking.state} (expect "
      f"cert_issued)")
print(f"  cert state: {cert.state} (expect active)")
print(f"  events in chatter: {sorted(events_found)}")
print(f"  stub-marker count: {stub_count} (expect 4)")
stage_results["s10_aggregates"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = [
    "s1_vendor", "s2_booking_draft", "s3_submit",
    "s4_approve", "s5_cron_reminder", "s6_attended",
    "s7_completed", "s8_cert_issued", "s9_reverse",
    "s10_aggregates",
]
for k in order:
    v = stage_results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(f"  {k}: {mark}")
passed = sum(1 for k in order
             if stage_results.get(k) is True)
print()
print(f"Stages: {passed}/{len(order)} pass")

# Single-test result for run_regression.sh summary line.
overall = passed == len(order)
print()
print("T7cI001:", "PASS" if overall else "FAIL")
print(f"Total: {1 if overall else 0}/1 passed")

env.cr.rollback()
