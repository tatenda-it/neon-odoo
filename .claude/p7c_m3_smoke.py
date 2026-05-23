"""Phase 7c M3 smoke -- approval workflow + reject wizard
(8 tests).

T7c300 - submit_for_approval transitions draft -> pending +
         creates an activity
T7c301 - activity routed to Robin + Munashe (Phase 7a
         pattern reuse)
T7c302 - approve by superuser -> booked + audit fields set
T7c303 - approve by non-superuser raises AccessError
T7c304 - reject wizard -> draft + rejection_reason captured
T7c305 - rejected booking can be re-submitted
T7c306 - chatter logs both approval + rejection events
T7c307 - cannot approve a cancelled booking
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
Wizard = env["neon.external.training.reject.wizard"]
Activity = env["mail.activity"]
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
    if group_xmlid:
        g = env.ref(group_xmlid, raise_if_not_found=False)
        if g and u not in g.users:
            g.sudo().write({"users": [(4, u.id)]})
    return u


u_super = _get_or_create_user(
    "p7c_m3_super", "P7c M3 Super",
    "neon_core.group_neon_superuser")
u_lead = _get_or_create_user(
    "p7c_m3_lead", "P7c M3 Lead",
    "neon_core.group_neon_lead_tech")
u_crew = _get_or_create_user(
    "p7c_m3_crew", "P7c M3 Crew",
    "base.group_user")

# Ensure Robin + Munashe exist as users for the routing
# test. They're real production users; if missing locally
# create placeholders.
robin = _get_or_create_user(
    "robin@neonhiring.co.zw", "Robin (test)",
    "neon_core.group_neon_superuser")
munashe = _get_or_create_user(
    "munashe@neonhiring.co.zw", "Munashe (test)",
    "neon_core.group_neon_superuser")
env.cr.commit()

vendor = env.ref("neon_external_training.vendor_vid")
tomorrow = date.today() + timedelta(days=1)


def _new_booking(course=None, **vals):
    base = {
        "vendor_id": vendor.id,
        "course_name": course or "M3 probe course",
        "crew_user_id": u_crew.id,
        "scheduled_date": tomorrow,
    }
    base.update(vals)
    return Booking.sudo().create(base)


# ============================================================
print()
print("T7c300 - submit_for_approval transitions + creates "
      "activity")
print("=" * 72)
b1 = _new_booking(course="T7c300")
n_activities_before = Activity.sudo().search_count([
    ("res_model", "=", Booking._name),
    ("res_id", "=", b1.id),
])
b1.with_user(u_crew).action_submit_for_approval()
b1.invalidate_recordset(["state"])
n_activities_after = Activity.sudo().search_count([
    ("res_model", "=", Booking._name),
    ("res_id", "=", b1.id),
])
ok = (b1.state == "pending_approval"
      and n_activities_after > n_activities_before)
print(f"  state: {b1.state} (expect pending_approval)")
print(f"  activities created: "
      f"{n_activities_after - n_activities_before}")
print("T7c300:", "PASS" if ok else "FAIL")
results["T7c300"] = ok


# ============================================================
print()
print("T7c301 - activity routed to Robin + Munashe")
print("=" * 72)
activities = Activity.sudo().search([
    ("res_model", "=", Booking._name),
    ("res_id", "=", b1.id),
])
assigned_logins = sorted(
    activities.mapped("user_id.login"))
expected_logins = sorted([
    "robin@neonhiring.co.zw",
    "munashe@neonhiring.co.zw"])
ok = assigned_logins == expected_logins
print(f"  assigned: {assigned_logins}")
print(f"  expected: {expected_logins}")
print("T7c301:", "PASS" if ok else "FAIL")
results["T7c301"] = ok


# ============================================================
print()
print("T7c302 - approve by superuser -> booked + audit "
      "fields set")
print("=" * 72)
b1.with_user(u_super).action_approve()
b1.invalidate_recordset([
    "state", "approved_by_id", "approval_date"])
ok = (b1.state == "booked"
      and b1.approved_by_id == u_super
      and b1.approval_date is not False)
print(f"  state: {b1.state}")
print(f"  approved_by: {b1.approved_by_id.login}")
print(f"  approval_date: {b1.approval_date}")
print("T7c302:", "PASS" if ok else "FAIL")
results["T7c302"] = ok


# ============================================================
print()
print("T7c303 - approve by non-superuser raises AccessError")
print("=" * 72)
b2 = _new_booking(course="T7c303")
b2.with_user(u_crew).action_submit_for_approval()
err, _v = _try(lambda: b2.with_user(u_lead).action_approve())
ok = isinstance(err, AccessError)
print(f"  AccessError raised: "
      f"{isinstance(err, AccessError)}")
print(f"  err type: {type(err).__name__ if err else None}")
print("T7c303:", "PASS" if ok else "FAIL")
results["T7c303"] = ok


# ============================================================
print()
print("T7c304 - reject wizard -> draft + reason captured")
print("=" * 72)
b3 = _new_booking(course="T7c304")
b3.with_user(u_crew).action_submit_for_approval()
wiz = Wizard.with_user(u_super).create({
    "booking_id": b3.id,
    "reason": "Cost not budgeted; pre-approve with finance",
})
wiz.action_reject()
b3.invalidate_recordset(["state", "rejection_reason"])
ok = (b3.state == "draft"
      and b3.rejection_reason
      and "Cost not budgeted" in b3.rejection_reason)
print(f"  state: {b3.state}")
print(f"  reason: {b3.rejection_reason!r}")
print("T7c304:", "PASS" if ok else "FAIL")
results["T7c304"] = ok


# ============================================================
print()
print("T7c305 - rejected booking can be re-submitted")
print("=" * 72)
# Refresh date so we don't trip the past-date guard.
b3.scheduled_date = date.today() + timedelta(days=2)
err, _v = _try(lambda: b3.with_user(u_crew)
               .action_submit_for_approval())
b3.invalidate_recordset(["state"])
ok = (err is None and b3.state == "pending_approval")
print(f"  resubmit err: {err}")
print(f"  state: {b3.state}")
print("T7c305:", "PASS" if ok else "FAIL")
results["T7c305"] = ok


# ============================================================
print()
print("T7c306 - chatter logs approval + rejection events")
print("=" * 72)
# Walk back through b1 (approved) and b3 (rejected then
# resubmitted) chatter.
msgs_b1 = b1.message_ids.mapped("body")
msgs_b3 = b3.message_ids.mapped("body")
approved_logged = any("Approved by" in (m or "")
                      for m in msgs_b1)
rejected_logged = any("Rejected by" in (m or "")
                      and "Cost not budgeted" in (m or "")
                      for m in msgs_b3)
ok = approved_logged and rejected_logged
print(f"  approve-event in b1 chatter: {approved_logged}")
print(f"  reject-event in b3 chatter: {rejected_logged}")
print("T7c306:", "PASS" if ok else "FAIL")
results["T7c306"] = ok


# ============================================================
print()
print("T7c307 - cannot approve a cancelled booking")
print("=" * 72)
b4 = _new_booking(course="T7c307")
b4.with_user(u_crew).action_submit_for_approval()
b4.with_user(u_super).action_cancel()
err, _v = _try(lambda: b4.with_user(u_super).action_approve())
ok = isinstance(err, UserError)
print(f"  state before approve attempt: {b4.state}")
print(f"  UserError raised: {isinstance(err, UserError)}")
print("T7c307:", "PASS" if ok else "FAIL")
results["T7c307"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7c300", "T7c301", "T7c302", "T7c303", "T7c304",
         "T7c305", "T7c306", "T7c307"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
