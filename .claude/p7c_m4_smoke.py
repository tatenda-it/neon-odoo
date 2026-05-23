"""Phase 7c M4 smoke -- auto-cert issuance (11 tests).

T7c400 - external_booking_id field on certification
T7c401 - mark_cert_issued from non-completed -> UserError
T7c402 - mark_cert_issued without cert_type_id -> UserError
T7c403 - full happy path: completed + cert_type -> cert
         created
T7c404 - cert has state=active + correct user + reverse
         pointer
T7c405 - re-calling mark_cert_issued -> UserError (already
         issued)
T7c406 - cert.external_booking_id reverse-resolves
T7c407 - deleting booking sets cert.external_booking_id
         to null (ondelete=set null preserves cert)
T7c408 - defensive env.get pattern catches missing model
         (skipped: model is always present in test env;
         assert the guard branch exists in code)
T7c409 - external_trainer_name field populated with vendor
         name
T7c410 - _CERT_VERIFIER_LOGINS routing unchanged by M4
         (M3 regression smoke)
"""
from datetime import date, timedelta

from odoo.exceptions import UserError, ValidationError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Booking = env["neon.external.training.booking"]
Cert = env["neon.training.certification"]
CertType = env["neon.training.certification.type"]
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
    "p7c_m4_super", "P7c M4 Super",
    "neon_core.group_neon_superuser")
u_crew = _get_or_create_user(
    "p7c_m4_crew", "P7c M4 Crew",
    "base.group_user")
robin = _get_or_create_user(
    "robin@neonhiring.co.zw", "Robin (test)",
    "neon_core.group_neon_superuser")
munashe = _get_or_create_user(
    "munashe@neonhiring.co.zw", "Munashe (test)",
    "neon_core.group_neon_superuser")
env.cr.commit()

vendor = env.ref("neon_external_training.vendor_allen_heath")
cert_type = CertType.search([], limit=1)
assert cert_type, "expected at least one seeded cert type"
print(f"cert_type: {cert_type.name} (id={cert_type.id})")

tomorrow = date.today() + timedelta(days=1)


def _new_completed_booking(course=None, **vals):
    """Create a booking already at 'completed' state by
    fast-forwarding through the state machine."""
    base = {
        "vendor_id": vendor.id,
        "course_name": course or "M4 probe course",
        "crew_user_id": u_crew.id,
        "scheduled_date": tomorrow,
        "cert_type_id": cert_type.id,
    }
    base.update(vals)
    b = Booking.sudo().create(base)
    b.with_user(u_crew).action_submit_for_approval()
    b.with_user(u_super).action_approve()
    b.with_user(u_super).action_mark_attended()
    b.with_user(u_super).action_mark_completed()
    return b


# ============================================================
print()
print("T7c400 - external_booking_id field exists on "
      "certification")
print("=" * 72)
fld = Cert._fields.get("external_booking_id")
ok = (fld is not None
      and fld.comodel_name == "neon.external.training.booking"
      and fld.ondelete == "set null")
print(f"  field present: {fld is not None}")
if fld is not None:
    print(f"  comodel: {fld.comodel_name}")
    print(f"  ondelete: {fld.ondelete}")
print("T7c400:", "PASS" if ok else "FAIL")
results["T7c400"] = ok


# ============================================================
print()
print("T7c401 - mark_cert_issued from non-completed -> "
      "UserError")
print("=" * 72)
b_draft = Booking.sudo().create({
    "vendor_id": vendor.id,
    "course_name": "draft probe",
    "crew_user_id": u_crew.id,
    "scheduled_date": tomorrow,
    "cert_type_id": cert_type.id,
})
err, _v = _try(lambda: b_draft.action_mark_cert_issued())
ok = isinstance(err, UserError)
print(f"  UserError raised: {isinstance(err, UserError)}")
print(f"  msg: {str(err)[:140] if err else None}")
print("T7c401:", "PASS" if ok else "FAIL")
results["T7c401"] = ok


# ============================================================
print()
print("T7c402 - mark_cert_issued without cert_type_id -> "
      "UserError")
print("=" * 72)
b_no_type = _new_completed_booking(course="no_type probe",
                                    cert_type_id=False)
err, _v = _try(lambda: b_no_type.action_mark_cert_issued())
ok = (isinstance(err, UserError)
      and "cert_type" in str(err).lower())
print(f"  UserError raised: {isinstance(err, UserError)}")
print(f"  msg: {str(err)[:140] if err else None}")
print("T7c402:", "PASS" if ok else "FAIL")
results["T7c402"] = ok


# ============================================================
print()
print("T7c403 - happy path: completed + cert_type -> cert "
      "created")
print("=" * 72)
b_happy = _new_completed_booking(course="happy path")
n_certs_before = Cert.sudo().search_count(
    [("user_id", "=", u_crew.id)])
b_happy.with_user(u_super).action_mark_cert_issued()
n_certs_after = Cert.sudo().search_count(
    [("user_id", "=", u_crew.id)])
b_happy.invalidate_recordset(["state", "issued_cert_id"])
ok = (n_certs_after == n_certs_before + 1
      and b_happy.state == "cert_issued"
      and bool(b_happy.issued_cert_id))
print(f"  certs delta: "
      f"{n_certs_after - n_certs_before} (expect 1)")
print(f"  booking state: {b_happy.state}")
print(f"  issued_cert_id: "
      f"{b_happy.issued_cert_id.id if b_happy.issued_cert_id else None}")
print("T7c403:", "PASS" if ok else "FAIL")
results["T7c403"] = ok


# ============================================================
print()
print("T7c404 - cert has state=active + user + reverse "
      "pointer")
print("=" * 72)
cert = b_happy.issued_cert_id
ok = (cert.state == "active"
      and cert.user_id == u_crew
      and cert.external_booking_id == b_happy
      and cert.type_id == cert_type
      and cert.signed_off_by_id == u_super)
print(f"  state: {cert.state} (expect active)")
print(f"  user: {cert.user_id.login}")
print(f"  external_booking_id: {cert.external_booking_id.id}")
print(f"  signed_off_by: {cert.signed_off_by_id.login}")
print("T7c404:", "PASS" if ok else "FAIL")
results["T7c404"] = ok


# ============================================================
print()
print("T7c405 - re-calling mark_cert_issued -> UserError "
      "(already issued)")
print("=" * 72)
err, _v = _try(lambda: b_happy.with_user(u_super)
               .action_mark_cert_issued())
ok = (isinstance(err, UserError)
      and "already issued" in str(err).lower())
print(f"  UserError raised: {isinstance(err, UserError)}")
print(f"  msg: {str(err)[:140] if err else None}")
print("T7c405:", "PASS" if ok else "FAIL")
results["T7c405"] = ok


# ============================================================
print()
print("T7c406 - cert.external_booking_id reverse-resolves")
print("=" * 72)
# Search certs by booking
found = Cert.sudo().search(
    [("external_booking_id", "=", b_happy.id)])
ok = found == cert
print(f"  search by external_booking_id matched: "
      f"{found == cert}")
print("T7c406:", "PASS" if ok else "FAIL")
results["T7c406"] = ok


# ============================================================
print()
print("T7c407 - deleting booking sets cert.external_booking"
      "_id to null")
print("=" * 72)
cert_id = cert.id
booking_id_pre = b_happy.id
b_happy.sudo().unlink()
# Force registry cache invalidation; PostgreSQL set_null
# fires at the SQL layer but the Odoo recordset cache may
# still hold the stale FK value until invalidated.
env.invalidate_all()
cert_after = Cert.sudo().browse(cert_id)
booking_after = Booking.sudo().browse(booking_id_pre)
ok = (cert_after.exists()
      and not booking_after.exists()
      and not cert_after.external_booking_id)
print(f"  cert still exists: {bool(cert_after.exists())}")
print(f"  booking gone: {not booking_after.exists()}")
print(f"  external_booking_id after delete: "
      f"{cert_after.external_booking_id.id if cert_after.external_booking_id else None}")
print("T7c407:", "PASS" if ok else "FAIL")
results["T7c407"] = ok


# ============================================================
print()
print("T7c408 - defensive env.get guard pattern present")
print("=" * 72)
# We can't actually unload the cert model in a live env,
# but assert the guard branch exists in the booking
# action source.
import inspect
src = inspect.getsource(Booking.action_mark_cert_issued)
ok = (("env.get(" in src
       and "neon.training.certification" in src)
      and "is None" in src)
print(f"  env.get + None-check both present in source: {ok}")
print("T7c408:", "PASS" if ok else "FAIL")
results["T7c408"] = ok


# ============================================================
print()
print("T7c409 - external_trainer_name populated with "
      "vendor name")
print("=" * 72)
# T7c403 already issued an active cert for u_crew + cert_type.
# Phase 7a's _check_unique_active_per_user_type would refuse
# a duplicate -- use a different cert type if the registry
# has one; else use a different crew user.
alt_type = CertType.sudo().search(
    [("id", "!=", cert_type.id)], limit=1)
if alt_type:
    b_trainer = _new_completed_booking(
        course="trainer name", cert_type_id=alt_type.id)
else:
    # Fallback: different crew user, same cert type.
    u_crew2 = _get_or_create_user(
        "p7c_m4_crew2", "P7c M4 Crew 2",
        "base.group_user")
    b_trainer = _new_completed_booking(
        course="trainer name", crew_user_id=u_crew2.id)
b_trainer.with_user(u_super).action_mark_cert_issued()
ok = (b_trainer.issued_cert_id.external_trainer_name
      == vendor.name)
print(f"  external_trainer_name: "
      f"{b_trainer.issued_cert_id.external_trainer_name!r}")
print(f"  vendor.name: {vendor.name!r}")
print("T7c409:", "PASS" if ok else "FAIL")
results["T7c409"] = ok


# ============================================================
print()
print("T7c410 - M3 _CERT_VERIFIER_LOGINS routing unchanged")
print("=" * 72)
# Re-run M3's activity routing test inline as a regression
# guard against any M4 wiring breaking the verifier list.
b_reg = Booking.sudo().create({
    "vendor_id": vendor.id,
    "course_name": "regression probe",
    "crew_user_id": u_crew.id,
    "scheduled_date": tomorrow,
    "cert_type_id": cert_type.id,
})
b_reg.with_user(u_crew).action_submit_for_approval()
Activity = env["mail.activity"]
activities = Activity.sudo().search([
    ("res_model", "=", Booking._name),
    ("res_id", "=", b_reg.id),
])
assigned = sorted(activities.mapped("user_id.login"))
expected = sorted([
    "robin@neonhiring.co.zw",
    "munashe@neonhiring.co.zw"])
ok = assigned == expected
print(f"  assigned: {assigned}")
print(f"  expected: {expected}")
print("T7c410:", "PASS" if ok else "FAIL")
results["T7c410"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7c400", "T7c401", "T7c402", "T7c403", "T7c404",
         "T7c405", "T7c406", "T7c407", "T7c408", "T7c409",
         "T7c410"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
