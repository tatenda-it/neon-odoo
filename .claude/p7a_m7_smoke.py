"""P7a.M7 smoke -- sign-off authority workflow (22 tests).

Authority-routed TODOs:
T7700  TODO on submit_for_verification, routed to lead_tech group
T7701  TODO on submit_for_verification, routed to od_md group
T7702  TODO on submit_for_verification, routed to admin (external_trainer)
T7703  TODO dedup: re-submission doesn't create duplicate
T7704  TODO routing fallback to admin when authority group empty

Verify hardening:
T7705  lead_tech-authority cert: u_signoff (no crew_leader) -> UserError
T7706  od_md-authority cert: u_signoff (no finance_approver) -> UserError
T7707  external_trainer-authority cert: u_signoff -> UserError (admin route)
T7708  admin override -- training_admin can verify any authority

Promotion mechanics:
T7709  action_promote_to_cert creates draft cert with linkage
T7710  Promotion chatter on both records
T7711  Promote blocked when leads_to_certification=False
T7712  Promote blocked when already promoted (no duplicate)

Constraints:
T7713  source_cross_competency_id consistency: user_id mismatch
T7714  Field-lock post-promotion: cross_competency user_id change blocked
T7715  is_promoted compute reflects cert existence

Audit + chatter:
T7716  No perm_unlink on promoted cert as admin
T7717  Verify chatter records authority bypass
T7718  Fallback chatter posted when authority group empty
T7719  Promote action returns act_window for new cert

Shared constant:
T7720  _SIGN_OFF_AUTHORITY_GROUP constant accessible + correct values
T7721  M5's _resolve_cc_partners consumes shared constant
"""
from datetime import date, timedelta

from odoo import fields, SUPERUSER_ID
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
CC = env["neon.training.cross_competency"]
Activity = env["mail.activity"]
Users = env["res.users"]
Partner = env["res.partner"]
Job = env["commercial.job"]
EventJob = env["commercial.event.job"]

u_subject = Users.sudo().search([("login", "=", "p7am2_subject")], limit=1)
u_signoff = Users.sudo().search(
    [("login", "=", "p7am2_train_signoff")], limit=1)
u_admin = Users.sudo().search(
    [("login", "=", "p7am2_train_admin")], limit=1)
u_user = Users.sudo().search(
    [("login", "=", "p7am2_train_user")], limit=1)
lead_tech_user = Users.sudo().search(
    [("login", "=", "p2m75_lead")], limit=1)
finance_approver_user = Users.sudo().search(
    [("login", "=", "p2m75_approver")], limit=1)
assert (u_subject and u_signoff and u_admin and u_user
        and lead_tech_user and finance_approver_user), (
    "Missing fixture users")

# Cleanup prior fixture certs from p7am2_subject so the unique-
# active-per-(user, type) constraint doesn't trip.
env.cr.execute(
    "DELETE FROM mail_activity WHERE res_model_id IN "
    "(SELECT id FROM ir_model WHERE model = "
    "'neon.training.certification') AND res_id IN "
    "(SELECT id FROM neon_training_certification WHERE "
    "user_id IN (%s, %s))",
    (u_subject.id, u_user.id))
env.cr.execute(
    "DELETE FROM mail_message WHERE model = "
    "'neon.training.certification' AND res_id IN "
    "(SELECT id FROM neon_training_certification WHERE "
    "user_id IN (%s, %s))",
    (u_subject.id, u_user.id))
env.cr.execute(
    "DELETE FROM neon_training_certification WHERE user_id IN (%s, %s)",
    (u_subject.id, u_user.id))
# Also clean cross-competency from M6 fixtures.
env.cr.execute(
    "DELETE FROM mail_message WHERE model = "
    "'neon.training.cross_competency' AND res_id IN "
    "(SELECT id FROM neon_training_cross_competency WHERE "
    "user_id IN (%s, %s))",
    (u_subject.id, u_user.id))
env.cr.execute(
    "DELETE FROM neon_training_cross_competency WHERE user_id IN (%s, %s)",
    (u_subject.id, u_user.id))
env.cr.commit()
print("  cleaned up prior fixtures")

# Certification types with each authority value.
ma3 = env.ref("neon_training.cert_type_ma3_console")          # lead_tech
lead_tech_type = env.ref("neon_training.cert_type_lead_tech")  # od_md
first_aid = env.ref("neon_training.cert_type_first_aid")       # external_trainer
english = env.ref("neon_training.cert_type_lang_english")      # self_with_peer

# Sanity-check authority values match expected before testing.
assert ma3.sign_off_authority == "lead_tech"
assert lead_tech_type.sign_off_authority == "od_md"
assert first_aid.sign_off_authority == "external_trainer"
assert english.sign_off_authority == "self_with_peer"
print("  authorities confirmed: ma3=lead_tech, lead_tech_type=od_md,"
      " first_aid=external_trainer, english=self_with_peer")

# Fixture event_job for cross-competency tests.
test_partner = Partner.sudo().create({
    "name": "P7aM7 Test Client", "is_company": True})
test_venue = Partner.sudo().create({
    "name": "P7aM7 Test Venue", "is_company": True})
test_job = Job.sudo().create({
    "partner_id": test_partner.id,
    "venue_id": test_venue.id,
    "event_date": date.today() - timedelta(days=10),
    "currency_id": env.company.currency_id.id,
})
test_job.sudo().write({"state": "active", "soft_hold_until": False})
test_ej = test_job.event_job_ids[0]
print("  fixture event_job:", test_ej.id)


# ============================================================
print()
print("=" * 72)
print("T7700 - TODO routed to lead_tech group on submit_for_verification")
print("=" * 72)
c_t7700 = Cert.sudo().create({
    "user_id": u_subject.id,
    "type_id": ma3.id,  # lead_tech authority
    "date_obtained": date.today() - timedelta(days=1),
})
c_t7700.with_user(u_subject).action_submit_for_verification()
todos = Activity.sudo().search([
    ("res_model", "=", "neon.training.certification"),
    ("res_id", "=", c_t7700.id),
    ("summary", "=ilike", "Verify%"),
])
ok = (len(todos) == 1
      and todos[0].user_id == lead_tech_user
      and "MA3 Console" in todos[0].summary
      and "p7am2_subject" in todos[0].summary)
print("  TODO count:", len(todos),
      " user:", todos[0].user_id.login if todos else None,
      " summary:", todos[0].summary if todos else None)
print("T7700:", "PASS" if ok else "FAIL")
results["T7700"] = ok


# ============================================================
print()
print("=" * 72)
print("T7701 - TODO routed to od_md group (Lead Tech cert type)")
print("=" * 72)
c_t7701 = Cert.sudo().create({
    "user_id": u_subject.id,
    "type_id": lead_tech_type.id,  # od_md authority
    "date_obtained": date.today() - timedelta(days=1),
    "level": "lead_tech",
})
c_t7701.with_user(u_subject).action_submit_for_verification()
todos = Activity.sudo().search([
    ("res_model", "=", "neon.training.certification"),
    ("res_id", "=", c_t7701.id),
    ("summary", "=ilike", "Verify%"),
])
ok = (len(todos) == 1 and todos[0].user_id == finance_approver_user)
print("  TODO count:", len(todos),
      " user:", todos[0].user_id.login if todos else None,
      " (expected p2m75_approver)")
print("T7701:", "PASS" if ok else "FAIL")
results["T7701"] = ok


# ============================================================
print()
print("=" * 72)
print("T7702 - TODO routed to admin (external_trainer authority)")
print("=" * 72)
c_t7702 = Cert.sudo().create({
    "user_id": u_subject.id,
    "type_id": first_aid.id,  # external_trainer authority
    "date_obtained": date.today() - timedelta(days=1),
    "signed_off_by_id": u_signoff.id,  # satisfy external trainer constraint
})
c_t7702.with_user(u_subject).action_submit_for_verification()
todos = Activity.sudo().search([
    ("res_model", "=", "neon.training.certification"),
    ("res_id", "=", c_t7702.id),
    ("summary", "=ilike", "Verify%"),
])
# external_trainer routes to admin tier; first user in
# group_neon_training_admin (sorted by id).
admin_group = env.ref("neon_training.group_neon_training_admin")
expected_user = admin_group.users.sorted("id")[0]
ok = (len(todos) == 1 and todos[0].user_id == expected_user)
print("  TODO count:", len(todos),
      " user:", todos[0].user_id.login if todos else None,
      " expected:", expected_user.login)
print("T7702:", "PASS" if ok else "FAIL")
results["T7702"] = ok


# ============================================================
print()
print("=" * 72)
print("T7703 - TODO dedup: re-submission does NOT create duplicate")
print("=" * 72)
# Suspend c_t7700, then re-submit (after returning to draft).
# Actually simpler: just call _create_verification_todo() again
# directly; the dedup logic should skip.
prior = Activity.sudo().search_count([
    ("res_model", "=", "neon.training.certification"),
    ("res_id", "=", c_t7700.id),
    ("summary", "=ilike", "Verify%"),
])
c_t7700.sudo()._create_verification_todo()
after = Activity.sudo().search_count([
    ("res_model", "=", "neon.training.certification"),
    ("res_id", "=", c_t7700.id),
    ("summary", "=ilike", "Verify%"),
])
ok = prior == after == 1
print("  prior:", prior, " after:", after)
print("T7703:", "PASS" if ok else "FAIL")
results["T7703"] = ok


# ============================================================
print()
print("=" * 72)
print("T7704 - TODO fallback to admin when authority group empty")
print("=" * 72)
# Simulate empty group by removing all users from group_neon_jobs_
# crew_leader transiently (within smoke savepoint). Easier: monkey-
# patch _resolve_verify_authority_partners to return the fallback
# path. Cleanest: create a cert with lead_tech authority, drop
# crew_leader memberships temporarily, fire submit, assert
# fallback applied.
crew_leader_grp = env.ref("neon_jobs.group_neon_jobs_crew_leader")
crew_users_backup = crew_leader_grp.users
crew_leader_grp.sudo().write(
    {"users": [(5, 0, 0)]})  # clear all members transiently
# Verify the group is empty now.
crew_leader_grp.invalidate_recordset()
assert not crew_leader_grp.users, (
    "fallback test prep: crew_leader group still has members")
c_t7704 = Cert.sudo().create({
    "user_id": u_subject.id,
    "type_id": env.ref(
        "neon_training.cert_type_chamsys_magicq").id,  # also lead_tech
    "date_obtained": date.today() - timedelta(days=1),
})
c_t7704.with_user(u_subject).action_submit_for_verification()
todos = Activity.sudo().search([
    ("res_model", "=", "neon.training.certification"),
    ("res_id", "=", c_t7704.id),
])
# Should have fallen back to admin tier.
ok_routing = (
    len(todos) == 1
    and todos[0].user_id == expected_user)  # admin tier first user
# Check chatter recorded the fallback.
fallback_msg = c_t7704.message_ids.filtered(
    lambda m: "Authority routing fallback" in (m.body or "")
              or "Authority routing fallback" in (m.subject or ""))
ok = ok_routing and bool(fallback_msg)
print("  TODO routed to admin:", ok_routing,
      " fallback chatter present:", bool(fallback_msg))
# Restore crew_leader membership for downstream tests.
crew_leader_grp.sudo().write(
    {"users": [(6, 0, crew_users_backup.ids)]})
print("T7704:", "PASS" if ok else "FAIL")
results["T7704"] = ok


# ============================================================
print()
print("=" * 72)
print("T7705 - verify hardening: lead_tech-auth cert, signoff -> UserError")
print("=" * 72)
# c_t7700 is ma3 (lead_tech authority), still in pending_verification.
# u_signoff has training_signoff but NOT crew_leader -> blocked.
err, _r = _try(lambda: c_t7700.with_user(u_signoff).action_verify())
ok = isinstance(err, UserError)
print("  err class:", type(err).__name__ if err else None,
      " message:", (str(err)[:90] if err else ""))
print("T7705:", "PASS" if ok else "FAIL")
results["T7705"] = ok


# ============================================================
print()
print("=" * 72)
print("T7706 - verify hardening: od_md-auth cert, signoff -> UserError")
print("=" * 72)
err, _r = _try(lambda: c_t7701.with_user(u_signoff).action_verify())
ok = isinstance(err, UserError)
print("  err class:", type(err).__name__ if err else None)
print("T7706:", "PASS" if ok else "FAIL")
results["T7706"] = ok


# ============================================================
print()
print("=" * 72)
print("T7707 - verify hardening: external_trainer-auth cert, signoff -> UserError")
print("=" * 72)
err, _r = _try(lambda: c_t7702.with_user(u_signoff).action_verify())
ok = isinstance(err, UserError)
print("  err class:", type(err).__name__ if err else None)
print("T7707:", "PASS" if ok else "FAIL")
results["T7707"] = ok


# ============================================================
print()
print("=" * 72)
print("T7708 - admin override: training_admin verifies any authority")
print("=" * 72)
# Admin can verify all three certs.
c_t7700.with_user(u_admin).action_verify()  # lead_tech authority
c_t7700.invalidate_recordset()
# Suspend c_t7701 since lead_tech_type is unique-active and we'll
# create more lead_tech_type certs downstream. Actually c_t7701 is
# in pending_verification -> active here.
c_t7701.with_user(u_admin).action_verify()  # od_md authority
c_t7701.invalidate_recordset()
c_t7702.with_user(u_admin).action_verify()  # external_trainer authority
c_t7702.invalidate_recordset()
ok = (c_t7700.state == "active"
      and c_t7701.state == "active"
      and c_t7702.state == "active")
print("  c_t7700.state:", c_t7700.state,
      " c_t7701.state:", c_t7701.state,
      " c_t7702.state:", c_t7702.state)
print("T7708:", "PASS" if ok else "FAIL")
results["T7708"] = ok


# ============================================================
print()
print("=" * 72)
print("T7709 - action_promote_to_cert creates draft with linkage")
print("=" * 72)
# Create a cross-competency observation with leads_to_certification=True.
# Use truss_climbing_trilite to avoid colliding with c_t7700 (ma3).
trilite = env.ref("neon_training.cert_type_truss_climbing_trilite")
cc_t7709 = CC.sudo().create({
    "user_id": u_subject.id,
    "certification_type_id": trilite.id,
    "demonstrated_through_event_id": test_ej.id,
    "demonstrated_at": test_ej.event_date + timedelta(days=2),
    "observed_by_id": u_signoff.id,
    "notes": "Ran truss climb solo; competent.",
    "leads_to_certification": True,
})
result = cc_t7709.with_user(u_admin).action_promote_to_cert()
cc_t7709.invalidate_recordset()
promoted = cc_t7709.promoted_cert_ids
ok = (bool(promoted)
      and len(promoted) == 1
      and promoted.user_id == u_subject
      and promoted.type_id == trilite
      and promoted.state == "draft"
      and promoted.source_cross_competency_id == cc_t7709
      and isinstance(result, dict)
      and result.get("res_model") == "neon.training.certification"
      and result.get("res_id") == promoted.id)
print("  promoted exists:", bool(promoted),
      " state:", promoted.state if promoted else None,
      " source linked:", (promoted.source_cross_competency_id == cc_t7709)
      if promoted else None,
      " act_window returned:", isinstance(result, dict))
print("T7709:", "PASS" if ok else "FAIL")
results["T7709"] = ok


# ============================================================
print()
print("=" * 72)
print("T7710 - promotion chatter recorded on both records")
print("=" * 72)
cc_chatter = cc_t7709.message_ids.filtered(
    lambda m: "Promoted to certification" in (m.body or ""))
cert_chatter = promoted.message_ids.filtered(
    lambda m: "cross-competency observation" in (m.body or ""))
ok = bool(cc_chatter) and bool(cert_chatter)
print("  CC chatter:", bool(cc_chatter),
      " cert chatter:", bool(cert_chatter))
print("T7710:", "PASS" if ok else "FAIL")
results["T7710"] = ok


# ============================================================
print()
print("=" * 72)
print("T7711 - promote blocked when leads_to_certification=False")
print("=" * 72)
# Use led_wall_absen (lead_tech authority, different from trilite).
led_wall = env.ref("neon_training.cert_type_led_wall_absen")
cc_t7711 = CC.sudo().create({
    "user_id": u_subject.id,
    "certification_type_id": led_wall.id,
    "demonstrated_through_event_id": test_ej.id,
    "demonstrated_at": test_ej.event_date,
    "observed_by_id": u_signoff.id,
    "notes": "LED build observation.",
    "leads_to_certification": False,
})
err, _r = _try(
    lambda: cc_t7711.with_user(u_admin).action_promote_to_cert())
ok = isinstance(err, UserError) and "not flagged" in (str(err) or "")
print("  err class:", type(err).__name__ if err else None,
      " msg:", (str(err)[:90] if err else ""))
print("T7711:", "PASS" if ok else "FAIL")
results["T7711"] = ok


# ============================================================
print()
print("=" * 72)
print("T7712 - promote blocked when already promoted")
print("=" * 72)
err, _r = _try(
    lambda: cc_t7709.with_user(u_admin).action_promote_to_cert())
ok = isinstance(err, UserError) and "already been promoted" in (str(err) or "")
print("  err class:", type(err).__name__ if err else None)
print("T7712:", "PASS" if ok else "FAIL")
results["T7712"] = ok


# ============================================================
print()
print("=" * 72)
print("T7713 - source consistency: user_id mismatch raises")
print("=" * 72)
# Attempt to change promoted cert's user_id away from source.
err, _r = _try(lambda: promoted.sudo().write({"user_id": u_user.id}))
ok = isinstance(err, ValidationError)
print("  err class:", type(err).__name__ if err else None)
print("T7713:", "PASS" if ok else "FAIL")
results["T7713"] = ok


# ============================================================
print()
print("=" * 72)
print("T7714 - field-lock: change user_id on promoted cross-competency raises")
print("=" * 72)
err, _r = _try(lambda: cc_t7709.sudo().write({"user_id": u_user.id}))
ok = isinstance(err, ValidationError) and "Source-of-truth locked" in (
    str(err) or "")
print("  err class:", type(err).__name__ if err else None)
print("T7714:", "PASS" if ok else "FAIL")
results["T7714"] = ok


# ============================================================
print()
print("=" * 72)
print("T7715 - is_promoted compute reflects cert existence")
print("=" * 72)
cc_t7709.invalidate_recordset()
cc_t7711.invalidate_recordset()
ok = (cc_t7709.is_promoted is True
      and cc_t7711.is_promoted is False)
print("  cc_t7709.is_promoted:", cc_t7709.is_promoted,
      " cc_t7711.is_promoted:", cc_t7711.is_promoted)
print("T7715:", "PASS" if ok else "FAIL")
results["T7715"] = ok


# ============================================================
print()
print("=" * 72)
print("T7716 - No perm_unlink on promoted cert as admin")
print("=" * 72)
err, _r = _try(lambda: promoted.with_user(u_admin).unlink())
ok = isinstance(err, AccessError)
print("  err class:", type(err).__name__ if err else None)
print("T7716:", "PASS" if ok else "FAIL")
results["T7716"] = ok


# ============================================================
print()
print("=" * 72)
print("T7717 - Verify chatter records verifier name")
print("=" * 72)
verify_msgs = c_t7700.message_ids.filtered(
    lambda m: "Verified by" in (m.body or ""))
ok = bool(verify_msgs) and u_admin.name in (verify_msgs[0].body or "")
print("  verify chatter count:", len(verify_msgs),
      " contains admin name:", u_admin.name in (verify_msgs[0].body or "")
      if verify_msgs else False)
print("T7717:", "PASS" if ok else "FAIL")
results["T7717"] = ok


# ============================================================
print()
print("=" * 72)
print("T7718 - Fallback chatter contains group xmlid")
print("=" * 72)
fallback_msg = c_t7704.message_ids.filtered(
    lambda m: "Authority routing fallback" in (m.body or "")
              or "Authority routing fallback" in (m.subject or ""))
ok = (bool(fallback_msg)
      and "group_neon_jobs_crew_leader" in (fallback_msg[0].body or ""))
print("  fallback msg present:", bool(fallback_msg),
      " group_xmlid in body:",
      "group_neon_jobs_crew_leader" in (fallback_msg[0].body or "")
      if fallback_msg else False)
print("T7718:", "PASS" if ok else "FAIL")
results["T7718"] = ok


# ============================================================
print()
print("=" * 72)
print("T7719 - Promote action returns act_window for new cert")
print("=" * 72)
# Already exercised via T7709's result check; re-affirm.
ok = (isinstance(result, dict)
      and result.get("type") == "ir.actions.act_window"
      and result.get("res_model") == "neon.training.certification")
print("  result:", result)
print("T7719:", "PASS" if ok else "FAIL")
results["T7719"] = ok


# ============================================================
print()
print("=" * 72)
print("T7720 - _SIGN_OFF_AUTHORITY_GROUP constant correct + complete")
print("=" * 72)
# Import the constant via the model's module path.
from odoo.addons.neon_training.models.neon_training_certification import (
    _SIGN_OFF_AUTHORITY_GROUP)
expected = {
    "lead_tech":        "neon_jobs.group_neon_jobs_crew_leader",
    "od_md":            "neon_finance.group_neon_finance_approver",
    "external_trainer": "neon_training.group_neon_training_admin",
    "self_with_peer":   "neon_training.group_neon_training_admin",
}
ok = _SIGN_OFF_AUTHORITY_GROUP == expected
print("  constant keys:", sorted(_SIGN_OFF_AUTHORITY_GROUP.keys()))
print("T7720:", "PASS" if ok else "FAIL")
results["T7720"] = ok


# ============================================================
print()
print("=" * 72)
print("T7721 - M5's _resolve_cc_partners consumes shared constant")
print("=" * 72)
# Spot-check: a cert with lead_tech authority resolves to
# crew_leader users as CC partners (matches the constant value).
c_t7721 = Cert.sudo().create({
    "user_id": u_subject.id,
    "type_id": env.ref(
        "neon_training.cert_type_avolites_tiger_touch").id,  # lead_tech
    "date_obtained": date.today() - timedelta(days=1),
})
cc_partners = c_t7721._resolve_cc_partners()
expected_partners = env.ref(
    "neon_jobs.group_neon_jobs_crew_leader").users.partner_id
ok = cc_partners == expected_partners
print("  cc_partners count:", len(cc_partners),
      " expected count:", len(expected_partners),
      " match:", ok)
print("T7721:", "PASS" if ok else "FAIL")
results["T7721"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in range(7700, 7722)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
