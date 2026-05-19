"""P2.M4 smoke tests — Capacity Acceptance Gate.

Setup creates dedicated venues/rooms/users tagged P2M4 so the test is
re-runnable. Hard-resets any prior P2M4 fixtures + leftover jobs.
"""
import json

from odoo import fields
from odoo.exceptions import UserError

print("=" * 72)
print("SETUP")
print("=" * 72)

# Hard cleanup of prior P2M4 fixtures and jobs.
# Users must be deleted before their linked partners.
env["commercial.job"].sudo().search([("name", "like", "JOB-")]).unlink()
env["commercial.job.crew"].sudo().search([]).unlink()
env["res.users"].sudo().search([("login", "like", "p2m4_")]).unlink()
env["venue.room"].sudo().search([("name", "like", "P2M4")]).unlink()
env["res.partner"].sudo().search([("name", "like", "P2M4")]).unlink()
env.cr.commit()

# Two venues + rooms
venue_a = env["res.partner"].create({
    "name": "P2M4 Venue A", "is_company": True, "is_venue": True,
})
room_a1 = env["venue.room"].create({"name": "P2M4 A1", "venue_id": venue_a.id, "capacity": 200})
room_a2 = env["venue.room"].create({"name": "P2M4 A2", "venue_id": venue_a.id, "capacity": 100})
venue_b = env["res.partner"].create({
    "name": "P2M4 Venue B", "is_company": True, "is_venue": True,
})
room_b1 = env["venue.room"].create({"name": "P2M4 B1", "venue_id": venue_b.id, "capacity": 300})

# Client
client = env["res.partner"].create({
    "name": "P2M4 Client", "is_company": True, "is_venue": False,
})

# Users: regular + manager
regular = env["res.users"].create({
    "name": "P2M4 Regular User", "login": "p2m4_user",
    "email": "p2m4_user@test.local",
    "groups_id": [(6, 0, [env.ref("base.group_user").id])],
})
manager = env["res.users"].create({
    "name": "P2M4 Manager User", "login": "p2m4_mgr",
    "email": "p2m4_mgr@test.local",
    "groups_id": [(6, 0, [
        env.ref("base.group_user").id,
        env.ref("neon_jobs.group_neon_jobs_manager").id,
    ])],
})
# After install, the post_init_hook should have given group_user implied
# the neon_jobs_user group, so regular already has user-level access.
print("regular has neon_jobs_user?", regular.has_group("neon_jobs.group_neon_jobs_user"))
print("regular has neon_jobs_manager?", regular.has_group("neon_jobs.group_neon_jobs_manager"))
print("manager has neon_jobs_manager?", manager.has_group("neon_jobs.group_neon_jobs_manager"))
env.cr.commit()

base_date = fields.Date.add(fields.Date.today(), days=21)


def mk_job(suffix, **kw):
    vals = {
        "partner_id": client.id, "venue_id": venue_a.id,
        "venue_room_id": room_a1.id, "event_date": base_date,
        "currency_id": env.company.currency_id.id,
    }
    vals.update(kw)
    return env["commercial.job"].create(vals)


results = {}

# ============================================================
print()
print("=" * 72)
print("T1 - Pass case: pending job with no conflicts -> pass + active")
print("=" * 72)
job = mk_job("T1", venue_id=venue_b.id, venue_room_id=room_b1.id)
job.action_activate()
ok = (job.state == "active" and job.gate_result == "pass")
print("T1: state=", job.state, "gate_result=", job.gate_result,
      "run_at=", bool(job.gate_run_at))
print("T1:", "PASS" if ok else "FAIL")
results["T1"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T2 - Warning case: sub_hire_required=True -> warning + active")
print("=" * 72)
job = mk_job("T2", venue_id=venue_b.id, venue_room_id=room_b1.id,
             event_date=fields.Date.add(base_date, days=30),
             sub_hire_required=True)
job.action_activate()
ok = (job.state == "active" and job.gate_result == "warning")
print("T2: state=", job.state, "gate_result=", job.gate_result)
log = json.loads(job.gate_check_log)
print("    check messages (subset):")
for c in log["checks"]:
    if c["result"] != "pass":
        print("     -", c["name"], "->", c["result"], ":", c["message"][:80])
print("T2:", "PASS" if ok else "FAIL")
results["T2"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T3 - Reject for regular user: same venue+room+date")
print("=" * 72)
# First job: activate cleanly
first = mk_job("T3a", venue_id=venue_a.id, venue_room_id=room_a1.id,
               event_date=fields.Date.add(base_date, days=60))
first.action_activate()
print("T3 setup: first=", first.name, "state=", first.state)
# Second job: same venue + room + date
second = mk_job("T3b", venue_id=venue_a.id, venue_room_id=room_a1.id,
                event_date=fields.Date.add(base_date, days=60))
# Try as regular user
try:
    second.with_user(regular).action_activate()
    print("T3 FAIL: regular user activation should have raised UserError")
    results["T3"] = False
except UserError as e:
    msg = str(e)
    ok = "date_venue" in msg and "reject" in msg.lower()
    print("T3: UserError raised. Excerpt:", msg[:160].replace("\n", " | "))
    print("T3:", "PASS" if ok else "FAIL")
    results["T3"] = ok
env.cr.commit()
t3_second = second

# ============================================================
print()
print("=" * 72)
print("T4 - Reject + manager override path")
print("=" * 72)
# Manager call on the same conflicting job — should return wizard action
action = t3_second.with_user(manager).action_activate()
print("T4 manager call returned action:", isinstance(action, dict),
      "res_model=", action.get("res_model") if isinstance(action, dict) else None)
wizard_model = action.get("res_model") if isinstance(action, dict) else None
ok_action = wizard_model == "commercial.job.gate.override.wizard"
# Simulate the wizard confirmation
ctx = action.get("context", {})
wiz = env["commercial.job.gate.override.wizard"].with_user(manager).with_context(**ctx).create({
    "gate_override_reason": "T4 — urgent client, double-booking accepted by MD",
})
wiz.action_confirm()
t3_second.invalidate_recordset()
ok = (ok_action
      and t3_second.state == "active"
      and t3_second.gate_result == "overridden"
      and t3_second.gate_override_by == manager
      and "urgent client" in (t3_second.gate_override_reason or ""))
print("T4: state=", t3_second.state, "gate_result=", t3_second.gate_result,
      "override_by=", t3_second.gate_override_by.name,
      "reason=", t3_second.gate_override_reason)
print("T4:", "PASS" if ok else "FAIL")
results["T4"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T5 - Re-run on update: change active job's venue to clash")
print("=" * 72)
# T1's job is at venue_b/room_b1; first/second at venue_a/room_a1 on a
# different date. Create a fresh active job at venue_a/room_a2 on a
# unique date, then change its venue+room to clash with first.
target = mk_job("T5", venue_id=venue_a.id, venue_room_id=room_a2.id,
                event_date=fields.Date.add(base_date, days=60))
target.action_activate()
print("T5 setup: target active, gate=", target.gate_result)
prior_chatter = env["mail.message"].search_count([
    ("model", "=", "commercial.job"), ("res_id", "=", target.id),
])
# Move venue_room_id to room_a1 — same date as `first` -> conflict reject
target.write({"venue_room_id": room_a1.id})
target.invalidate_recordset()
new_chatter = env["mail.message"].search_count([
    ("model", "=", "commercial.job"), ("res_id", "=", target.id),
])
# State should stay active (no auto-deactivate per D1)
ok = (target.state == "active"
      and target.gate_result in ("warning", "reject")
      and new_chatter > prior_chatter)
print("T5: state=", target.state, "gate_result=", target.gate_result,
      "chatter delta=", new_chatter - prior_chatter)
print("T5:", "PASS" if ok else "FAIL")
results["T5"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T6 - Crew double-book warning")
print("=" * 72)
crew_user = env["res.users"].search([("login", "=", "p2m4_user")], limit=1)
job_x = mk_job("T6x", venue_id=venue_b.id, venue_room_id=room_b1.id,
               event_date=fields.Date.add(base_date, days=90))
env["commercial.job.crew"].create({
    "job_id": job_x.id, "user_id": crew_user.id,
    "role": "tech", "state": "confirmed",
})
job_x.action_activate()
print("T6 setup: job_x active gate=", job_x.gate_result)
job_y = mk_job("T6y", venue_id=venue_a.id, venue_room_id=room_a1.id,
               event_date=fields.Date.add(base_date, days=90))
env["commercial.job.crew"].create({
    "job_id": job_y.id, "user_id": crew_user.id,
    "role": "tech", "state": "confirmed",
})
job_y.action_activate()
ok = (job_y.state == "active" and job_y.gate_result == "warning")
log = json.loads(job_y.gate_check_log)
crew_check = next((c for c in log["checks"] if c["name"] == "crew"), None)
print("T6: job_y gate=", job_y.gate_result,
      " crew check =", crew_check["result"] if crew_check else None)
print("T6:", "PASS" if ok else "FAIL")
results["T6"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T7 - Cash-flow warning: 4 jobs same fortnight, deposit_pending")
print("=" * 72)
cf_date = fields.Date.add(base_date, days=120)
cf_jobs = []
for i in range(4):
    j = mk_job("T7." + str(i),
               venue_id=venue_b.id, venue_room_id=False,
               event_date=cf_date)
    j.write({"finance_status": "deposit_pending"})
    cf_jobs.append(j)
# Activate first 3 — should pass (each sees only <3 others in window)
for j in cf_jobs[:3]:
    j.action_activate()
# Activate 4th — should warn on cashflow (3 others in window)
cf_jobs[3].action_activate()
log = json.loads(cf_jobs[3].gate_check_log)
cf_check = next((c for c in log["checks"] if c["name"] == "cashflow"), None)
ok = (cf_jobs[3].gate_result == "warning"
      and cf_check and cf_check["result"] == "warning")
# But other checks may also be warnings (same venue, same date). Let's
# verify cashflow specifically is a warning.
print("T7: 4th gate_result=", cf_jobs[3].gate_result,
      " cashflow check=", cf_check["result"] if cf_check else None,
      " msg=", (cf_check["message"][:80] if cf_check else ""))
print("T7:", "PASS" if ok else "FAIL")
results["T7"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T8 - Aggregate: warning + reject -> reject")
print("=" * 72)
# Build a job with sub_hire_required (warning) AND same room conflict (reject)
seed = mk_job("T8seed", venue_id=venue_b.id, venue_room_id=room_b1.id,
              event_date=fields.Date.add(base_date, days=150))
seed.action_activate()
conflict = mk_job("T8conflict", venue_id=venue_b.id, venue_room_id=room_b1.id,
                  event_date=fields.Date.add(base_date, days=150),
                  sub_hire_required=True)
result = conflict._evaluate_capacity_gate()
log_checks = {c["name"]: c["result"] for c in result["checks"]}
ok = (result["aggregate"] == "reject"
      and log_checks.get("date_venue") == "reject"
      and log_checks.get("sub_hire") == "warning")
print("T8: aggregate=", result["aggregate"],
      " date_venue=", log_checks.get("date_venue"),
      " sub_hire=", log_checks.get("sub_hire"))
print("T8:", "PASS" if ok else "FAIL")
results["T8"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T9 - Re-run button updates gate_run_at")
print("=" * 72)
old_run_at = first.gate_run_at
import time
time.sleep(1)  # ensure timestamp difference
first.action_rerun_capacity_gate()
first.invalidate_recordset()
ok = first.gate_run_at and first.gate_run_at > old_run_at
print("T9: old=", old_run_at, " new=", first.gate_run_at)
print("T9:", "PASS" if ok else "FAIL")
results["T9"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T10 - Idempotency: no spurious chatter on second identical re-run")
print("=" * 72)
# Use job_x (active, has gate result). Force two re-runs back-to-back.
job_x.action_rerun_capacity_gate()
chat_before = env["mail.message"].search_count([
    ("model", "=", "commercial.job"), ("res_id", "=", job_x.id),
])
job_x.action_rerun_capacity_gate()
chat_after = env["mail.message"].search_count([
    ("model", "=", "commercial.job"), ("res_id", "=", job_x.id),
])
ok = chat_after == chat_before
print("T10: chatter before=", chat_before, " after=", chat_after)
print("T10:", "PASS" if ok else "FAIL")
results["T10"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
