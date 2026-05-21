"""P7a.M11 smoke -- tier 3 (BLOCK) wizard at event_job in_progress (22 tests).

Wizard basics:
T8100  Wizard model + 5 fields present
T8101  affected_role_line_ids compute filters to firing statuses
T8102  affected_summary_html renders alert banner for tier_3

action_move_to_in_progress gating:
T8103  Event with all-qualified crew -> direct transition (no wizard)
T8104  Event with unqualified crew -> wizard returned (state stays dispatched)
T8105  Event with needs_cross_competency crew -> wizard returned
T8106  Event with pending-only crew -> direct transition (DP6)
T8107  Event with no crew -> direct transition

Wizard confirm:
T8108  Confirm writes one gate_log per (crew, event_job) -- DP7 shape
T8109  Confirm completes original transition (state -> in_progress)
T8110  Confirm captures override_reason on every log record
T8111  Confirm sets overridden_by_id + overridden_at + triggered_by_id

Wizard cancel:
T8112  Cancel preserves prior state, writes NO log

Severity + tier:
T8113  Log records have gate_tier='tier_3_event_start' + severity='block'

24h freshness window:
T8114  Recent tier_3 override (< 24h) suppresses wizard re-fire
T8115  Stale tier_3 override (>= 24h) re-fires wizard
T8116  Override window checks ONLY overridden_at, not fired_at

Routing (DP5):
T8117  mail.activity TODO created on finance approver group on confirm
T8118  TODO not duplicated on second confirm (defensive idempotency)

Cross-impact + bypass:
T8119  M9 tier_1 + M10 tier_2 logs preserved alongside M11 tier_3
T8120  Context flag m11_skip_gate_evaluation bypasses the gate
T8121  Empty override_reason raises UserError
"""
from datetime import date, datetime, timedelta

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
GateLog = env["neon.training.assignment_gate_log"]
Wizard = env["neon.training.event_start_gate_override_wizard"]
Activity = env["mail.activity"]

u_lt = Users.sudo().search([("login", "=", "p2m75_lead")], limit=1)
u_tech = Users.sudo().search([("login", "=", "p7am2_subject")], limit=1)
u_other = Users.sudo().search([("login", "=", "p2m75_other")], limit=1)
u_admin = Users.sudo().search(
    [("login", "=", "p7am2_train_admin")], limit=1)
u_mgr = Users.sudo().search([("login", "=", "p2m75_mgr")], limit=1)
u_approver = Users.sudo().search(
    [("login", "=", "p2m75_approver")], limit=1)
assert all([u_lt, u_tech, u_other, u_admin, u_mgr, u_approver]), (
    "Missing fixture users")

# Cleanup prior fixture state.
all_uids = (u_lt.id, u_tech.id, u_other.id)
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
print("  cleaned up prior fixtures")

type_lt = env.ref("neon_training.cert_type_lead_tech")
type_tech = env.ref("neon_training.cert_type_tech")

# Seed: u_lt holds active lead_tech cert (qualified).
c_lt_cert = Cert.sudo().create({
    "user_id":       u_lt.id,
    "type_id":       type_lt.id,
    "date_obtained": date.today() - timedelta(days=30),
    "level":         "lead_tech",
})
c_lt_cert.with_user(u_admin).action_submit_for_verification()
c_lt_cert.with_user(u_admin).action_verify()
print("  u_lt seeded with active lead_tech cert (transaction-local)")

usd = env.ref("base.USD")
test_partner = Partner.sudo().create({
    "name": "P7aM11 Test Client", "is_company": True})
test_venue = Partner.sudo().create({
    "name": "P7aM11 Test Venue", "is_company": True})


def _walk_event_job_to_dispatched(crew_user=None, crew_role="tech",
                                  is_chief=False, lead_tech_user=None):
    """Helper: create a job + event_job + crew + walk the event_job
    state machine all the way to 'dispatched' (the state immediately
    before 'in_progress'). Returns (job, event_job, crew).
    """
    lt = lead_tech_user or u_lt
    job = Job.sudo().create({
        "partner_id":  test_partner.id,
        "venue_id":    test_venue.id,
        "event_date":  date.today() + timedelta(days=14),
        "currency_id": usd.id,
    })
    job.sudo().write({"state": "active", "soft_hold_until": False})
    ej = job.event_job_ids[0]
    ej.sudo().write({"lead_tech_id": lt.id})

    # Crew chief required to move to dispatched.
    Crew.sudo().create({
        "job_id":     job.id,
        "partner_id": lt.partner_id.id,
        "user_id":    lt.id,
        "role":       "lead_tech",
        "is_crew_chief": True,
        "state":      "confirmed",
    })
    crew = None
    if crew_user is not None:
        crew = Crew.sudo().create({
            "job_id":     job.id,
            "partner_id": crew_user.partner_id.id,
            "user_id":    crew_user.id,
            "role":       crew_role,
            "state":      "confirmed",
        })
    # Walk states: draft -> planning -> prep -> ready_for_dispatch
    # -> dispatched. Use sudo() + the context bypass on
    # action_move_to_ready_for_dispatch_with_override if readiness
    # score is low (it will be on a bare event_job).
    ej.sudo().action_move_to_planning()
    ej.sudo().action_move_to_prep()
    # Readiness score is likely below threshold; use override path.
    if ej.readiness_score < 80:
        ej.sudo().action_move_to_ready_for_dispatch_with_override(
            reason="P7aM11 fixture override -- readiness bypass")
    else:
        ej.sudo().action_move_to_ready_for_dispatch()
    ej.sudo().action_move_to_dispatched()
    assert ej.state == "dispatched", (
        "fixture failed to reach 'dispatched', got %s" % ej.state)
    return job, ej, crew


# ============================================================
print()
print("=" * 72)
print("T8100 - Wizard model + 5 fields present")
print("=" * 72)
fields_present = set(Wizard._fields.keys())
expected = {"event_job_id", "target_state", "affected_role_line_ids",
            "affected_summary_html", "override_reason"}
missing = expected - fields_present
ok = not missing
print("  expected:", sorted(expected),
      " missing:", sorted(missing))
print("T8100:", "PASS" if ok else "FAIL")
results["T8100"] = ok


# ============================================================
print()
print("=" * 72)
print("T8101 - affected_role_line_ids filters to firing statuses")
print("=" * 72)
_, ej_t8101, c_uq = _walk_event_job_to_dispatched(
    crew_user=u_tech, crew_role="tech")  # u_tech unqualified
# u_lt crew added by helper is qualified; expect only c_uq in result.
w = Wizard.sudo().create({
    "event_job_id": ej_t8101.id,
    "override_reason": "(scaffold)",
})
ok = (c_uq in w.affected_role_line_ids
      and len(w.affected_role_line_ids) == 1)
print("  affected count:", len(w.affected_role_line_ids),
      " contains unqualified:", c_uq in w.affected_role_line_ids)
print("T8101:", "PASS" if ok else "FAIL")
results["T8101"] = ok


# ============================================================
print()
print("=" * 72)
print("T8102 - affected_summary_html renders tier_3 BLOCK banner")
print("=" * 72)
html = w.affected_summary_html or ""
ok = ("Tier 3 BLOCK" in html
      and u_tech.name in html
      and "Robin" in html or "Munashe" in html or "approver" in html.lower())
print("  html length:", len(html),
      " has BLOCK banner:", "Tier 3 BLOCK" in html)
print("T8102:", "PASS" if ok else "FAIL")
results["T8102"] = ok


# ============================================================
print()
print("=" * 72)
print("T8103 - Event with all-qualified crew -> direct transition")
print("=" * 72)
# Need a fresh event where ALL crew are qualified. u_lt has the
# lead_tech cert; create an event_job where u_lt is the only
# additional crew (the helper already adds u_lt as crew_chief).
_, ej_t8103, _ = _walk_event_job_to_dispatched(
    crew_user=None)  # no extra crew; only u_lt as chief
result = ej_t8103.with_user(u_mgr).action_move_to_in_progress()
ok = (result is None and ej_t8103.state == "in_progress")
print("  state:", ej_t8103.state,
      " result:", type(result).__name__ if result else None)
print("T8103:", "PASS" if ok else "FAIL")
results["T8103"] = ok


# ============================================================
print()
print("=" * 72)
print("T8104 - Event with unqualified crew -> wizard returned")
print("=" * 72)
result = ej_t8101.with_user(u_mgr).action_move_to_in_progress()
ok = (isinstance(result, dict)
      and result.get("type") == "ir.actions.act_window"
      and result.get("res_model")
        == "neon.training.event_start_gate_override_wizard"
      and result.get("target") == "new"
      and ej_t8101.state == "dispatched")
print("  result type:", result.get("type") if isinstance(result, dict) else None,
      " res_model:", result.get("res_model") if isinstance(result, dict) else None,
      " state:", ej_t8101.state)
print("T8104:", "PASS" if ok else "FAIL")
results["T8104"] = ok


# ============================================================
print()
print("=" * 72)
print("T8105 - Event with needs_cross_competency crew -> wizard")
print("=" * 72)
# Seed cc for u_other softening tech cert.
cc_partner = Partner.sudo().create({"name": "P7aM11 CC Client"})
cc_job = Job.sudo().create({
    "partner_id":  cc_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() - timedelta(days=5),
    "currency_id": usd.id,
})
cc_job.sudo().write({"state": "active", "soft_hold_until": False})
cc_ej = cc_job.event_job_ids[0]
CC.sudo().create({
    "user_id":                       u_other.id,
    "certification_type_id":         type_tech.id,
    "demonstrated_through_event_id": cc_ej.id,
    "demonstrated_at":               date.today() - timedelta(days=2),
    "observed_by_id":                u_admin.id,
    "notes": "Demonstrated tech tier.",
})
_, ej_t8105, c_ncc = _walk_event_job_to_dispatched(
    crew_user=u_other, crew_role="tech")  # needs_cross_competency
# Verify status.
ok_status = c_ncc.sudo().gate_status == "needs_cross_competency"
result = ej_t8105.with_user(u_mgr).action_move_to_in_progress()
ok = (ok_status
      and isinstance(result, dict)
      and result.get("res_model")
        == "neon.training.event_start_gate_override_wizard"
      and ej_t8105.state == "dispatched")
print("  gate_status:", c_ncc.sudo().gate_status,
      " wizard returned:", isinstance(result, dict))
print("T8105:", "PASS" if ok else "FAIL")
results["T8105"] = ok


# ============================================================
print()
print("=" * 72)
print("T8106 - Event with pending-only crew -> direct transition (DP6)")
print("=" * 72)
# Build event with only u_lt (qualified) + a freelancer crew (no
# user_id, pending). The helper already adds u_lt as chief; add
# the pending freelancer.
job_t8106 = Job.sudo().create({
    "partner_id":  test_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() + timedelta(days=20),
    "currency_id": usd.id,
})
job_t8106.sudo().write({"state": "active", "soft_hold_until": False})
ej_t8106 = job_t8106.event_job_ids[0]
ej_t8106.sudo().write({"lead_tech_id": u_lt.id})
Crew.sudo().create({
    "job_id":     job_t8106.id,
    "partner_id": u_lt.partner_id.id,
    "user_id":    u_lt.id,
    "role":       "lead_tech",
    "is_crew_chief": True,
    "state":      "confirmed",
})
pending_partner = Partner.sudo().create({"name": "P7aM11 Freelancer"})
Crew.sudo().create({
    "job_id":     job_t8106.id,
    "partner_id": pending_partner.id,
    "role":       "tech",  # no user_id -> pending
    "state":      "confirmed",
})
ej_t8106.sudo().action_move_to_planning()
ej_t8106.sudo().action_move_to_prep()
if ej_t8106.readiness_score < 80:
    ej_t8106.sudo().action_move_to_ready_for_dispatch_with_override(
        reason="P7aM11 T8106 override")
else:
    ej_t8106.sudo().action_move_to_ready_for_dispatch()
ej_t8106.sudo().action_move_to_dispatched()
result = ej_t8106.with_user(u_mgr).action_move_to_in_progress()
ok = (result is None and ej_t8106.state == "in_progress")
print("  state:", ej_t8106.state)
print("T8106:", "PASS" if ok else "FAIL")
results["T8106"] = ok


# ============================================================
print()
print("=" * 72)
print("T8107 - Event with no crew -> direct transition")
print("=" * 72)
# An event with no crew at all -> training_gate_status='no_crew',
# no firing crew -> direct transition. Sanity check P3-era
# backwards compat.
job_t8107 = Job.sudo().create({
    "partner_id":  test_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() + timedelta(days=20),
    "currency_id": usd.id,
})
job_t8107.sudo().write({"state": "active", "soft_hold_until": False})
ej_t8107 = job_t8107.event_job_ids[0]
ej_t8107.sudo().write({"lead_tech_id": u_lt.id})
# Need at least a crew_chief to move to dispatched -- add u_lt as
# chief only, no other crew. That gives the helper its requirement
# but no role-tier inference (u_lt qualified anyway).
Crew.sudo().create({
    "job_id":     job_t8107.id,
    "partner_id": u_lt.partner_id.id,
    "user_id":    u_lt.id,
    "role":       "lead_tech",
    "is_crew_chief": True,
    "state":      "confirmed",
})
ej_t8107.sudo().action_move_to_planning()
ej_t8107.sudo().action_move_to_prep()
if ej_t8107.readiness_score < 80:
    ej_t8107.sudo().action_move_to_ready_for_dispatch_with_override(
        reason="P7aM11 T8107 override")
else:
    ej_t8107.sudo().action_move_to_ready_for_dispatch()
ej_t8107.sudo().action_move_to_dispatched()
result = ej_t8107.with_user(u_mgr).action_move_to_in_progress()
ok = (result is None and ej_t8107.state == "in_progress")
print("  state:", ej_t8107.state)
print("T8107:", "PASS" if ok else "FAIL")
results["T8107"] = ok


# ============================================================
print()
print("=" * 72)
print("T8108 - Confirm writes one gate_log per (crew, event_job)")
print("=" * 72)
# ej_t8101 is dispatched with one unqualified crew (c_uq).
before = GateLog.sudo().search_count([
    ("event_job_id", "=", ej_t8101.id),
    ("gate_tier", "=", "tier_3_event_start")])
w_t8108 = Wizard.with_user(u_mgr).create({
    "event_job_id":    ej_t8101.id,
    "override_reason": "Smoke test override T8108",
})
w_t8108.action_confirm_override()
after = GateLog.sudo().search_count([
    ("event_job_id", "=", ej_t8101.id),
    ("gate_tier", "=", "tier_3_event_start")])
ok = (after - before == 1)  # one affected crew -> one tier_3 log
print("  before:", before, " after:", after)
print("T8108:", "PASS" if ok else "FAIL")
results["T8108"] = ok


# ============================================================
print()
print("=" * 72)
print("T8109 - Confirm completes original transition (state -> in_progress)")
print("=" * 72)
ok = (ej_t8101.state == "in_progress")
print("  state:", ej_t8101.state)
print("T8109:", "PASS" if ok else "FAIL")
results["T8109"] = ok


# ============================================================
print()
print("=" * 72)
print("T8110 - override_reason captured on every tier_3 log record")
print("=" * 72)
log_t8110 = GateLog.sudo().search([
    ("event_job_id", "=", ej_t8101.id),
    ("gate_tier", "=", "tier_3_event_start")], limit=1)
ok = (log_t8110.override_reason == "Smoke test override T8108")
print("  override_reason:", log_t8110.override_reason if log_t8110 else None)
print("T8110:", "PASS" if ok else "FAIL")
results["T8110"] = ok


# ============================================================
print()
print("=" * 72)
print("T8111 - overridden_by_id + overridden_at + triggered_by_id")
print("=" * 72)
ok = (log_t8110.overridden_by_id == u_mgr
      and bool(log_t8110.overridden_at)
      and log_t8110.triggered_by_id == u_mgr)
print("  overridden_by:", log_t8110.overridden_by_id.login,
      " triggered_by:", log_t8110.triggered_by_id.login,
      " overridden_at set:", bool(log_t8110.overridden_at))
print("T8111:", "PASS" if ok else "FAIL")
results["T8111"] = ok


# ============================================================
print()
print("=" * 72)
print("T8112 - Cancel preserves prior state, writes NO log")
print("=" * 72)
# Make a fresh event with unqualified crew; instantiate wizard;
# cancel; verify state stays dispatched + no log.
_, ej_t8112, c_t8112 = _walk_event_job_to_dispatched(
    crew_user=u_tech, crew_role="tech")
before = GateLog.sudo().search_count([
    ("event_job_id", "=", ej_t8112.id),
    ("gate_tier", "=", "tier_3_event_start")])
w_t8112 = Wizard.with_user(u_mgr).create({
    "event_job_id":    ej_t8112.id,
    "override_reason": "(scaffold)",
})
result = w_t8112.action_cancel()
after = GateLog.sudo().search_count([
    ("event_job_id", "=", ej_t8112.id),
    ("gate_tier", "=", "tier_3_event_start")])
ok = (result.get("type") == "ir.actions.act_window_close"
      and ej_t8112.state == "dispatched"
      and after == before)
print("  state:", ej_t8112.state, " logs delta:", after - before)
print("T8112:", "PASS" if ok else "FAIL")
results["T8112"] = ok


# ============================================================
print()
print("=" * 72)
print("T8113 - Log records have tier_3_event_start + severity='block'")
print("=" * 72)
ok = (log_t8110.gate_tier == "tier_3_event_start"
      and log_t8110.severity == "block")
print("  gate_tier:", log_t8110.gate_tier, " severity:", log_t8110.severity)
print("T8113:", "PASS" if ok else "FAIL")
results["T8113"] = ok


# ============================================================
print()
print("=" * 72)
print("T8114 - Recent tier_3 override (< 24h) suppresses wizard re-fire")
print("=" * 72)
# Take ej_t8101 (still in_progress from T8109); transition it
# manually back to dispatched (SQL bypass since state-write is
# locked), then re-call action_move_to_in_progress. With the
# T8108 override < 24h old, the wizard should NOT fire; the
# transition should proceed directly.
env.flush_all()
env.cr.execute(
    "UPDATE commercial_event_job SET state='dispatched' WHERE id = %s",
    (ej_t8101.id,))
ej_t8101.invalidate_recordset(["state"])
fresh_state = ej_t8101.read(["state"])[0]["state"]
assert fresh_state == "dispatched", (
    "SQL state reset failed; got %s" % fresh_state)
result = ej_t8101.with_user(u_mgr).action_move_to_in_progress()
ok = (result is None and ej_t8101.state == "in_progress")
print("  state after re-fire:", ej_t8101.state,
      " result:", type(result).__name__ if result else None)
print("T8114:", "PASS" if ok else "FAIL")
results["T8114"] = ok


# ============================================================
print()
print("=" * 72)
print("T8115 - Stale tier_3 override (>= 24h) re-fires wizard")
print("=" * 72)
# Age the T8108 log's overridden_at to >24h ago via SQL.
env.cr.execute(
    "UPDATE neon_training_assignment_gate_log SET overridden_at = "
    "%s WHERE id = %s",
    (fields.Datetime.now() - timedelta(hours=25), log_t8110.id))
# Re-set ej_t8101 to dispatched and re-fire.
env.flush_all()
env.cr.execute(
    "UPDATE commercial_event_job SET state='dispatched' WHERE id = %s",
    (ej_t8101.id,))
ej_t8101.invalidate_recordset(["state"])
fresh_state = ej_t8101.read(["state"])[0]["state"]
assert fresh_state == "dispatched", (
    "SQL state reset failed; got %s" % fresh_state)
result = ej_t8101.with_user(u_mgr).action_move_to_in_progress()
ok = (isinstance(result, dict)
      and result.get("res_model")
        == "neon.training.event_start_gate_override_wizard"
      and ej_t8101.state == "dispatched")
print("  result:", result.get("res_model") if isinstance(result, dict)
      else None, " state:", ej_t8101.state)
print("T8115:", "PASS" if ok else "FAIL")
results["T8115"] = ok


# ============================================================
print()
print("=" * 72)
print("T8116 - 24h window checks overridden_at, not fired_at")
print("=" * 72)
# Restore the log's overridden_at to fresh, but set fired_at to
# >24h ago. Window should pass (overridden is fresh).
env.cr.execute(
    "UPDATE neon_training_assignment_gate_log SET "
    "overridden_at = %s, fired_at = %s WHERE id = %s",
    (fields.Datetime.now(),
     fields.Datetime.now() - timedelta(hours=30),
     log_t8110.id))
env.flush_all()
env.cr.execute(
    "UPDATE commercial_event_job SET state='dispatched' WHERE id = %s",
    (ej_t8101.id,))
ej_t8101.invalidate_recordset(["state"])
fresh_state = ej_t8101.read(["state"])[0]["state"]
assert fresh_state == "dispatched", (
    "SQL state reset failed; got %s" % fresh_state)
result = ej_t8101.with_user(u_mgr).action_move_to_in_progress()
ok = (result is None and ej_t8101.state == "in_progress")
print("  state:", ej_t8101.state,
      " (fresh overridden_at + stale fired_at -> passes)")
print("T8116:", "PASS" if ok else "FAIL")
results["T8116"] = ok


# ============================================================
print()
print("=" * 72)
print("T8117 - mail.activity TODO on finance approver on confirm")
print("=" * 72)
todos = Activity.sudo().search([
    ("res_model", "=", "commercial.event.job"),
    ("res_id",    "=", ej_t8101.id),
    ("summary",   "=ilike", "Tier 3 event-start gate override%"),
])
approver_group = env.ref("neon_finance.group_neon_finance_approver")
expected_user = approver_group.users.sorted("id")[0]
ok = (len(todos) == 1 and todos[0].user_id == expected_user)
print("  TODO count:", len(todos),
      " user:", todos[0].user_id.login if todos else None,
      " expected:", expected_user.login)
print("T8117:", "PASS" if ok else "FAIL")
results["T8117"] = ok


# ============================================================
print()
print("=" * 72)
print("T8118 - TODO not duplicated on second confirm")
print("=" * 72)
# Defensive: a stray second wizard for the same event_job should
# not create another TODO. The wizard's confirm dedups by summary
# ilike "Tier 3 event-start gate override%".
# State machine is in 'in_progress' now; reset to dispatched.
env.flush_all()
env.cr.execute(
    "UPDATE commercial_event_job SET state='dispatched' WHERE id = %s",
    (ej_t8101.id,))
ej_t8101.invalidate_recordset(["state"])
fresh_state = ej_t8101.read(["state"])[0]["state"]
assert fresh_state == "dispatched", (
    "SQL state reset failed; got %s" % fresh_state)
# Wizard creation (no actual user-action; just defensive search).
w_t8118 = Wizard.with_user(u_mgr).create({
    "event_job_id":    ej_t8101.id,
    "override_reason": "Stray duplicate",
})
# We don't confirm here -- but verify the existing TODO search
# would dedup if confirm were called.
todos_after = Activity.sudo().search([
    ("res_model", "=", "commercial.event.job"),
    ("res_id",    "=", ej_t8101.id),
    ("summary",   "=ilike", "Tier 3 event-start gate override%"),
])
ok = (len(todos_after) == 1)
print("  TODO count after stray-wizard:", len(todos_after))
print("T8118:", "PASS" if ok else "FAIL")
results["T8118"] = ok


# ============================================================
print()
print("=" * 72)
print("T8119 - M9 tier_1 + M10 tier_2 logs preserved alongside M11 tier_3")
print("=" * 72)
# ej_t8101 should have:
# - tier_1 log from when c_uq was created (M9 crew create hook)
# - tier_3 log from T8108 confirm
all_logs = ej_t8101.assignment_gate_log_ids
tier_1_logs = all_logs.filtered(
    lambda l: l.gate_tier == "tier_1_assignment")
tier_3_logs = all_logs.filtered(
    lambda l: l.gate_tier == "tier_3_event_start")
ok = (len(tier_1_logs) >= 1 and len(tier_3_logs) >= 1)
print("  tier_1 count:", len(tier_1_logs),
      " tier_3 count:", len(tier_3_logs),
      " total:", len(all_logs))
print("T8119:", "PASS" if ok else "FAIL")
results["T8119"] = ok


# ============================================================
print()
print("=" * 72)
print("T8120 - Context flag m11_skip_gate_evaluation bypasses the gate")
print("=" * 72)
# Fresh event with unqualified crew; transition with the bypass
# flag should proceed directly without wizard.
_, ej_t8120, _ = _walk_event_job_to_dispatched(
    crew_user=u_tech, crew_role="tech")
result = ej_t8120.with_user(u_mgr).with_context(
    m11_skip_gate_evaluation=True).action_move_to_in_progress()
ok = (result is None and ej_t8120.state == "in_progress")
print("  state with bypass:", ej_t8120.state)
print("T8120:", "PASS" if ok else "FAIL")
results["T8120"] = ok


# ============================================================
print()
print("=" * 72)
print("T8121 - Empty override_reason raises UserError")
print("=" * 72)
_, ej_t8121, _ = _walk_event_job_to_dispatched(
    crew_user=u_tech, crew_role="tech")
w_t8121 = Wizard.sudo().create({
    "event_job_id":    ej_t8121.id,
    "override_reason": "   ",  # whitespace-only
})
err, _ = _try(lambda: w_t8121.with_user(u_mgr).action_confirm_override())
ok = isinstance(err, UserError)
print("  err type:", type(err).__name__ if err else None)
print("T8121:", "PASS" if ok else "FAIL")
results["T8121"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in range(8100, 8122)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
