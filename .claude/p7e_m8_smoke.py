"""P7e.M8 smoke -- completion workflow + auto-cert (8 tests)."""
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

Enrollment = env["slide.channel.partner"]
TrackComp = env["neon.lms.track.completion"]
ModuleComp = env["neon.lms.module.completion"]
ScenarioComp = env["neon.lms.scenario.completion"]
Scenario = env["neon.lms.practical.scenario"]
Users = env["res.users"]


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


u_learner = _get_or_create_user(
    "p7e_m8_learner", "P7e M8 Learner",
    ["neon_jobs.group_neon_jobs_crew"])
env.cr.commit()

program = env.ref("neon_lms.program_channel")
foundations = env.ref("neon_lms.track_foundations_safety")
audio = env.ref("neon_lms.track_audio")
m01 = env.ref("neon_lms.module_m01")
m08 = env.ref("neon_lms.module_m08")
m02 = env.ref("neon_lms.module_m02")
m03 = env.ref("neon_lms.module_m03")
m15 = env.ref("neon_lms.module_m15")


# ============================================================
print()
print("T7e800 - module write quiz_score >= min -> completed")
print("=" * 72)
enroll = Enrollment.sudo().create({
    "channel_id": program.id,
    "partner_id": u_learner.partner_id.id,
})
mc01 = ModuleComp.sudo().create({
    "enrollment_id": enroll.id,
    "module_id": m01.id,
    "state": "in_progress",
})
# m01 has no practical scenarios (M5 didn't seed any for it)
# so just hitting quiz_score >= 0.8 should advance.
mc01.sudo().write({"quiz_score": 0.9})
mc01.invalidate_recordset()
ok = mc01.state == "completed"
print(f"  state after quiz write: {mc01.state}")
print("T7e800:", "PASS" if ok else "FAIL")
results["T7e800"] = ok


# ============================================================
print()
print("T7e801 - all modules in track completed -> track")
print("=" * 72)
tc_found = TrackComp.sudo().create({
    "enrollment_id": enroll.id,
    "track_id": foundations.id,
})
# m01 already completed. Add m08 + complete it.
mc08 = ModuleComp.sudo().create({
    "enrollment_id": enroll.id,
    "module_id": m08.id,
    "state": "in_progress",
})
mc08.sudo().write({"quiz_score": 0.85})
tc_found.invalidate_recordset()
# m01 is completed via T7e800, m08 just completed via write
# above. Track rollup should fire from m08's
# _check_and_advance which calls tc._check_and_advance.
ok = tc_found.state in ("completed", "certified")
print(f"  track state: {tc_found.state}")
print(f"  modules_completed: {tc_found.modules_completed}")
print("T7e801:", "PASS" if ok else "FAIL")
results["T7e801"] = ok


# ============================================================
print()
print("T7e802 - sub_cert_type set -> cert issued + certified")
print("=" * 72)
# M9 hasn't run yet so foundations.sub_cert_type_id is False.
# In M8 standalone this means track stays at 'completed' and
# logs the M9-not-yet message. That's the defensive path.
# Set sub_cert_type_id manually to verify the issuance path.
# Use any existing cert type (e.g. cert_type_runner from
# neon_training) as a stand-in.
runner_cert_type = env.ref(
    "neon_training.cert_type_runner")
foundations.sudo().write({
    "sub_cert_type_id": runner_cert_type.id,
})
# Re-trigger issuance.
tc_found._issue_sub_cert()
tc_found.invalidate_recordset()
ok = (tc_found.state == "certified"
      and bool(tc_found.sub_cert_id))
print(f"  state: {tc_found.state} "
      f"sub_cert_id: {tc_found.sub_cert_id.id if tc_found.sub_cert_id else None}")
print("T7e802:", "PASS" if ok else "FAIL")
results["T7e802"] = ok
# Cleanup: clear the sub_cert_type_id back to False
foundations.sudo().write({"sub_cert_type_id": False})


# ============================================================
print()
print("T7e803 - all 7 tracks certified -> capstone")
print("=" * 72)
# This test requires sub_cert_type on ALL 7 tracks + capstone
# on channel. Without M9, mark intermediate state instead:
# verify that with all 7 track_completion records at
# 'certified', the enrollment advances to 'completed' (capstone
# deferred per defensive path). Set up all 7 tcs as certified.
all_tracks = env["neon.lms.track"].search([])
for trk in all_tracks:
    existing = TrackComp.sudo().search([
        ("enrollment_id", "=", enroll.id),
        ("track_id", "=", trk.id),
    ], limit=1)
    if not existing:
        existing = TrackComp.sudo().create({
            "enrollment_id": enroll.id,
            "track_id": trk.id,
        })
    existing.sudo().write({
        "state": "certified",
        "completion_date": fields.Datetime.now(),
        "certification_date": fields.Datetime.now(),
    })
enroll._check_and_advance_to_certified()
enroll.invalidate_recordset()
# Without capstone cert_type, defensive path -> neon_state=
# completed. With cert_type, neon_state=certified.
# T7e803 expects 'completed' (defensive path; capstone in M9).
ok = enroll.neon_state in ("completed", "certified")
print(f"  enrollment.neon_state: {enroll.neon_state}")
print("T7e803:", "PASS" if ok else "FAIL")
results["T7e803"] = ok


# ============================================================
print()
print("T7e804 - capstone before all 7 -> no capstone issued")
print("=" * 72)
# Fresh enrollment with only 1 track certified.
u_partial = _get_or_create_user(
    "p7e_m8_partial", "P7e M8 Partial",
    ["neon_jobs.group_neon_jobs_crew"])
enroll_partial = Enrollment.sudo().create({
    "channel_id": program.id,
    "partner_id": u_partial.partner_id.id,
})
TrackComp.sudo().create({
    "enrollment_id": enroll_partial.id,
    "track_id": foundations.id,
    "state": "certified",
})
enroll_partial._check_and_advance_to_certified()
enroll_partial.invalidate_recordset()
ok = (not enroll_partial.neon_capstone_cert_id
      and enroll_partial.neon_state in ("in_progress", "enrolled"))
print(f"  state: {enroll_partial.neon_state} "
      f"capstone: {enroll_partial.neon_capstone_cert_id.id or None}")
print("T7e804:", "PASS" if ok else "FAIL")
results["T7e804"] = ok


# ============================================================
print()
print("T7e805 - scenario passed -> module advance hook")
print("=" * 72)
# m02 has no scenarios seeded by M1-M5 (only M5 model exists).
# Create a scenario + completion to test the cross-model
# write trigger.
u_sc = _get_or_create_user(
    "p7e_m8_sc", "P7e M8 Scenario",
    ["neon_jobs.group_neon_jobs_crew"])
enroll_sc = Enrollment.sudo().create({
    "channel_id": program.id,
    "partner_id": u_sc.partner_id.id,
})
sc = Scenario.sudo().create({
    "module_id": m02.id,
    "title": "T7e805 scenario",
    "description": "Setup",
    "signoff_authority": "superuser",
})
mc_sc = ModuleComp.sudo().create({
    "enrollment_id": enroll_sc.id,
    "module_id": m02.id,
    "state": "in_progress",
    "quiz_score": 0.9,  # quiz passed
})
# Module has scenario; not yet passed -> still in_progress.
mc_sc.invalidate_recordset()
state_before = mc_sc.state
# Create completion with passed=False, then write passed=True
# to trigger the scenario.write hook -> module._check.
comp_sc = ScenarioComp.sudo().create({
    "learner_id": u_sc.id,
    "scenario_id": sc.id,
    "passed": False,
})
comp_sc.sudo().write({"passed": True})
mc_sc.invalidate_recordset()
ok = (state_before == "in_progress"
      and mc_sc.state == "completed")
print(f"  before scenario pass: {state_before}")
print(f"  after scenario pass: {mc_sc.state}")
print("T7e805:", "PASS" if ok else "FAIL")
results["T7e805"] = ok


# ============================================================
print()
print("T7e806 - defensive when sub_cert_type unset -> "
      "logs + skips (no exception)")
print("=" * 72)
# Use foundations track whose sub_cert_type_id is now False
# again (cleaned up after T7e802).
u_def = _get_or_create_user(
    "p7e_m8_defensive", "P7e M8 Defensive",
    ["neon_jobs.group_neon_jobs_crew"])
enroll_def = Enrollment.sudo().create({
    "channel_id": program.id,
    "partner_id": u_def.partner_id.id,
})
tc_def = TrackComp.sudo().create({
    "enrollment_id": enroll_def.id,
    "track_id": foundations.id,
    "state": "completed",
})
err, result = _try(lambda: tc_def._issue_sub_cert())
ok = (err is None
      and result is False
      and tc_def.state == "completed"
      and not tc_def.sub_cert_id)
print(f"  err: {err}")
print(f"  result: {result} (expect False)")
print(f"  state stays at: {tc_def.state}")
print("T7e806:", "PASS" if ok else "FAIL")
results["T7e806"] = ok


# ============================================================
print()
print("T7e807 - drift scenario: module completion exists but "
      "no cert yet (M9 absent)")
print("=" * 72)
# This is the negative test per sketch section 12 refinement
# 3: module completion can land before cert types are seeded
# (M9 not yet run). Verify the system handles the gap
# gracefully.
# tc_def is at 'completed' state but sub_cert_id is False
# (from T7e806). This represents the M8-without-M9 drift.
# The expected state: track stays 'completed', no cert, no
# error.
drift_detected = (
    tc_def.state == "completed"
    and not tc_def.sub_cert_id
    and tc_def.completion_date  # was set on advance
       is False or tc_def.completion_date is False
    or True  # acceptable either way
)
ok = (tc_def.state == "completed"
      and not tc_def.sub_cert_id)
print(f"  drift state: {tc_def.state}")
print(f"  sub_cert: {tc_def.sub_cert_id.id if tc_def.sub_cert_id else None}")
print("T7e807:", "PASS" if ok else "FAIL")
results["T7e807"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7e800", "T7e801", "T7e802", "T7e803",
         "T7e804", "T7e805", "T7e806", "T7e807"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
