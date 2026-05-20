"""P7a.M8 smoke -- event_job crew gate inference engine (24 tests).

Inference + gate-status computes on commercial.job.crew:
T7800  role='lead_tech' -> required cert_type_lead_tech inferred
T7801  role='tech' -> required cert_type_tech inferred
T7802  role='runner' -> required cert_type_runner inferred
T7803  role='driver' -> required cert_type_driver inferred
T7804  role='other' -> no role-tier required (only equipment)
T7805  No equipment lines -> equipment-based required is empty
T7806  Equipment line with cert mapping -> cert_type added to required

Gate status verdicts:
T7807  No user_id (freelancer) -> 'pending'
T7808  user_id with all required certs active -> 'qualified'
T7809  user_id with no required certs at all -> 'qualified' (trivial)
T7810  user_id missing role-tier cert, no softener -> 'unqualified'
T7811  user_id missing role-tier cert, softening cc -> 'needs_cross_competency'
T7812  Suspended cert does not count as held -> 'unqualified'
T7813  Expired cert does not count as held -> 'unqualified'

Diagnostics:
T7814  gate_missing_certification_ids matches required - held
T7815  gate_softening_used True only when status='needs_cross_competency'
T7816  gate_softening_cross_competency_ids restricted to user's cc records

Event-level roll-up on commercial.event.job:
T7817  No crew -> training_gate_status='no_crew'
T7818  All qualified -> 'qualified'
T7819  Any unqualified -> 'unqualified' (worst wins)
T7820  needs_cc + qualified mix -> 'needs_cross_competency'
T7821  pending crew only -> 'pending'

Helper method:
T7822  _action_check_training_gate(tier='info') always ok=True
T7823  _action_check_training_gate(tier='block') unqualified -> ok=False
T7824  _action_check_training_gate(tier='block') needs_cc -> ok=True (softener passes block)
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
CertType = env["neon.training.certification.type"]
CC = env["neon.training.cross_competency"]
Users = env["res.users"]
Partner = env["res.partner"]
Job = env["commercial.job"]
EventJob = env["commercial.event.job"]
Crew = env["commercial.job.crew"]

u_lt = Users.sudo().search(
    [("login", "=", "p2m75_lead")], limit=1)
u_tech = Users.sudo().search(
    [("login", "=", "p7am2_subject")], limit=1)
u_runner = Users.sudo().search(
    [("login", "=", "p7am2_train_user")], limit=1)
u_driver = Users.sudo().search(
    [("login", "=", "p2m75_crew")], limit=1)
u_admin = Users.sudo().search(
    [("login", "=", "p7am2_train_admin")], limit=1)
u_other = Users.sudo().search(
    [("login", "=", "p2m75_other")], limit=1)
assert (u_lt and u_tech and u_runner and u_driver and u_admin
        and u_other), "Missing fixture users"

# Cleanup prior fixture certs + cc for the four users so unique-
# active-per-(user, type) constraint doesn't trip.
all_uids = (u_lt.id, u_tech.id, u_runner.id, u_driver.id)
env.cr.execute(
    "DELETE FROM mail_activity WHERE res_model_id IN "
    "(SELECT id FROM ir_model WHERE model = "
    "'neon.training.certification') AND res_id IN "
    "(SELECT id FROM neon_training_certification WHERE "
    "user_id IN %s)", (all_uids,))
env.cr.execute(
    "DELETE FROM mail_message WHERE model = "
    "'neon.training.certification' AND res_id IN "
    "(SELECT id FROM neon_training_certification WHERE "
    "user_id IN %s)", (all_uids,))
env.cr.execute(
    "DELETE FROM neon_training_certification WHERE user_id IN %s",
    (all_uids,))
env.cr.execute(
    "DELETE FROM mail_message WHERE model = "
    "'neon.training.cross_competency' AND res_id IN "
    "(SELECT id FROM neon_training_cross_competency WHERE "
    "user_id IN %s)", (all_uids,))
env.cr.execute(
    "DELETE FROM neon_training_cross_competency WHERE user_id IN %s",
    (all_uids,))
env.cr.commit()
print("  cleaned up prior fixtures for 4 test users")

# Role-tier cert types from seed.
type_lt     = env.ref("neon_training.cert_type_lead_tech")
type_tech   = env.ref("neon_training.cert_type_tech")
type_runner = env.ref("neon_training.cert_type_runner")
type_driver = env.ref("neon_training.cert_type_driver")
type_first_aid = env.ref("neon_training.cert_type_first_aid")
print("  role-tier types resolved:",
      [type_lt.code, type_tech.code, type_runner.code, type_driver.code])

# Fixture commercial.job + event_job (no equipment lines yet -- T7806
# adds them).
test_partner = Partner.sudo().create({
    "name": "P7aM8 Test Client", "is_company": True})
test_venue = Partner.sudo().create({
    "name": "P7aM8 Test Venue", "is_company": True})
test_job = Job.sudo().create({
    "partner_id": test_partner.id,
    "venue_id": test_venue.id,
    "event_date": date.today() + timedelta(days=14),
    "currency_id": env.company.currency_id.id,
})
test_job.sudo().write({"state": "active", "soft_hold_until": False})
test_ej = test_job.event_job_ids[0]
print("  fixture event_job:", test_ej.id)


# ============================================================
# T7800-T7804: role-tier requirement inference
# ============================================================
def _make_crew(role, user=False, partner=None):
    """Create a crew assignment on test_job."""
    vals = {
        "job_id": test_job.id,
        "partner_id": (partner or (user.partner_id if user else u_lt.partner_id)).id,
        "role": role,
    }
    if user:
        vals["user_id"] = user.id
    return Crew.sudo().create(vals)


print()
print("=" * 72)
print("T7800 - role='lead_tech' -> required cert_type_lead_tech inferred")
print("=" * 72)
c_lt = _make_crew("lead_tech", user=u_lt)
ok = type_lt in c_lt.required_certification_type_ids
print("  required:", c_lt.required_certification_type_ids.mapped("code"),
      " has lead_tech:", ok)
print("T7800:", "PASS" if ok else "FAIL")
results["T7800"] = ok


print()
print("=" * 72)
print("T7801 - role='tech' -> required cert_type_tech inferred")
print("=" * 72)
c_tech = _make_crew("tech", user=u_tech)
ok = type_tech in c_tech.required_certification_type_ids
print("  required:", c_tech.required_certification_type_ids.mapped("code"))
print("T7801:", "PASS" if ok else "FAIL")
results["T7801"] = ok


print()
print("=" * 72)
print("T7802 - role='runner' -> required cert_type_runner inferred")
print("=" * 72)
c_runner = _make_crew("runner", user=u_runner)
ok = type_runner in c_runner.required_certification_type_ids
print("  required:", c_runner.required_certification_type_ids.mapped("code"))
print("T7802:", "PASS" if ok else "FAIL")
results["T7802"] = ok


print()
print("=" * 72)
print("T7803 - role='driver' -> required cert_type_driver inferred")
print("=" * 72)
c_driver = _make_crew("driver", user=u_driver)
ok = type_driver in c_driver.required_certification_type_ids
print("  required:", c_driver.required_certification_type_ids.mapped("code"))
print("T7803:", "PASS" if ok else "FAIL")
results["T7803"] = ok


print()
print("=" * 72)
print("T7804 - role='other' -> no role-tier required")
print("=" * 72)
# Use a fresh partner so unique (job, partner, role) isn't tripped.
other_partner = Partner.sudo().create({"name": "P7aM8 Other Crew"})
c_other = Crew.sudo().create({
    "job_id":     test_job.id,
    "partner_id": other_partner.id,
    "role":       "other",
})
# 'other' has no role-tier mapping; equipment is empty so required must be empty.
ok = len(c_other.required_certification_type_ids) == 0
print("  required count:", len(c_other.required_certification_type_ids))
print("T7804:", "PASS" if ok else "FAIL")
results["T7804"] = ok


# ============================================================
# T7805-T7806: equipment-based inference
# ============================================================
print()
print("=" * 72)
print("T7805 - no equipment lines -> equipment-based required empty")
print("=" * 72)
# c_lt already exists; equipment is empty on test_ej. Re-derive
# inference helper directly.
equip_certs = c_lt._infer_equipment_certifications()
ok = len(equip_certs) == 0
print("  equipment-based cert count:", len(equip_certs))
print("T7805:", "PASS" if ok else "FAIL")
results["T7805"] = ok


print()
print("=" * 72)
print("T7806 - equipment line with cert mapping -> cert in required")
print("=" * 72)
# Pick any product.template; bind first_aid type's equipment_model_id
# to it; add an equipment line on test_ej; expect first_aid in
# c_lt.required_certification_type_ids.
Product = env["product.template"]
prod = Product.sudo().search([], limit=1)
if prod and type_first_aid:
    type_first_aid.sudo().write({"equipment_model_id": prod.id})
    Eqline = env["commercial.event.job.equipment.line"]
    eqline = Eqline.sudo().create({
        "event_job_id":         test_ej.id,
        "product_template_id":  prod.id,
        "quantity_planned":     1,
    })
    # Invalidate the non-stored compute cache so the inference re-fires.
    c_lt.invalidate_recordset(["required_certification_type_ids"])
    required = c_lt.required_certification_type_ids
    ok = type_first_aid in required
    print("  required after equipment add:",
          required.mapped("code"), " has first_aid:", ok)
    # Cleanup for downstream tests (don't leave equipment lingering).
    eqline.sudo().unlink()
    type_first_aid.sudo().write({"equipment_model_id": False})
    c_lt.invalidate_recordset(["required_certification_type_ids"])
else:
    ok = False
    print("  FAIL: no product.template available for fixture")
print("T7806:", "PASS" if ok else "FAIL")
results["T7806"] = ok


# ============================================================
# T7807-T7813: gate_status verdicts
# ============================================================
print()
print("=" * 72)
print("T7807 - no user_id (freelancer) -> 'pending'")
print("=" * 72)
free_partner = Partner.sudo().create({"name": "P7aM8 Freelance Tech"})
c_free = Crew.sudo().create({
    "job_id":     test_job.id,
    "partner_id": free_partner.id,
    "role":       "tech",
    # no user_id -- freelancer
})
ok = c_free.gate_status == "pending"
print("  gate_status:", c_free.gate_status)
print("T7807:", "PASS" if ok else "FAIL")
results["T7807"] = ok


print()
print("=" * 72)
print("T7808 - user with required cert active -> 'qualified'")
print("=" * 72)
# Give u_lt the lead_tech cert, active.
c_lt_cert = Cert.sudo().create({
    "user_id":       u_lt.id,
    "type_id":       type_lt.id,
    "date_obtained": date.today() - timedelta(days=30),
    "level":         "lead_tech",
})
c_lt_cert.with_user(u_admin).action_submit_for_verification()
c_lt_cert.with_user(u_admin).action_verify()
# Force a recompute by invalidating cache.
c_lt.invalidate_recordset(["gate_status",
                           "required_certification_type_ids",
                           "gate_missing_certification_ids"])
ok = c_lt.gate_status == "qualified"
print("  gate_status:", c_lt.gate_status,
      " cert state:", c_lt_cert.state)
print("T7808:", "PASS" if ok else "FAIL")
results["T7808"] = ok


print()
print("=" * 72)
print("T7809 - role='other' + no equipment -> 'qualified' trivially")
print("=" * 72)
# c_other has role='other'; assign u_other as user_id. Update
# partner_id together to satisfy the (user, partner) consistency
# constraint. Use u_other (p2m75_other) -- distinct partner from
# every other crew on test_job to avoid (job, partner) UNIQUE trip.
c_other.sudo().write({
    "user_id":    u_other.id,
    "partner_id": u_other.partner_id.id,
})
c_other.invalidate_recordset(["gate_status",
                              "required_certification_type_ids"])
ok = c_other.gate_status == "qualified"
print("  gate_status:", c_other.gate_status,
      " required count:", len(c_other.required_certification_type_ids))
print("T7809:", "PASS" if ok else "FAIL")
results["T7809"] = ok


print()
print("=" * 72)
print("T7810 - user missing role-tier cert, no softener -> 'unqualified'")
print("=" * 72)
# c_tech: u_tech has no tech cert, no cc -> unqualified.
c_tech.invalidate_recordset(["gate_status",
                             "gate_missing_certification_ids"])
ok = c_tech.gate_status == "unqualified"
print("  gate_status:", c_tech.gate_status,
      " missing:", c_tech.gate_missing_certification_ids.mapped("code"))
print("T7810:", "PASS" if ok else "FAIL")
results["T7810"] = ok


print()
print("=" * 72)
print("T7811 - missing cert + softening cc -> 'needs_cross_competency'")
print("=" * 72)
# Create a cross-competency on u_tech for cert_type_tech. The
# event_job must be in the past for the demonstrated_at constraint,
# so build a fresh past-dated job for the cc fixture.
cc_partner = Partner.sudo().create({
    "name": "P7aM8 CC Client", "is_company": True})
cc_job = Job.sudo().create({
    "partner_id":  cc_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() - timedelta(days=5),
    "currency_id": env.company.currency_id.id,
})
cc_job.sudo().write({"state": "active", "soft_hold_until": False})
cc_ej = cc_job.event_job_ids[0]
cc_tech = CC.sudo().create({
    "user_id":                       u_tech.id,
    "certification_type_id":         type_tech.id,
    "demonstrated_through_event_id": cc_ej.id,
    "demonstrated_at":               date.today() - timedelta(days=2),
    "observed_by_id":                u_admin.id,
    "notes": "Demonstrated tech-tier competency on the job.",
})
c_tech.invalidate_recordset(["gate_status",
                             "gate_softening_cross_competency_ids",
                             "gate_softening_used",
                             "gate_missing_certification_ids"])
ok = c_tech.gate_status == "needs_cross_competency"
print("  gate_status:", c_tech.gate_status,
      " softeners:", c_tech.gate_softening_cross_competency_ids.ids,
      " softening_used:", c_tech.gate_softening_used)
print("T7811:", "PASS" if ok else "FAIL")
results["T7811"] = ok


print()
print("=" * 72)
print("T7812 - suspended cert does not count as held -> 'unqualified'")
print("=" * 72)
# Give u_runner a runner cert then suspend it; with no cc softener.
c_runner_cert = Cert.sudo().create({
    "user_id":       u_runner.id,
    "type_id":       type_runner.id,
    "date_obtained": date.today() - timedelta(days=30),
    "level":         "runner",
})
c_runner_cert.with_user(u_admin).action_submit_for_verification()
c_runner_cert.with_user(u_admin).action_verify()
# Now suspend.
c_runner_cert.with_user(u_admin).with_context(
    suspension_reason="Smoke fixture suspend").action_suspend()
c_runner.invalidate_recordset(["gate_status",
                               "gate_missing_certification_ids"])
ok = c_runner.gate_status == "unqualified"
print("  gate_status:", c_runner.gate_status,
      " cert state:", c_runner_cert.state)
print("T7812:", "PASS" if ok else "FAIL")
results["T7812"] = ok


print()
print("=" * 72)
print("T7813 - expired cert does not count as held -> 'unqualified'")
print("=" * 72)
# Give u_driver a driver cert, verify, then _action_force_expire it.
c_driver_cert = Cert.sudo().create({
    "user_id":       u_driver.id,
    "type_id":       type_driver.id,
    "date_obtained": date.today() - timedelta(days=30),
    "level":         "driver",
})
c_driver_cert.with_user(u_admin).action_submit_for_verification()
c_driver_cert.with_user(u_admin).action_verify()
# Force-expire via raw SQL (DP3 strict: state='expired' is set by
# cron only, and the smoke needs the terminal state regardless of
# the driver cert's validity_months). SQL bypasses the gate cleanly
# for fixture purposes; cache invalidation triggers a recompute.
env.cr.execute(
    "UPDATE neon_training_certification SET state='expired' "
    "WHERE id = %s", (c_driver_cert.id,))
c_driver_cert.invalidate_recordset(["state"])
c_driver.invalidate_recordset(["gate_status",
                               "gate_missing_certification_ids"])
ok = c_driver.gate_status == "unqualified"
print("  gate_status:", c_driver.gate_status,
      " cert state:", c_driver_cert.state)
print("T7813:", "PASS" if ok else "FAIL")
results["T7813"] = ok


# ============================================================
# T7814-T7816: diagnostics correctness
# ============================================================
print()
print("=" * 72)
print("T7814 - gate_missing_certification_ids matches required - held")
print("=" * 72)
# c_tech: required = {tech}; held = {} (cc doesn't count as held);
# missing should be {tech}.
ok = (set(c_tech.gate_missing_certification_ids.ids)
      == {type_tech.id})
print("  missing:", c_tech.gate_missing_certification_ids.mapped("code"),
      " expected: ['tech']")
print("T7814:", "PASS" if ok else "FAIL")
results["T7814"] = ok


print()
print("=" * 72)
print("T7815 - gate_softening_used True only when status='needs_cross_competency'")
print("=" * 72)
# c_tech is needs_cc -> True; c_lt is qualified -> False; c_runner is
# unqualified (no softener) -> False; c_free is pending -> False.
checks = [
    (c_tech,   "needs_cross_competency", True),
    (c_lt,     "qualified",              False),
    (c_runner, "unqualified",            False),
    (c_free,   "pending",                False),
]
ok = True
for crew, expected_status, expected_used in checks:
    crew.invalidate_recordset(["gate_softening_used", "gate_status"])
    if crew.gate_status != expected_status:
        ok = False
        print("  STATUS MISMATCH for crew", crew.id,
              ": got", crew.gate_status, " expected", expected_status)
    if bool(crew.gate_softening_used) != expected_used:
        ok = False
        print("  SOFT USED MISMATCH for crew", crew.id,
              ": got", crew.gate_softening_used,
              " expected", expected_used)
print("T7815:", "PASS" if ok else "FAIL")
results["T7815"] = ok


print()
print("=" * 72)
print("T7816 - gate_softening_cross_competency_ids restricted to user's cc")
print("=" * 72)
# c_tech softeners should include cc_tech only (not any other user's cc).
ok = c_tech.gate_softening_cross_competency_ids == cc_tech
print("  softeners:", c_tech.gate_softening_cross_competency_ids.ids,
      " expected:", [cc_tech.id])
print("T7816:", "PASS" if ok else "FAIL")
results["T7816"] = ok


# ============================================================
# T7817-T7821: event-level roll-up
# ============================================================
print()
print("=" * 72)
print("T7817 - empty crew -> training_gate_status='no_crew'")
print("=" * 72)
# Make a separate job + event_job with no crew.
empty_job = Job.sudo().create({
    "partner_id":  test_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() + timedelta(days=21),
    "currency_id": env.company.currency_id.id,
})
empty_job.sudo().write({"state": "active", "soft_hold_until": False})
empty_ej = empty_job.event_job_ids[0]
ok = empty_ej.training_gate_status == "no_crew"
print("  training_gate_status:", empty_ej.training_gate_status,
      " crew count:", len(empty_job.crew_assignment_ids))
print("T7817:", "PASS" if ok else "FAIL")
results["T7817"] = ok


print()
print("=" * 72)
print("T7818 - all crew qualified -> 'qualified'")
print("=" * 72)
# Build a fresh job whose only crew has all-qualified state.
q_job = Job.sudo().create({
    "partner_id":  test_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() + timedelta(days=28),
    "currency_id": env.company.currency_id.id,
})
q_job.sudo().write({"state": "active", "soft_hold_until": False})
q_ej = q_job.event_job_ids[0]
# u_lt already has active lead_tech cert (T7808 above).
Crew.sudo().create({
    "job_id":     q_job.id,
    "partner_id": u_lt.partner_id.id,
    "user_id":    u_lt.id,
    "role":       "lead_tech",
})
q_ej.invalidate_recordset(["training_gate_status"])
ok = q_ej.training_gate_status == "qualified"
print("  training_gate_status:", q_ej.training_gate_status)
print("T7818:", "PASS" if ok else "FAIL")
results["T7818"] = ok


print()
print("=" * 72)
print("T7819 - any unqualified -> 'unqualified' (worst wins)")
print("=" * 72)
# test_ej now has: c_lt (qualified), c_tech (needs_cc), c_runner
# (unqualified), c_driver (unqualified), c_other (qualified),
# c_free (pending). Worst = unqualified.
test_ej.invalidate_recordset(["training_gate_status"])
ok = test_ej.training_gate_status == "unqualified"
print("  training_gate_status:", test_ej.training_gate_status)
print("T7819:", "PASS" if ok else "FAIL")
results["T7819"] = ok


print()
print("=" * 72)
print("T7820 - needs_cc + qualified mix -> 'needs_cross_competency'")
print("=" * 72)
# Build a fresh job: one qualified crew (u_lt as lead_tech) + one
# needs_cc crew (u_tech as tech, with cc softener -- need a new
# event_job_id for the cc constraint, so reuse same job's event_job
# for the cc record).
ncc_job = Job.sudo().create({
    "partner_id":  test_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() + timedelta(days=35),
    "currency_id": env.company.currency_id.id,
})
ncc_job.sudo().write({"state": "active", "soft_hold_until": False})
ncc_ej = ncc_job.event_job_ids[0]
Crew.sudo().create({
    "job_id":     ncc_job.id,
    "partner_id": u_lt.partner_id.id,
    "user_id":    u_lt.id,
    "role":       "lead_tech",
})
Crew.sudo().create({
    "job_id":     ncc_job.id,
    "partner_id": u_tech.partner_id.id,
    "user_id":    u_tech.id,
    "role":       "tech",
})
ncc_ej.invalidate_recordset(["training_gate_status"])
ok = ncc_ej.training_gate_status == "needs_cross_competency"
print("  training_gate_status:", ncc_ej.training_gate_status)
print("T7820:", "PASS" if ok else "FAIL")
results["T7820"] = ok


print()
print("=" * 72)
print("T7821 - pending crew only -> 'pending'")
print("=" * 72)
p_job = Job.sudo().create({
    "partner_id":  test_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() + timedelta(days=42),
    "currency_id": env.company.currency_id.id,
})
p_job.sudo().write({"state": "active", "soft_hold_until": False})
p_ej = p_job.event_job_ids[0]
p_partner = Partner.sudo().create({"name": "P7aM8 Pending Crew"})
Crew.sudo().create({
    "job_id":     p_job.id,
    "partner_id": p_partner.id,
    "role":       "tech",
    # no user_id -> pending
})
p_ej.invalidate_recordset(["training_gate_status"])
ok = p_ej.training_gate_status == "pending"
print("  training_gate_status:", p_ej.training_gate_status)
print("T7821:", "PASS" if ok else "FAIL")
results["T7821"] = ok


# ============================================================
# T7822-T7824: _action_check_training_gate helper
# ============================================================
print()
print("=" * 72)
print("T7822 - _action_check_training_gate(tier='info') always ok=True")
print("=" * 72)
res = test_ej._action_check_training_gate(tier="info")
ok = (isinstance(res, dict)
      and res.get("ok") is True
      and res.get("tier") == "info"
      and res.get("status") == "unqualified"
      and "unqualified_crew_ids" in res
      and len(res["unqualified_crew_ids"]) >= 2)
print("  result:", {k: res.get(k) for k in
                    ("ok", "tier", "status", "message",
                     "softening_used")})
print("  unqualified_crew_ids:", res.get("unqualified_crew_ids"))
print("T7822:", "PASS" if ok else "FAIL")
results["T7822"] = ok


print()
print("=" * 72)
print("T7823 - tier='block': unqualified status -> ok=False")
print("=" * 72)
res = test_ej._action_check_training_gate(tier="block")
ok = (res.get("ok") is False
      and res.get("status") == "unqualified"
      and res.get("tier") == "block")
print("  result:", {k: res.get(k) for k in ("ok", "tier", "status")})
print("T7823:", "PASS" if ok else "FAIL")
results["T7823"] = ok


print()
print("=" * 72)
print("T7824 - tier='block': needs_cc -> ok=True (softener passes block)")
print("=" * 72)
res = ncc_ej._action_check_training_gate(tier="block")
ok = (res.get("ok") is True
      and res.get("status") == "needs_cross_competency"
      and res.get("tier") == "block"
      and res.get("softening_used") is True)
print("  result:", {k: res.get(k) for k in
                    ("ok", "tier", "status", "softening_used")})
print("T7824:", "PASS" if ok else "FAIL")
results["T7824"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in range(7800, 7825)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
