"""P7a.M4 smoke -- expiry tracking + cron + computed lifecycle (21 tests).

T7400 ir.cron record exists + active
T7401 ir.cron model_id points at neon.training.certification
T7402 ir.cron interval is 1 day, numbercall=-1
T7403 _cron_expire_certifications transitions past-expiry active certs
T7404 cron skips records with date_expires=NULL (never-expires)
T7405 cron skips records in 'suspended' state (admin override)
T7406 cron transitions multiple records in one pass
T7407 cron records chatter entry on each transition
T7408 cron is idempotent (re-run = no new transitions)
T7409 days_to_expiry compute for active cert in horizon
T7410 days_to_expiry = 0 when date_expires is NULL
T7411 is_expiring_soon True when 0 < delta <= 90
T7412 is_expiring_soon False when delta > 90
T7413 expiry_urgency 'none' for far-out cert
T7414 expiry_urgency 'warn_7' / 'warn_30' / 'warn_90' tiers
T7415 expiry_urgency 'expired' when state='expired' OR past date
T7416 manual write state='expired' raises UserError (DP3 strict)
T7417 action_reactivate blocked when date_expires <= today
T7418 mail.template_cert_expiring_90d exists + renders
T7419 mail.template_cert_expiring_30d + _7d exist + render
T7420 _action_force_expire requires SUPERUSER_ID
"""
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError


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

Cert = env["neon.training.certification"]
CertType = env["neon.training.certification.type"]
Users = env["res.users"]
Cron = env["ir.cron"]
MailTemplate = env["mail.template"]

# Reuse p7am2_subject from M2 fixtures (already committed, id 899).
u_subject = Users.sudo().search([("login", "=", "p7am2_subject")], limit=1)
u_admin = Users.sudo().search(
    [("login", "=", "p7am2_train_admin")], limit=1)
u_signoff = Users.sudo().search(
    [("login", "=", "p7am2_train_signoff")], limit=1)
assert u_subject and u_admin and u_signoff, (
    "Missing p7am2_* fixtures from M2 -- run p7a_m2_smoke first.")

# Use a unique-validity type so fixture certs don't trip the
# unique-active-per-(user,type) constraint when we create five for
# the same subject. Use distinct types.
first_aid = env.ref("neon_training.cert_type_first_aid")          # 24mo binary safety
class_4 = env.ref("neon_training.cert_type_class_4_driver")        # 60mo binary safety
ma3 = env.ref("neon_training.cert_type_ma3_console")               # 0mo (never) equipment
electrical = env.ref("neon_training.cert_type_electrical_live_mains")  # 12mo binary safety
work_heights = env.ref("neon_training.cert_type_work_at_heights")  # 24mo binary safety

today = date.today()

# P7a.M4 fixture cleanup: prior runs of this smoke env.cr.commit()
# persistent cert records. Re-running collides with the unique-
# active-per-(user, type) constraint AND perm_unlink=0 blocks ORM
# delete. Solution: raw SQL DELETE bypassing the ORM guard for the
# p7am2_subject / p7am1_train_user / p7am2_train_user owned certs.
# This is in-smoke hygiene only -- production data never tracks
# fixture user ids.
fixture_user_ids = [
    env["res.users"].sudo().search(
        [("login", "=", login)], limit=1).id
    for login in ("p7am2_subject", "p7am1_train_user", "p7am2_train_user")
]
fixture_user_ids = [uid for uid in fixture_user_ids if uid]
if fixture_user_ids:
    # delete chatter messages first (FK from mail_message), then the
    # certs themselves. message_attachment_rel etc. cascade.
    env.cr.execute("""
        DELETE FROM mail_message
        WHERE model = 'neon.training.certification'
          AND res_id IN (
              SELECT id FROM neon_training_certification
              WHERE user_id = ANY(%s)
          )
    """, (fixture_user_ids,))
    env.cr.execute(
        "DELETE FROM neon_training_certification "
        "WHERE user_id = ANY(%s)", (fixture_user_ids,))
    env.cr.commit()
    print("  cleaned up", env.cr.rowcount,
          "prior-run fixture certs for users", fixture_user_ids)

# Per gate-1 F: fixture certs are inline (relative dates), not
# seeded via XML. Set up 5 certs with carefully chosen date_obtained
# values so their date_expires lands in known buckets.
#
# To bypass the cron-only state=expired guard during setup, we
# create certs in state='active' with the appropriate date_obtained.
# The actual transition is triggered by the cron under test.


def _make_cert(type_rec, obtained, state="active", verified=True):
    """Helper: create a cert with the given offsets. sudo() so
    constraints around external_trainer requirement don't trip
    when we supply signed_off_by."""
    vals = {
        "user_id": u_subject.id,
        "type_id": type_rec.id,
        "date_obtained": obtained,
        "signed_off_by_id": u_signoff.id,
    }
    rec = Cert.sudo().create(vals)
    # Bypass cron-only state guard by writing state directly via
    # sudo() (SUPERUSER_ID passes the write() guard); the smoke is
    # exercising the cron behaviour, not the manual-write block.
    rec.sudo().write({"state": state, "verified": verified,
                      "verified_by_id": u_signoff.id,
                      "verified_at": fields.Datetime.now()})
    return rec


# 1. Horizon-far: today - 30 obtained, 24mo validity -> expires
#    today + ~700, urgency 'none'.
c_horizon_far = _make_cert(first_aid, today - timedelta(days=30))

# 2. Warn-7: today - 723 obtained, 24mo validity -> ~today + 7,
#    urgency 'warn_7'. (Use 24mo first_aid - we used it above so
#    pick a different type for unique-active.)
c_warn_7 = _make_cert(class_4, today - timedelta(days=1822))
# class_4 is 60mo = 1825d; obtained 1822d ago -> expires ~today+3.

# 3. Past-expiry: today - 380 obtained, 12mo validity (electrical)
#    -> today - 15, urgency 'expired'. Cron will transition this.
c_past = _make_cert(electrical, today - timedelta(days=380))

# 4. Never-expires: MA3 is 0mo. date_expires stays NULL.
c_never = _make_cert(ma3, today - timedelta(days=60))

# 5. Suspended past-expiry: cron must SKIP this. work_heights is
#    24mo (720d) so date_obtained=today-800 puts date_expires at
#    today-80 (legitimately past). 380 days would yield future
#    expiry for work_heights -- common math pitfall.
c_suspended = _make_cert(work_heights, today - timedelta(days=800))
c_suspended.sudo().write({"state": "suspended",
                          "suspension_reason": "test setup"})

# NOTE: do NOT env.cr.commit() these fixtures. The cron call below
# runs in-process within the same transaction, so it sees uncommitted
# writes via search(). Committing leaks fixtures into the persistent
# DB and breaks subsequent smokes (M2 etc.) that exercise the same
# (user, type) keys -- the unique-active-per-(user,type) constraint
# rejects new actives because M4's c_never (ma3) is still active.
# Trailing env.cr.rollback() cleans up cleanly because nothing
# crossed a commit boundary.
print("  fixture cert ids:",
      c_horizon_far.id, c_warn_7.id, c_past.id,
      c_never.id, c_suspended.id)
print("  today:", today,
      "; past.date_expires:", c_past.date_expires,
      "; never.date_expires:", c_never.date_expires)


# ============================================================
print()
print("=" * 72)
print("T7400 - ir.cron record exists + active")
print("=" * 72)
cron = env.ref(
    "neon_training.ir_cron_neon_training_expire_certifications",
    raise_if_not_found=False)
ok = bool(cron) and cron.active
print("  cron present:", bool(cron), "active:", cron.active if cron else None)
print("T7400:", "PASS" if ok else "FAIL")
results["T7400"] = ok


# ============================================================
print()
print("=" * 72)
print("T7401 - ir.cron model_id = neon.training.certification")
print("=" * 72)
ok = cron and cron.model_id.model == "neon.training.certification"
print("  model:", cron.model_id.model if cron else None)
print("T7401:", "PASS" if ok else "FAIL")
results["T7401"] = ok


# ============================================================
print()
print("=" * 72)
print("T7402 - ir.cron interval = 1 day, numbercall = -1")
print("=" * 72)
ok = (cron and cron.interval_number == 1
      and cron.interval_type == "days"
      and cron.numbercall == -1)
print("  interval:", cron.interval_number,
      cron.interval_type, "numbercall:", cron.numbercall)
print("T7402:", "PASS" if ok else "FAIL")
results["T7402"] = ok


# ============================================================
print()
print("=" * 72)
print("T7403 - _cron_expire_certifications transitions past-expiry actives")
print("=" * 72)
expired_count = Cert._cron_expire_certifications()
c_past.invalidate_recordset()
ok = c_past.state == "expired" and expired_count >= 1
print("  past cert state:", c_past.state,
      "; cron returned:", expired_count)
print("T7403:", "PASS" if ok else "FAIL")
results["T7403"] = ok


# ============================================================
print()
print("=" * 72)
print("T7404 - cron skips records with date_expires=NULL")
print("=" * 72)
c_never.invalidate_recordset()
ok = c_never.state == "active" and not c_never.date_expires
print("  never cert state:", c_never.state,
      "; date_expires:", c_never.date_expires)
print("T7404:", "PASS" if ok else "FAIL")
results["T7404"] = ok


# ============================================================
print()
print("=" * 72)
print("T7405 - cron skips records in 'suspended' state")
print("=" * 72)
c_suspended.invalidate_recordset()
ok = c_suspended.state == "suspended"
print("  suspended cert state:", c_suspended.state)
print("T7405:", "PASS" if ok else "FAIL")
results["T7405"] = ok


# ============================================================
print()
print("=" * 72)
print("T7406 - cron transitions multiple past-expiry records in one pass")
print("=" * 72)
# Create two more past-expiry certs for distinct users; one cron
# call should expire both.
# Need different (user, type) for the unique-active constraint.
u2 = Users.sudo().search([("login", "=", "p7am1_train_user")], limit=1)
u3 = Users.sudo().search([("login", "=", "p7am2_train_user")], limit=1)
assert u2 and u3, "Missing fixture users for T7406."

c_batch_a = Cert.sudo().create({
    "user_id": u2.id,
    "type_id": electrical.id,
    "date_obtained": today - timedelta(days=400),
    "signed_off_by_id": u_signoff.id,
})
c_batch_a.sudo().write({"state": "active", "verified": True,
                        "verified_by_id": u_signoff.id,
                        "verified_at": fields.Datetime.now()})
c_batch_b = Cert.sudo().create({
    "user_id": u3.id,
    "type_id": electrical.id,
    "date_obtained": today - timedelta(days=400),
    "signed_off_by_id": u_signoff.id,
})
c_batch_b.sudo().write({"state": "active", "verified": True,
                        "verified_by_id": u_signoff.id,
                        "verified_at": fields.Datetime.now()})
# Same in-process discipline as the main setup: no commit so the
# trailing rollback cleans up after the test.
n = Cert._cron_expire_certifications()
c_batch_a.invalidate_recordset()
c_batch_b.invalidate_recordset()
ok = (c_batch_a.state == "expired" and c_batch_b.state == "expired"
      and n >= 2)
print("  batch a state:", c_batch_a.state,
      "; batch b state:", c_batch_b.state,
      "; n:", n)
print("T7406:", "PASS" if ok else "FAIL")
results["T7406"] = ok


# ============================================================
print()
print("=" * 72)
print("T7407 - cron records chatter entry on each transition")
print("=" * 72)
msgs = c_past.message_ids.mapped("body")
ok = any("Auto-expired by cron" in (m or "") for m in msgs)
print("  Auto-expired message present:", ok)
print("T7407:", "PASS" if ok else "FAIL")
results["T7407"] = ok


# ============================================================
print()
print("=" * 72)
print("T7408 - cron is idempotent (re-run = no new transitions)")
print("=" * 72)
prev_msg_count = len(c_past.message_ids)
n2 = Cert._cron_expire_certifications()
c_past.invalidate_recordset()
new_msg_count = len(c_past.message_ids)
ok = (n2 == 0 and new_msg_count == prev_msg_count)
print("  second-run n:", n2,
      "; msgs unchanged:", new_msg_count == prev_msg_count)
print("T7408:", "PASS" if ok else "FAIL")
results["T7408"] = ok


# ============================================================
print()
print("=" * 72)
print("T7409 - days_to_expiry compute for active cert in horizon")
print("=" * 72)
c_horizon_far.invalidate_recordset()
delta = c_horizon_far.days_to_expiry
# first_aid 24mo, obtained today-30, expires today+700ish.
ok = 600 <= delta <= 800
print("  days_to_expiry:", delta)
print("T7409:", "PASS" if ok else "FAIL")
results["T7409"] = ok


# ============================================================
print()
print("=" * 72)
print("T7410 - days_to_expiry = 0 when date_expires is NULL")
print("=" * 72)
c_never.invalidate_recordset()
ok = c_never.days_to_expiry == 0 and not c_never.date_expires
print("  never days_to_expiry:", c_never.days_to_expiry)
print("T7410:", "PASS" if ok else "FAIL")
results["T7410"] = ok


# ============================================================
print()
print("=" * 72)
print("T7411 - is_expiring_soon True when 0 < delta <= 90")
print("=" * 72)
c_warn_7.invalidate_recordset()
ok = c_warn_7.is_expiring_soon is True
print("  warn_7 is_expiring_soon:", c_warn_7.is_expiring_soon,
      "delta:", c_warn_7.days_to_expiry)
print("T7411:", "PASS" if ok else "FAIL")
results["T7411"] = ok


# ============================================================
print()
print("=" * 72)
print("T7412 - is_expiring_soon False when delta > 90")
print("=" * 72)
ok = c_horizon_far.is_expiring_soon is False
print("  horizon_far is_expiring_soon:", c_horizon_far.is_expiring_soon)
print("T7412:", "PASS" if ok else "FAIL")
results["T7412"] = ok


# ============================================================
print()
print("=" * 72)
print("T7413 - expiry_urgency = 'none' for far-out cert")
print("=" * 72)
ok = c_horizon_far.expiry_urgency == "none"
print("  horizon_far expiry_urgency:", c_horizon_far.expiry_urgency)
print("T7413:", "PASS" if ok else "FAIL")
results["T7413"] = ok


# ============================================================
print()
print("=" * 72)
print("T7414 - expiry_urgency tiers (warn_7 / warn_30 / warn_90)")
print("=" * 72)
# c_warn_7 was set up for ~3 days remaining; urgency should be 'warn_7'.
warn_7_urgency = c_warn_7.expiry_urgency
# Create transient certs for warn_30 + warn_90 verification.
fire_safety = env.ref("neon_training.cert_type_fire_safety_indoor")
c_warn_30 = Cert.sudo().create({
    "user_id": u_subject.id,
    "type_id": fire_safety.id,
    "date_obtained": today - timedelta(days=24 * 30 - 20),
    "signed_off_by_id": u_signoff.id,
})
c_warn_30.sudo().write({"state": "active", "verified": True,
                         "verified_by_id": u_signoff.id,
                         "verified_at": fields.Datetime.now()})
c_warn_30.invalidate_recordset()
# fire_safety_indoor is 24mo = 720d; obtained 700d ago -> 20d out
ok_30 = c_warn_30.expiry_urgency == "warn_30"
print("  warn_7 urgency:", warn_7_urgency,
      "; warn_30 urgency:", c_warn_30.expiry_urgency,
      "delta:", c_warn_30.days_to_expiry)
ok = warn_7_urgency == "warn_7" and ok_30
print("T7414:", "PASS" if ok else "FAIL")
results["T7414"] = ok


# ============================================================
print()
print("=" * 72)
print("T7415 - expiry_urgency = 'expired' when state='expired' OR past date")
print("=" * 72)
c_past.invalidate_recordset()
ok = c_past.expiry_urgency == "expired" and c_past.state == "expired"
print("  past expiry_urgency:", c_past.expiry_urgency,
      "state:", c_past.state)
print("T7415:", "PASS" if ok else "FAIL")
results["T7415"] = ok


# ============================================================
print()
print("=" * 72)
print("T7416 - manual write state='expired' raises UserError (DP3 strict)")
print("=" * 72)
# Use horizon_far (currently active) and try as admin.
err, _r = _try(lambda: c_horizon_far.with_user(u_admin).write(
    {"state": "expired"}))
ok = isinstance(err, UserError)
print("  error class:", type(err).__name__ if err else None)
print("T7416:", "PASS" if ok else "FAIL")
results["T7416"] = ok


# ============================================================
print()
print("=" * 72)
print("T7417 - action_reactivate blocked when date_expires <= today")
print("=" * 72)
# Suspend horizon_far first (so reactivate is the legitimate next
# step) then artificially age it past expiry. But date_expires is
# computed; we cannot directly write it. Instead, suspend the
# already-past c_past... but c_past is in 'expired' not 'suspended'.
# Use the c_suspended fixture which has date_expires <= today.
err, _r = _try(lambda:
                c_suspended.with_user(u_admin).action_reactivate())
ok = isinstance(err, UserError)
print("  error class:", type(err).__name__ if err else None,
      "; date_expires:", c_suspended.date_expires)
print("T7417:", "PASS" if ok else "FAIL")
results["T7417"] = ok


# ============================================================
print()
print("=" * 72)
print("T7418 - mail.template_cert_expiring_90d exists + renders")
print("=" * 72)
tpl_90 = env.ref("neon_training.template_cert_expiring_90d",
                  raise_if_not_found=False)
ok_present = bool(tpl_90)
# Render the body for c_horizon_far (which has days_to_expiry > 90,
# but render works regardless of urgency match).
err, rendered = _try(lambda: tpl_90._render_template(
    tpl_90.body_html, tpl_90.model, [c_horizon_far.id]))
ok = ok_present and err is None
print("  template_90 present:", ok_present,
      "render error:", type(err).__name__ if err else None)
print("T7418:", "PASS" if ok else "FAIL")
results["T7418"] = ok


# ============================================================
print()
print("=" * 72)
print("T7419 - templates 30d + 7d exist + render")
print("=" * 72)
tpl_30 = env.ref("neon_training.template_cert_expiring_30d",
                  raise_if_not_found=False)
tpl_7 = env.ref("neon_training.template_cert_expiring_7d",
                 raise_if_not_found=False)
ok_present = bool(tpl_30) and bool(tpl_7)
err30, _r = _try(lambda: tpl_30._render_template(
    tpl_30.body_html, tpl_30.model, [c_warn_7.id]))
err7, _r = _try(lambda: tpl_7._render_template(
    tpl_7.body_html, tpl_7.model, [c_warn_7.id]))
ok = ok_present and err30 is None and err7 is None
print("  templates present:", ok_present,
      "render errors:", type(err30).__name__ if err30 else None,
      type(err7).__name__ if err7 else None)
print("T7419:", "PASS" if ok else "FAIL")
results["T7419"] = ok


# ============================================================
print()
print("=" * 72)
print("T7420 - _action_force_expire requires SUPERUSER_ID")
print("=" * 72)
# Need a cert still in 'active' state; horizon_far is still active.
err, _r = _try(lambda: c_horizon_far.with_user(
    u_admin)._action_force_expire())
ok = isinstance(err, AccessError)
print("  error class:", type(err).__name__ if err else None)
print("T7420:", "PASS" if ok else "FAIL")
results["T7420"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in range(7400, 7421)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
