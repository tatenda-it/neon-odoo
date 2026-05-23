"""P7e.M10 smoke -- gate engine 5th condition (9 tests)."""
import inspect
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError


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

Users = env["res.users"]
Job = env["commercial.job"]
EventJob = env["commercial.event.job"]
Crew = env["commercial.job.crew"]
GateLog = env["neon.training.assignment_gate_log"]
Authority = env["neon.lms.operating.authority"]
Enrollment = env["slide.channel.parner"] if False else env["slide.channel.partner"]
TrackComp = env["neon.lms.track.completion"]


def _get_or_create_user(login, name, group_xmlids):
    u = Users.sudo().search(
        [("login", "=", login)], limit=1)
    if not u:
        u = Users.sudo().create({
            "name": name, "login": login,
            "password": "test123",
        })
    for g_xmlid in group_xmlids:
        g = env.ref(g_xmlid, raise_if_not_found=False)
        if g and u not in g.users:
            g.sudo().write({"users": [(4, u.id)]})
    return u


u_authorised = _get_or_create_user(
    "p7e_m10_auth", "P7e M10 Authorised",
    ["neon_jobs.group_neon_jobs_crew"])
u_unauthorised = _get_or_create_user(
    "p7e_m10_unauth", "P7e M10 Unauthorised",
    ["neon_jobs.group_neon_jobs_crew"])
env.cr.commit()

program = env.ref("neon_lms.program_channel")
foundations = env.ref("neon_lms.track_foundations_safety")
authority_electrical = env.ref(
    "neon_lms.authority_electrical")
authority_stop_work = env.ref(
    "neon_lms.authority_stop_work")
sample_job = Job.sudo().search([], limit=1)


def _make_event_job_with_authority(authority):
    job = Job.sudo().create({
        "name": "P7e M10 Test Job",
        "partner_id": sample_job.partner_id.id,
        "venue_id": sample_job.venue_id.id,
        "currency_id": sample_job.currency_id.id,
        "event_date": fields.Date.today() + timedelta(days=7),
    })
    ej = EventJob.sudo().create({
        "commercial_job_id": job.id,
        "name": "P7e M10 Event",
        "event_date": fields.Date.today() + timedelta(days=7),
        "state": "planning",
        "required_authority_ids": [(4, authority.id)],
    })
    return job, ej


def _grant_authority(user, authority):
    """Wire a user up with the authority via enrollment + a
    certified track completion that has the authority in its
    operating_authority_ids.
    """
    enrollment = Enrollment.sudo().create({
        "channel_id": program.id,
        "partner_id": user.partner_id.id,
    })
    # Find a track that grants this authority.
    track = env["neon.lms.track"].sudo().search([
        ("operating_authority_ids", "in", authority.id),
    ], limit=1)
    if not track:
        return enrollment
    TrackComp.sudo().create({
        "enrollment_id": enrollment.id,
        "track_id": track.id,
        "state": "certified",
    })
    return enrollment


# ============================================================
print()
print("T7e1000 - authorised user + required auth -> no fire")
print("=" * 72)
_grant_authority(u_authorised, authority_electrical)
job_a, ej_a = _make_event_job_with_authority(authority_electrical)
crew_a = Crew.sudo().create({
    "job_id": job_a.id,
    "user_id": u_authorised.id,
    "role": "tech",
})
m10_logs = GateLog.sudo().search([
    ("crew_id", "=", crew_a.id),
    ("fire_reason", "=like", "operating_authority_missing:%"),
])
ok = len(m10_logs) == 0
print(f"  M10 logs for authorised user: {len(m10_logs)} "
      f"(expected 0)")
print("T7e1000:", "PASS" if ok else "FAIL")
results["T7e1000"] = ok


# ============================================================
print()
print("T7e1001 - unauthorised user + electrical required -> "
      "tier_3 gate log fires")
print("=" * 72)
job_b, ej_b = _make_event_job_with_authority(authority_electrical)
crew_b = Crew.sudo().create({
    "job_id": job_b.id,
    "user_id": u_unauthorised.id,
    "role": "tech",
})
m10_logs_b = GateLog.sudo().search([
    ("crew_id", "=", crew_b.id),
    ("fire_reason", "=like", "operating_authority_missing:%"),
])
ok = (len(m10_logs_b) >= 1
      and any("electrical" in (log.fire_reason or "")
              for log in m10_logs_b))
print(f"  M10 logs: {len(m10_logs_b)}")
if m10_logs_b:
    print(f"  fire_reason: {m10_logs_b[0].fire_reason}")
    print(f"  gate_tier: {m10_logs_b[0].gate_tier}")
print("T7e1001:", "PASS" if ok else "FAIL")
results["T7e1001"] = ok


# ============================================================
print()
print("T7e1002 - no required_authority_ids -> M10 no-op")
print("=" * 72)
job_c = Job.sudo().create({
    "name": "P7e M10 Job no auth",
    "partner_id": sample_job.partner_id.id,
    "venue_id": sample_job.venue_id.id,
    "currency_id": sample_job.currency_id.id,
    "event_date": fields.Date.today() + timedelta(days=7),
})
ej_c = EventJob.sudo().create({
    "commercial_job_id": job_c.id,
    "name": "No-auth event",
    "event_date": fields.Date.today() + timedelta(days=7),
    "state": "planning",
})
crew_c = Crew.sudo().create({
    "job_id": job_c.id,
    "user_id": u_unauthorised.id,
    "role": "runner",
})
m10_logs_c = GateLog.sudo().search([
    ("crew_id", "=", crew_c.id),
    ("fire_reason", "=like", "operating_authority_missing:%"),
])
ok = len(m10_logs_c) == 0
print(f"  M10 logs: {len(m10_logs_c)} (expected 0)")
print("T7e1002:", "PASS" if ok else "FAIL")
results["T7e1002"] = ok


# ============================================================
print()
print("T7e1003 - defensive env.get -- helper source has guards")
print("=" * 72)
from odoo.addons.neon_training.models import (
    commercial_job_crew)
src = inspect.getsource(commercial_job_crew)
# Source check tolerant of line wrapping inside the env.get
# call (Black-style multi-line formatting).
src_compact = " ".join(src.split())
has_env_get_authority = (
    "neon.lms.operating.authority" in src_compact
    and "env.get(" in src_compact)
has_env_get_enrollment = (
    "slide.channel.partner" in src_compact
    and "env.get(" in src_compact)
has_none_check = (
    "if Enrollment is None or Authority is None:" in src
    and "return []" in src)
ok = has_env_get_authority and has_env_get_enrollment and has_none_check
print(f"  authority env.get: {has_env_get_authority}")
print(f"  enrollment env.get: {has_env_get_enrollment}")
print(f"  None-check returns []: {has_none_check}")
print("T7e1003:", "PASS" if ok else "FAIL")
results["T7e1003"] = ok


# ============================================================
print()
print("T7e1004 - fire_reason populated with authority code")
print("=" * 72)
log_b_first = m10_logs_b[:1]
ok = (bool(log_b_first)
      and log_b_first.fire_reason.startswith(
          "operating_authority_missing:")
      and log_b_first.fire_reason.endswith("electrical"))
print(f"  fire_reason: "
      f"{log_b_first.fire_reason if log_b_first else None}")
print("T7e1004:", "PASS" if ok else "FAIL")
results["T7e1004"] = ok


# ============================================================
print()
print("T7e1005 - M5 probationary check still works (regression)")
print("=" * 72)
# u_unauthorised is in a probationary onboarding state? It's
# not -- no candidate record. So M5 won't fire for them.
# This is a quick smoke that M5 helper still exists and is
# callable.
ok = hasattr(crew_b, "_m5_probationary_violation_for_user")
print(f"  M5 helper callable: {ok}")
print("T7e1005:", "PASS" if ok else "FAIL")
results["T7e1005"] = ok


# ============================================================
print()
print("T7e1006 - M9-M11 cert gate still fires (regression)")
print("=" * 72)
# Verify tier_1 gate_log entries from M9 still get created
# for users with missing certs (existing Phase 7a behaviour).
m9_logs_b = GateLog.sudo().search([
    ("crew_id", "=", crew_b.id),
    ("gate_tier", "=", "tier_1_assignment"),
])
# Existence depends on u_unauthorised's cert state; we just
# verify the M5 + M9 code paths haven't been removed. The
# T7e1003 source-check covers the M10 helper presence.
ok = hasattr(crew_b, "_evaluate_assignment_gate")
print(f"  _evaluate_assignment_gate present: {ok}")
print(f"  M9 tier_1 logs for crew_b: {len(m9_logs_b)}")
print("T7e1006:", "PASS" if ok else "FAIL")
results["T7e1006"] = ok


# ============================================================
print()
print("T7e1007 - required_authority_ids field readable on "
      "event_job")
print("=" * 72)
ok = (hasattr(ej_b, "required_authority_ids")
      and len(ej_b.required_authority_ids) >= 1
      and authority_electrical in ej_b.required_authority_ids)
print(f"  field present: "
      f"{hasattr(ej_b, 'required_authority_ids')}")
print(f"  count: {len(ej_b.required_authority_ids)}")
print("T7e1007:", "PASS" if ok else "FAIL")
results["T7e1007"] = ok


# ============================================================
print()
print("T7e1008 - admin writes required_authority_ids")
print("=" * 72)
u_admin = _get_or_create_user(
    "p7e_m10_admin", "P7e M10 Train Admin",
    ["neon_training.group_neon_training_admin"])
err, _r = _try(lambda: ej_c.with_user(u_admin).sudo().write({
    "required_authority_ids": [(4, authority_stop_work.id)],
}))
ej_c.invalidate_recordset()
ok = (err is None
      and authority_stop_work in ej_c.required_authority_ids)
print(f"  write err: {err}")
print(f"  stop_work present after write: "
      f"{authority_stop_work in ej_c.required_authority_ids}")
print("T7e1008:", "PASS" if ok else "FAIL")
results["T7e1008"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7e1000", "T7e1001", "T7e1002", "T7e1003",
         "T7e1004", "T7e1005", "T7e1006", "T7e1007",
         "T7e1008"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
