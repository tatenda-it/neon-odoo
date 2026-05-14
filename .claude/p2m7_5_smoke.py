"""P2.M7.5 smoke — role model hardening + Lead Tech + crew calendar."""
from odoo import fields, SUPERUSER_ID
from odoo.exceptions import AccessError

print("=" * 72)
print("SETUP")
print("=" * 72)
env.user.write({
    "groups_id": [(4, env.ref("neon_jobs.group_neon_jobs_manager").id)],
})

# Cleanup
env["commercial.job"].sudo().search([("name", "like", "JOB-")]).unlink()
env["commercial.job.crew"].sudo().search([]).unlink()
env["res.users"].sudo().search([("login", "like", "p2m75_")]).unlink()
env["res.partner"].sudo().search([("name", "like", "P2M75")]).unlink()
env.cr.commit()

# Fixtures
venue = env["res.partner"].create({
    "name": "P2M75 Venue", "is_company": True, "is_venue": True,
})
client = env["res.partner"].create({
    "name": "P2M75 Client", "is_company": True,
})

# Users:
# - sales: internal user, neon_jobs_user only (via base.group_user → implies)
# - manager: internal + manager
# - crew_leader: portal-tier with crew_leader only (clean isolation)
# - crew_only: portal-tier with crew only
# - other_crew: portal-tier with crew only (for the "other person's record" test)
sales = env["res.users"].create({
    "name": "P2M75 Sales", "login": "p2m75_sales",
    "email": "p2m75_sales@test.local",
    "password": "test123",
    # P2.M7.6 removed the base.group_user → neon_jobs_user implication.
    # Explicit grant required for sales reps now.
    "groups_id": [(6, 0, [
        env.ref("base.group_user").id,
        env.ref("neon_jobs.group_neon_jobs_user").id,
    ])],
})
manager = env["res.users"].create({
    "name": "P2M75 Manager", "login": "p2m75_mgr",
    "email": "p2m75_mgr@test.local",
    "password": "test123",
    "groups_id": [(6, 0, [
        env.ref("base.group_user").id,
        env.ref("neon_jobs.group_neon_jobs_manager").id,
    ])],
})
# crew_leader: realistic Lead Tech = internal user with crew_leader group.
# base.group_user implies neon_jobs_user, so this user also has user-tier
# read access on the operational models. The crew_leader grant adds the
# operational CRUD on commercial.job.crew and write on commercial.job.
crew_leader = env["res.users"].create({
    "name": "P2M75 Crew Leader", "login": "p2m75_lead",
    "email": "p2m75_lead@test.local",
    "password": "test123",
    "groups_id": [(6, 0, [
        env.ref("base.group_user").id,
        env.ref("neon_jobs.group_neon_jobs_crew_leader").id,
    ])],
})
crew_only = env["res.users"].create({
    "name": "P2M75 Crew", "login": "p2m75_crew",
    "email": "p2m75_crew@test.local",
    "password": "test123",
    "groups_id": [(6, 0, [
        env.ref("base.group_user").id,
        env.ref("neon_jobs.group_neon_jobs_crew").id,
    ])],
})
other_crew = env["res.users"].create({
    "name": "P2M75 Other Crew", "login": "p2m75_other",
    "email": "p2m75_other@test.local",
    "password": "test123",
    "groups_id": [(6, 0, [
        env.ref("base.group_user").id,
        env.ref("neon_jobs.group_neon_jobs_crew").id,
    ])],
})

print("sales: user=", sales.has_group("neon_jobs.group_neon_jobs_user"),
      " manager=", sales.has_group("neon_jobs.group_neon_jobs_manager"),
      " crew_leader=", sales.has_group("neon_jobs.group_neon_jobs_crew_leader"))
print("manager: user=", manager.has_group("neon_jobs.group_neon_jobs_user"),
      " manager=", manager.has_group("neon_jobs.group_neon_jobs_manager"),
      " crew_leader=", manager.has_group("neon_jobs.group_neon_jobs_crew_leader"))
print("crew_leader: user=", crew_leader.has_group("neon_jobs.group_neon_jobs_user"),
      " manager=", crew_leader.has_group("neon_jobs.group_neon_jobs_manager"),
      " crew_leader=", crew_leader.has_group("neon_jobs.group_neon_jobs_crew_leader"),
      " (internal user — has user-tier via base.group_user implication)")
print("crew_only: crew=", crew_only.has_group("neon_jobs.group_neon_jobs_crew"),
      " user=", crew_only.has_group("neon_jobs.group_neon_jobs_user"))

# Two jobs + crew assignments
today = fields.Date.today()
job1 = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.add(today, days=30),
    "currency_id": env.company.currency_id.id,
})
A1 = env["commercial.job.crew"].create({
    "job_id": job1.id, "user_id": crew_only.id,
    "role": "tech", "state": "pending",
})
A2 = env["commercial.job.crew"].create({
    "job_id": job1.id, "user_id": other_crew.id,
    "role": "tech", "state": "pending",
})
env.cr.commit()

results = {}

# ============================================================
print()
print("=" * 72)
print("T18 - Sales rep CANNOT create commercial.job.crew")
print("=" * 72)
try:
    env["commercial.job.crew"].with_user(sales).create({
        "job_id": job1.id, "user_id": crew_only.id,
        "role": "tech", "state": "pending",
    })
    print("T18 FAIL: sales created crew assignment (should have been blocked)")
    results["T18"] = False
except AccessError as e:
    print("T18: AccessError raised as expected:", str(e)[:120])
    results["T18"] = True

# ============================================================
print()
print("=" * 72)
print("T19 - Sales rep CAN read commercial.job.crew")
print("=" * 72)
try:
    records = env["commercial.job.crew"].with_user(sales).search([])
    ok = len(records) >= 2
    print("T19: search returned", len(records), "records (>= 2 expected)")
    print("T19:", "PASS" if ok else "FAIL")
    results["T19"] = ok
except AccessError as e:
    print("T19 FAIL: read blocked:", str(e)[:120])
    results["T19"] = False

# ============================================================
print()
print("=" * 72)
print("T20 - Crew leader CAN create commercial.job.crew")
print("=" * 72)
# Use a fresh user to avoid the unique (job_id, user_id) constraint.
t20_user = env["res.users"].create({
    "name": "P2M75 T20 Target", "login": "p2m75_t20",
    "email": "p2m75_t20@test.local",
    "password": "test123",
    "groups_id": [(6, 0, [
        env.ref("base.group_user").id,
        env.ref("neon_jobs.group_neon_jobs_crew").id,
    ])],
})
env.cr.commit()
try:
    new_assign = env["commercial.job.crew"].with_user(crew_leader).create({
        "job_id": job1.id, "user_id": t20_user.id,
        "role": "lead_tech", "state": "pending",
    })
    print("T20: created assignment id=", new_assign.id, "as crew leader")
    new_assign.unlink()
    results["T20"] = True
    print("T20: PASS")
    env.cr.commit()
except Exception as e:
    print("T20 FAIL: crew leader create raised", type(e).__name__, ":", str(e)[:120])
    results["T20"] = False
    env.cr.rollback()

# ============================================================
print()
print("=" * 72)
print("T21 - Crew leader can read+write commercial.job")
print("=" * 72)
try:
    j = env["commercial.job"].with_user(crew_leader).browse(job1.id)
    _ = j.name  # read
    j.write({"sub_hire_required": True})  # write
    j.invalidate_recordset()
    ok = j.sub_hire_required is True
    print("T21: read OK, write OK, sub_hire_required=", j.sub_hire_required)
    print("T21:", "PASS" if ok else "FAIL")
    results["T21"] = ok
    # revert
    job1.write({"sub_hire_required": False})
except Exception as e:
    print("T21 FAIL:", type(e).__name__, ":", str(e)[:120])
    results["T21"] = False

env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T22 - Crew tier can write OWN assignment but not OTHER user's")
print("=" * 72)
# A1 is for crew_only (the test user); A2 is for other_crew.
# Crew tier has CSV (1,1,0,0) + record rule [('user_id','=',user.id)].
own_ok = False
other_blocked = False
try:
    env["commercial.job.crew"].with_user(crew_only).browse(A1.id).write({
        "decline_reason": "T22 own — should succeed",
    })
    own_ok = True
    print("T22a: wrote own assignment A1 — OK")
except Exception as e:
    print("T22a FAIL: own write blocked:", type(e).__name__, ":", str(e)[:120])

try:
    env["commercial.job.crew"].with_user(crew_only).browse(A2.id).write({
        "decline_reason": "T22 other — should be blocked",
    })
    print("T22b FAIL: other-user write was NOT blocked")
except AccessError as e:
    other_blocked = True
    print("T22b: AccessError on other-user write —", str(e)[:120])
except Exception as e:
    # Could also be "record does not exist" via record rule masking
    other_blocked = True
    print("T22b: blocked via", type(e).__name__, "—", str(e)[:120])

ok = own_ok and other_blocked
print("T22:", "PASS" if ok else "FAIL")
results["T22"] = ok
env.cr.rollback()

# ============================================================
print()
print("=" * 72)
print("T23 - My Calendar menu groups = crew only")
print("=" * 72)
m = env.ref("neon_jobs.menu_my_calendar", raise_if_not_found=False)
ok = bool(m and len(m.groups_id) == 1
          and m.groups_id[0] == env.ref("neon_jobs.group_neon_jobs_crew"))
print("T23: menu groups =", [g.name for g in m.groups_id] if m else None)
print("T23:", "PASS" if ok else "FAIL")
results["T23"] = ok

# ============================================================
print()
print("=" * 72)
print("T24 - Dashboard hide_cash_flow: crew_leader-only True, with manager False")
print("=" * 72)
# crew_leader-only user → hide_cash_flow = True
db_lead = env["commercial.job.dashboard"].with_user(crew_leader).create({})
hide_for_lead = db_lead.hide_cash_flow
# manager (also has neon_jobs_manager) → hide_cash_flow = False
db_mgr = env["commercial.job.dashboard"].with_user(manager).create({})
hide_for_mgr = db_mgr.hide_cash_flow
ok = (hide_for_lead is True and hide_for_mgr is False)
print("T24: crew_leader hide=", hide_for_lead, " manager hide=", hide_for_mgr)
print("T24:", "PASS" if ok else "FAIL")
results["T24"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T25 - can_edit_crew compute for each tier")
print("=" * 72)
def check_can_edit(user, expected):
    j = env["commercial.job"].with_user(user).browse(job1.id)
    return j.can_edit_crew == expected

results_25 = {
    "sales (user only)": check_can_edit(sales, False),
    "manager": check_can_edit(manager, True),
    "internal user + crew_leader": check_can_edit(crew_leader, True),
}
# Also verify hide_cash_flow on the dashboard for crew_leader (T24 confirmed
# True). Here we just sanity-check that adding crew_leader to a sales rep
# flips can_edit_crew.
sales.write({
    "groups_id": [(4, env.ref("neon_jobs.group_neon_jobs_crew_leader").id)],
})
results_25["sales after crew_leader added"] = check_can_edit(sales, True)

ok = all(results_25.values())
for label, v in results_25.items():
    print("   ", label, ":", "OK" if v else "FAIL")
print("T25:", "PASS" if ok else "FAIL")
results["T25"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T26 - My Calendar full domain returns only own confirmed events")
print("=" * 72)
# Reproduce the exact domain wired into commercial_job_calendar_my_calendar_action.
# Setup: jobJ active with crew_only confirmed; jobK active with other_crew
# confirmed; jobL pending without deposit (should be excluded).
jobJ = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.add(today, days=40),
    "currency_id": env.company.currency_id.id,
})
jobJ.write({"state": "active", "soft_hold_until": False})
env["commercial.job.crew"].sudo().create({
    "job_id": jobJ.id, "user_id": crew_only.id,
    "role": "tech", "state": "confirmed",
})

jobK = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.add(today, days=50),
    "currency_id": env.company.currency_id.id,
})
jobK.write({"state": "active", "soft_hold_until": False})
env["commercial.job.crew"].sudo().create({
    "job_id": jobK.id, "user_id": other_crew.id,
    "role": "tech", "state": "confirmed",
})

# jobL: crew_only is confirmed, but state is pending and no deposit — domain
# should exclude this.
jobL = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.add(today, days=60),
    "currency_id": env.company.currency_id.id,
})
env["commercial.job.crew"].sudo().create({
    "job_id": jobL.id, "user_id": crew_only.id,
    "role": "tech", "state": "confirmed",
})
env.cr.commit()

my_cal_domain = [
    ("is_my_crew_event", "=", True),
    "|",
    ("state", "=", "active"),
    "&", ("state", "=", "pending"), ("deposit_received", ">", 0),
]
search_result = env["commercial.job"].with_user(crew_only).search(my_cal_domain)
j_in = jobJ in search_result
k_in = jobK in search_result
l_in = jobL in search_result
ok = j_in and not k_in and not l_in
print("T26: search returned ids =", search_result.ids)
print("    jobJ (own, active) in result:", j_in, " (want True)")
print("    jobK (other crew, active) in result:", k_in, " (want False)")
print("    jobL (own, pending no deposit) in result:", l_in, " (want False)")
print("T26:", "PASS" if ok else "FAIL")
results["T26"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T18", "T19", "T20", "T21", "T22", "T23", "T24", "T25", "T26"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
