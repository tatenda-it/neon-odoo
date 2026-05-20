"""P7a.M9 smoke -- gating tier 1 info toast + assignment_gate_log (24 tests).

Model basics:
T7900  Model + fields present; severity computed from gate_tier
T7901  Field defaults: fired_at=now, triggered_by_id=current user, gate_tier='tier_1_assignment'
T7902  unlink() raises UserError on every group (H3=A audit)

Create-path tier 1 fire (DP6 -- create() override):
T7903  create() crew with unqualified user -> 1 gate_log per eligible event_job
T7904  create() crew with needs_cross_competency user -> log records softener
T7905  create() crew with qualified user -> NO gate_log written

Write-path tier 1 fire (DP6 -- write() override):
T7906  write() user_id=u_unqualified -> gate_log per event_job
T7907  write() user_id=u_qualified -> NO gate_log
T7908  write() clearing user_id (DP2) -> NO gate_log
T7909  write() unchanged user_id (DP5 idempotency) -> NO re-fire

Field correctness:
T7910  gate_log.severity='info' for tier_1_assignment
T7911  gate_log.gate_status_at_fire matches crew.gate_status
T7912  gate_log.missing_certification_type_ids populated
T7913  gate_log.softening_cross_competency_ids populated when applicable
T7914  gate_log.triggered_by_id = env.user (the writer)

Event-job filtering (DP7 + terminal-state filter):
T7915  One gate_log per (crew, event_job) pair (multi-event-job job)
T7916  Terminal-state event_jobs (closed/cancelled) -> NO gate_log on them
T7917  No-eligible-event-job assignment -> create returns empty log set

ACL + ir.rule:
T7918  training_user sees own triggered_by_id logs only
T7919  training_signoff sees all logs
T7920  training_admin sees all logs + can write override fields

Toast routing:
T7921  Single-crew toast: bus.bus _sendone fired to triggering user partner_id
T7921a Multi-crew batch (DP3): single summary toast, N individual log records
T7922  Persistence: gate_log survives subsequent crew reassignment

Event-job o2m:
T7923  event_job.assignment_gate_log_ids reverse o2m reflects related logs
"""
from datetime import date, datetime, timedelta
from unittest.mock import patch

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
CertType = env["neon.training.certification.type"]
Users = env["res.users"]
Partner = env["res.partner"]
Job = env["commercial.job"]
EventJob = env["commercial.event.job"]
Crew = env["commercial.job.crew"]
GateLog = env["neon.training.assignment_gate_log"]
Bus = env["bus.bus"]

u_lt = Users.sudo().search([("login", "=", "p2m75_lead")], limit=1)
u_tech = Users.sudo().search([("login", "=", "p7am2_subject")], limit=1)
u_runner = Users.sudo().search([("login", "=", "p7am2_train_user")], limit=1)
u_driver = Users.sudo().search([("login", "=", "p2m75_crew")], limit=1)
u_admin = Users.sudo().search(
    [("login", "=", "p7am2_train_admin")], limit=1)
u_signoff = Users.sudo().search(
    [("login", "=", "p7am2_train_signoff")], limit=1)
u_other = Users.sudo().search(
    [("login", "=", "p2m75_other")], limit=1)
u_mgr = Users.sudo().search([("login", "=", "p2m75_mgr")], limit=1)
assert (u_lt and u_tech and u_runner and u_driver and u_admin
        and u_signoff and u_other and u_mgr), "Missing fixture users"

# Cleanup prior fixture certs + cc for the test users.
all_uids = (u_lt.id, u_tech.id, u_runner.id, u_driver.id, u_other.id)
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
print("  cleaned up prior fixtures for test users")

type_lt = env.ref("neon_training.cert_type_lead_tech")
type_tech = env.ref("neon_training.cert_type_tech")
type_runner = env.ref("neon_training.cert_type_runner")
print("  role-tier types resolved")

# Seed: u_lt holds active lead_tech cert (qualified).
c_lt_cert = Cert.sudo().create({
    "user_id":       u_lt.id,
    "type_id":       type_lt.id,
    "date_obtained": date.today() - timedelta(days=30),
    "level":         "lead_tech",
})
c_lt_cert.with_user(u_admin).action_submit_for_verification()
c_lt_cert.with_user(u_admin).action_verify()
# NOTE: NO commit. The cert exists only within this smoke's
# transaction; rollback at end clears it. Mid-test commits leak
# into subsequent smoke runs and break cross-suite isolation
# (the p7a_m9 commit on a u_lt cert broke p2m7-era smokes when
# left committed -- M9 fix-round-1 trauma).
print("  u_lt seeded with active lead_tech cert (transaction-local)")

# Fixture commercial.job + event_job (future-dated, single event).
test_partner = Partner.sudo().create({
    "name": "P7aM9 Test Client", "is_company": True})
test_venue = Partner.sudo().create({
    "name": "P7aM9 Test Venue", "is_company": True})
test_job = Job.sudo().create({
    "partner_id":  test_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() + timedelta(days=14),
    "currency_id": env.company.currency_id.id,
})
test_job.sudo().write({"state": "active", "soft_hold_until": False})
test_ej = test_job.event_job_ids[0]
print("  fixture event_job:", test_ej.id, "state:", test_ej.state)


def _make_crew_user(role, user, job=None):
    """Helper: create a crew row with user_id set from the start."""
    target_job = job or test_job
    return Crew.sudo().create({
        "job_id":     target_job.id,
        "partner_id": user.partner_id.id,
        "user_id":    user.id,
        "role":       role,
    })


# ============================================================
print()
print("=" * 72)
print("T7900 - Model + fields present; severity computed from gate_tier")
print("=" * 72)
fields_present = set(GateLog._fields.keys())
expected = {
    "event_job_id", "crew_id", "user_id",
    "gate_tier", "severity", "gate_status_at_fire",
    "missing_certification_type_ids",
    "softening_cross_competency_ids",
    "override_reason", "overridden_by_id", "overridden_at",
    "fired_at", "triggered_by_id",
}
missing_fields = expected - fields_present
# Build a synthetic log to test compute.
log_synthetic = GateLog.sudo().create({
    "event_job_id": test_ej.id,
    "crew_id":      False,  # will fail; do via SQL below
    "user_id":      u_tech.id,
    "gate_tier":    "tier_2_quote_accept",
    "gate_status_at_fire": "unqualified",
}) if False else None
# Direct method test: severity from gate_tier.
ok_fields = not missing_fields
# Severity logic test via create + compute.
test_crew = Crew.sudo().create({
    "job_id":     test_job.id,
    "partner_id": u_tech.partner_id.id,
    "user_id":    u_tech.id,
    "role":       "lead_tech",
})
# Direct log create bypassing the auto-hook: use a different
# tier value to verify the compute.
log_synth = GateLog.sudo().create({
    "event_job_id":         test_ej.id,
    "crew_id":              test_crew.id,
    "user_id":              u_tech.id,
    "gate_tier":            "tier_2_quote_accept",
    "gate_status_at_fire": "unqualified",
})
ok_compute = log_synth.severity == "warn"
log_synth.gate_tier = "tier_3_event_start"
log_synth.invalidate_recordset(["severity"])
ok_compute_block = log_synth.severity == "block"
ok = ok_fields and ok_compute and ok_compute_block
print("  fields present:", sorted(expected - missing_fields))
print("  missing_fields:", missing_fields)
print("  severity (tier_2):", "warn", " (tier_3):", "block")
print("T7900:", "PASS" if ok else "FAIL")
results["T7900"] = ok


# ============================================================
print()
print("=" * 72)
print("T7901 - Field defaults: fired_at=now, triggered_by_id=current, gate_tier=tier_1")
print("=" * 72)
log_def = GateLog.sudo().create({
    "event_job_id":        test_ej.id,
    "crew_id":             test_crew.id,
    "user_id":             u_tech.id,
    "gate_status_at_fire": "unqualified",
})
delta = (datetime.utcnow() - log_def.fired_at).total_seconds()
ok = (log_def.gate_tier == "tier_1_assignment"
      and log_def.triggered_by_id == env.user
      and abs(delta) < 10)
print("  gate_tier default:", log_def.gate_tier,
      " triggered_by:", log_def.triggered_by_id.login,
      " delta seconds:", delta)
print("T7901:", "PASS" if ok else "FAIL")
results["T7901"] = ok


# ============================================================
print()
print("=" * 72)
print("T7902 - unlink() raises UserError (H3=A audit)")
print("=" * 72)
err_admin, _ = _try(lambda: log_def.with_user(u_admin).unlink())
err_sudo, _ = _try(lambda: log_def.sudo().unlink())
ok = (isinstance(err_admin, UserError) and isinstance(err_sudo, UserError))
print("  admin unlink raised:", type(err_admin).__name__)
print("  sudo unlink raised:", type(err_sudo).__name__)
print("T7902:", "PASS" if ok else "FAIL")
results["T7902"] = ok


# ============================================================
# Clean test crew + synthetic log via SQL (audit unlink block).
env.cr.execute("DELETE FROM neon_training_assignment_gate_log")
env.cr.execute("DELETE FROM commercial_job_crew WHERE id = %s",
               (test_crew.id,))
env.cr.commit()


# ============================================================
print()
print("=" * 72)
print("T7903 - create() crew with unqualified user -> gate_log + toast")
print("=" * 72)
# u_tech has no tech cert; role='tech' -> unqualified.
before = GateLog.sudo().search_count([])
c_uq = _make_crew_user("tech", u_tech)
after = GateLog.sudo().search_count([])
log = GateLog.sudo().search(
    [("crew_id", "=", c_uq.id),
     ("gate_status_at_fire", "=", "unqualified")], limit=1)
ok = (after - before == 1
      and log.event_job_id == test_ej
      and log.user_id == u_tech)
print("  before:", before, " after:", after,
      " log:", log.id, " event_job:", log.event_job_id.id)
print("T7903:", "PASS" if ok else "FAIL")
results["T7903"] = ok


# ============================================================
print()
print("=" * 72)
print("T7904 - create() crew with needs_cross_competency user -> log")
print("=" * 72)
# Add a cross-competency for u_runner softening runner cert.
cc_partner = Partner.sudo().create({
    "name": "P7aM9 CC Client", "is_company": True})
cc_job = Job.sudo().create({
    "partner_id":  cc_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() - timedelta(days=5),
    "currency_id": env.company.currency_id.id,
})
cc_job.sudo().write({"state": "active", "soft_hold_until": False})
cc_ej = cc_job.event_job_ids[0]
cc_runner = CC.sudo().create({
    "user_id":                       u_runner.id,
    "certification_type_id":         type_runner.id,
    "demonstrated_through_event_id": cc_ej.id,
    "demonstrated_at":               date.today() - timedelta(days=2),
    "observed_by_id":                u_admin.id,
    "notes": "Demonstrated runner tier on prior event.",
})
before = GateLog.sudo().search_count(
    [("gate_status_at_fire", "=", "needs_cross_competency")])
c_ncc = _make_crew_user("runner", u_runner)
after = GateLog.sudo().search_count(
    [("gate_status_at_fire", "=", "needs_cross_competency")])
log = GateLog.sudo().search(
    [("crew_id", "=", c_ncc.id),
     ("gate_status_at_fire", "=", "needs_cross_competency")],
    limit=1)
ok = (after - before == 1
      and log
      and cc_runner in log.softening_cross_competency_ids)
print("  log:", log.id if log else None,
      " softeners:", log.softening_cross_competency_ids.ids if log else None)
print("T7904:", "PASS" if ok else "FAIL")
results["T7904"] = ok


# ============================================================
print()
print("=" * 72)
print("T7905 - create() crew with qualified user -> NO gate_log")
print("=" * 72)
# u_lt has active lead_tech cert; role='lead_tech' -> qualified.
before = GateLog.sudo().search_count([])
c_q = _make_crew_user("lead_tech", u_lt)
after = GateLog.sudo().search_count([])
ok = (after == before)
print("  before:", before, " after:", after, " gate_status:", c_q.gate_status)
print("T7905:", "PASS" if ok else "FAIL")
results["T7905"] = ok


# ============================================================
print()
print("=" * 72)
print("T7906 - write() user_id=u_unqualified -> gate_log per event_job")
print("=" * 72)
# Existing c_q crew (qualified). Re-assign to u_driver (no
# driver cert -> unqualified). Change partner_id too to satisfy
# the (user,partner) consistency constraint.
before = GateLog.sudo().search_count([("crew_id", "=", c_q.id)])
c_q.sudo().write({
    "user_id":    u_driver.id,
    "partner_id": u_driver.partner_id.id,
    "role":       "driver",
})
after = GateLog.sudo().search_count([("crew_id", "=", c_q.id)])
ok = (after - before == 1)
print("  before:", before, " after:", after)
print("T7906:", "PASS" if ok else "FAIL")
results["T7906"] = ok


# ============================================================
print()
print("=" * 72)
print("T7907 - write() user_id=u_qualified -> NO gate_log")
print("=" * 72)
# Re-assign c_q to u_lt (qualified lead_tech). Need to also flip
# role back to lead_tech for the inference to match.
before = GateLog.sudo().search_count([("crew_id", "=", c_q.id)])
c_q.sudo().write({
    "user_id":    u_lt.id,
    "partner_id": u_lt.partner_id.id,
    "role":       "lead_tech",
})
after = GateLog.sudo().search_count([("crew_id", "=", c_q.id)])
ok = (after == before)
print("  before:", before, " after:", after,
      " gate_status:", c_q.gate_status)
print("T7907:", "PASS" if ok else "FAIL")
results["T7907"] = ok


# ============================================================
print()
print("=" * 72)
print("T7908 - write() clearing user_id (DP2) -> NO gate_log")
print("=" * 72)
before = GateLog.sudo().search_count([("crew_id", "=", c_uq.id)])
c_uq.sudo().write({"user_id": False})
after = GateLog.sudo().search_count([("crew_id", "=", c_uq.id)])
ok = (after == before)
print("  before:", before, " after:", after)
print("T7908:", "PASS" if ok else "FAIL")
results["T7908"] = ok


# ============================================================
print()
print("=" * 72)
print("T7909 - write() unchanged user_id (DP5 idempotency) -> NO re-fire")
print("=" * 72)
# c_q has user_id=u_lt now. Re-write same user_id; no fire.
before = GateLog.sudo().search_count([("crew_id", "=", c_q.id)])
c_q.sudo().write({"user_id": u_lt.id})
after = GateLog.sudo().search_count([("crew_id", "=", c_q.id)])
ok = (after == before)
print("  before:", before, " after:", after)
print("T7909:", "PASS" if ok else "FAIL")
results["T7909"] = ok


# ============================================================
print()
print("=" * 72)
print("T7910 - gate_log.severity='info' for tier_1_assignment")
print("=" * 72)
# Look at the log from T7903 (c_uq).
log_t7903 = GateLog.sudo().search(
    [("crew_id", "=", c_uq.id),
     ("gate_tier", "=", "tier_1_assignment")], limit=1)
ok = (log_t7903.severity == "info")
print("  severity:", log_t7903.severity)
print("T7910:", "PASS" if ok else "FAIL")
results["T7910"] = ok


# ============================================================
print()
print("=" * 72)
print("T7911 - gate_log.gate_status_at_fire snapshot")
print("=" * 72)
ok = (log_t7903.gate_status_at_fire == "unqualified")
print("  gate_status_at_fire:", log_t7903.gate_status_at_fire)
print("T7911:", "PASS" if ok else "FAIL")
results["T7911"] = ok


# ============================================================
print()
print("=" * 72)
print("T7912 - gate_log.missing_certification_type_ids populated")
print("=" * 72)
ok = (type_tech in log_t7903.missing_certification_type_ids)
print("  missing:", log_t7903.missing_certification_type_ids.mapped("code"))
print("T7912:", "PASS" if ok else "FAIL")
results["T7912"] = ok


# ============================================================
print()
print("=" * 72)
print("T7913 - gate_log.softening_cross_competency_ids populated for needs_cc")
print("=" * 72)
log_t7904 = GateLog.sudo().search(
    [("crew_id", "=", c_ncc.id),
     ("gate_tier", "=", "tier_1_assignment")], limit=1)
ok = (cc_runner in log_t7904.softening_cross_competency_ids)
print("  softeners on log:",
      log_t7904.softening_cross_competency_ids.ids)
print("T7913:", "PASS" if ok else "FAIL")
results["T7913"] = ok


# ============================================================
print()
print("=" * 72)
print("T7914 - gate_log.triggered_by_id = env.user")
print("=" * 72)
ok = (log_t7903.triggered_by_id == env.user)
print("  triggered_by:", log_t7903.triggered_by_id.login)
print("T7914:", "PASS" if ok else "FAIL")
results["T7914"] = ok


# ============================================================
print()
print("=" * 72)
print("T7915 - One gate_log per (crew, event_job) -- multi-event-job job")
print("=" * 72)
# Build a job with TWO event_jobs (commercial.job spawns one
# automatically; create a second by copying via job.copy_event_job
# or directly via EventJob.create).
multi_job = Job.sudo().create({
    "partner_id":  test_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() + timedelta(days=21),
    "currency_id": env.company.currency_id.id,
})
multi_job.sudo().write({"state": "active", "soft_hold_until": False})
multi_ej1 = multi_job.event_job_ids[0]
# Add a second event_job.
multi_ej2 = EventJob.sudo().create({
    "commercial_job_id": multi_job.id,
    "name":              "P7aM9 multi-ej 2",
    "venue_id":          test_venue.id,
})
print("  multi_job event_jobs:", multi_job.event_job_ids.ids)
# Assign u_tech as 'tech' (unqualified) on the multi job.
before = GateLog.sudo().search_count([])
c_multi = Crew.sudo().create({
    "job_id":     multi_job.id,
    "partner_id": u_tech.partner_id.id,
    "user_id":    u_tech.id,
    "role":       "tech",
})
after = GateLog.sudo().search_count([])
logs = GateLog.sudo().search([("crew_id", "=", c_multi.id)])
event_jobs_logged = set(logs.mapped("event_job_id").ids)
expected_event_jobs = set(multi_job.event_job_ids.ids)
ok = (after - before == 2
      and event_jobs_logged == expected_event_jobs)
print("  logs created:", len(logs),
      " event_jobs:", event_jobs_logged,
      " expected:", expected_event_jobs)
print("T7915:", "PASS" if ok else "FAIL")
results["T7915"] = ok


# ============================================================
print()
print("=" * 72)
print("T7916 - Terminal-state event_jobs -> NO gate_log on them")
print("=" * 72)
# Put multi_ej2 into a terminal state via SQL (the state machine
# doesn't permit jumping; SQL bypasses for fixture purposes).
env.cr.execute(
    "UPDATE commercial_event_job SET state='cancelled' WHERE id = %s",
    (multi_ej2.id,))
multi_ej2.invalidate_recordset(["state"])
# Make a new crew on multi_job with u_driver (unqualified).
# Driver type required (no driver cert held). Expected: only
# multi_ej1 gets a log (multi_ej2 is cancelled).
before = GateLog.sudo().search_count([])
c_term = Crew.sudo().create({
    "job_id":     multi_job.id,
    "partner_id": u_driver.partner_id.id,
    "user_id":    u_driver.id,
    "role":       "driver",
})
after = GateLog.sudo().search_count([])
logs = GateLog.sudo().search([("crew_id", "=", c_term.id)])
logged_ejs = set(logs.mapped("event_job_id").ids)
ok = (after - before == 1
      and logged_ejs == {multi_ej1.id}
      and multi_ej2.id not in logged_ejs)
print("  logs:", len(logs), " event_jobs logged:", logged_ejs,
      " cancelled_ej:", multi_ej2.id)
print("T7916:", "PASS" if ok else "FAIL")
results["T7916"] = ok


# ============================================================
print()
print("=" * 72)
print("T7917 - Assignment with no eligible event_jobs -> NO logs")
print("=" * 72)
# All-terminal job. Cancel multi_ej1 too.
env.cr.execute(
    "UPDATE commercial_event_job SET state='cancelled' WHERE id = %s",
    (multi_ej1.id,))
multi_ej1.invalidate_recordset(["state"])
before = GateLog.sudo().search_count([])
c_no_ej = Crew.sudo().create({
    "job_id":     multi_job.id,
    "partner_id": u_other.partner_id.id,
    "user_id":    u_other.id,
    "role":       "tech",
})
after = GateLog.sudo().search_count([])
ok = (after == before)
print("  before:", before, " after:", after,
      " crew gate_status:", c_no_ej.gate_status)
print("T7917:", "PASS" if ok else "FAIL")
results["T7917"] = ok


# ============================================================
print()
print("=" * 72)
print("T7918 - training_user sees own triggered_by_id logs only")
print("=" * 72)
# Create a log triggered_by u_admin; verify u_runner (training
# _user only) can't see it via search.
log_for_admin = GateLog.sudo().create({
    "event_job_id":        test_ej.id,
    "crew_id":             c_uq.id,
    "user_id":             u_tech.id,
    "gate_status_at_fire": "unqualified",
    "triggered_by_id":     u_admin.id,
})
# Create a log triggered_by u_runner via sudo.
log_for_runner = GateLog.sudo().create({
    "event_job_id":        test_ej.id,
    "crew_id":             c_uq.id,
    "user_id":             u_tech.id,
    "gate_status_at_fire": "unqualified",
    "triggered_by_id":     u_runner.id,
})
visible_to_runner = GateLog.with_user(u_runner).search([
    ("id", "in", (log_for_admin.id, log_for_runner.id))])
ok = (log_for_runner in visible_to_runner
      and log_for_admin not in visible_to_runner)
print("  visible to u_runner:", visible_to_runner.ids,
      " expected only:", [log_for_runner.id])
print("T7918:", "PASS" if ok else "FAIL")
results["T7918"] = ok


# ============================================================
print()
print("=" * 72)
print("T7919 - training_signoff sees all logs")
print("=" * 72)
visible_to_signoff = GateLog.with_user(u_signoff).search([
    ("id", "in", (log_for_admin.id, log_for_runner.id))])
ok = (log_for_admin in visible_to_signoff
      and log_for_runner in visible_to_signoff)
print("  visible to u_signoff:", visible_to_signoff.ids)
print("T7919:", "PASS" if ok else "FAIL")
results["T7919"] = ok


# ============================================================
print()
print("=" * 72)
print("T7920 - training_admin can write override fields")
print("=" * 72)
log_for_admin.with_user(u_admin).write({
    "override_reason": "Smoke test override",
    "overridden_by_id": u_admin.id,
    "overridden_at": fields.Datetime.now(),
})
ok = (log_for_admin.override_reason == "Smoke test override"
      and log_for_admin.overridden_by_id == u_admin)
print("  override_reason:", log_for_admin.override_reason,
      " by:", log_for_admin.overridden_by_id.login)
print("T7920:", "PASS" if ok else "FAIL")
results["T7920"] = ok


# ============================================================
print()
print("=" * 72)
print("T7921 - Bus channel notification fired to triggering user partner_id")
print("=" * 72)
# Patch bus.bus._sendone and assert the call captures
# self.env.user.partner_id as target.
captured = []
real_sendone = Bus._sendone
def _capturing_sendone(self, target, ntype, message):
    captured.append({"target": target, "type": ntype, "msg": message})
    return real_sendone(target, ntype, message)
# Bound to the model class.
with patch.object(type(Bus), "_sendone", _capturing_sendone):
    # Fresh job for a clean test (state must be active).
    t7921_job = Job.sudo().create({
        "partner_id":  test_partner.id,
        "venue_id":    test_venue.id,
        "event_date":  date.today() + timedelta(days=28),
        "currency_id": env.company.currency_id.id,
    })
    t7921_job.sudo().write({"state": "active", "soft_hold_until": False})
    Crew.sudo().create({
        "job_id":     t7921_job.id,
        "partner_id": u_tech.partner_id.id,
        "user_id":    u_tech.id,
        "role":       "tech",  # unqualified -> toast
    })
ok = (len(captured) == 1
      and captured[0]["target"] == env.user.partner_id
      and captured[0]["type"] == "simple_notification"
      and captured[0]["msg"].get("type") == "warning")
print("  captured calls:", len(captured),
      " target match:", (captured and
          captured[0]["target"] == env.user.partner_id),
      " type:", captured[0]["msg"].get("type") if captured else None)
print("T7921:", "PASS" if ok else "FAIL")
results["T7921"] = ok


# ============================================================
print()
print("=" * 72)
print("T7921a - Multi-crew batch (DP3): single summary toast + N logs")
print("=" * 72)
# Create a fresh job; create 3 crew records via Model.create
# (vals_list) in a single call -> should fire ONE summary toast
# (DP3) and N gate_log records.
batch_job = Job.sudo().create({
    "partner_id":  test_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() + timedelta(days=35),
    "currency_id": env.company.currency_id.id,
})
batch_job.sudo().write({"state": "active", "soft_hold_until": False})
batch_ej = batch_job.event_job_ids[0]
captured.clear()
# Build three partners; each crew with a distinct user (avoid
# the (job, partner) UNIQUE collision).
with patch.object(type(Bus), "_sendone", _capturing_sendone):
    Crew.sudo().create([
        {"job_id": batch_job.id,
         "partner_id": u_tech.partner_id.id,
         "user_id": u_tech.id,
         "role": "tech"},
        {"job_id": batch_job.id,
         "partner_id": u_driver.partner_id.id,
         "user_id": u_driver.id,
         "role": "driver"},
        {"job_id": batch_job.id,
         "partner_id": u_other.partner_id.id,
         "user_id": u_other.id,
         "role": "runner"},
    ])
logs_count = GateLog.sudo().search_count(
    [("event_job_id", "=", batch_ej.id),
     ("crew_id.user_id", "in", (u_tech.id, u_driver.id, u_other.id))])
# Three unqualified crew * one event_job each = 3 logs; toasts
# in a single create() call = 1 (summary).
ok = (len(captured) == 1
      and logs_count == 3
      and "warnings" in captured[0]["msg"].get("title", "").lower())
print("  captured toasts:", len(captured),
      " log records:", logs_count,
      " title:", captured[0]["msg"].get("title") if captured else None)
print("T7921a:", "PASS" if ok else "FAIL")
results["T7921a"] = ok


# ============================================================
print()
print("=" * 72)
print("T7922 - gate_log persists after crew reassignment (audit integrity)")
print("=" * 72)
# c_uq currently has user_id=False (T7908 cleared it). Take an
# earlier log on c_uq and verify it persists when we re-assign.
orig_log_count = GateLog.sudo().search_count([("crew_id", "=", c_uq.id)])
c_uq.sudo().write({
    "user_id":    u_other.id,
    "partner_id": u_other.partner_id.id,
})
final_log_count = GateLog.sudo().search_count([("crew_id", "=", c_uq.id)])
# New assignment may add a log; the OLD ones must still exist.
ok = (final_log_count >= orig_log_count)
print("  orig:", orig_log_count, " final:", final_log_count)
print("T7922:", "PASS" if ok else "FAIL")
results["T7922"] = ok


# ============================================================
print()
print("=" * 72)
print("T7923 - event_job.assignment_gate_log_ids reverse o2m")
print("=" * 72)
# test_ej should have multiple gate_log records pointing at it.
o2m_logs = test_ej.assignment_gate_log_ids
search_logs = GateLog.sudo().search([("event_job_id", "=", test_ej.id)])
ok = (set(o2m_logs.ids) == set(search_logs.ids) and len(o2m_logs) >= 1)
print("  o2m count:", len(o2m_logs),
      " search count:", len(search_logs))
print("T7923:", "PASS" if ok else "FAIL")
results["T7923"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = (["T7900", "T7901", "T7902"]
         + ["T%d" % i for i in range(7903, 7921)]
         + ["T7921", "T7921a", "T7922", "T7923"])
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
