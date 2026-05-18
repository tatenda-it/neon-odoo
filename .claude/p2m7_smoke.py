"""P2.M7 smoke — Operations Dashboard + My Schedule + crew confirm/decline."""
from odoo import fields, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError

print("=" * 72)
print("SETUP")
print("=" * 72)
env.user.write({
    "groups_id": [(4, env.ref("neon_jobs.group_neon_jobs_manager").id)],
})

# Hard cleanup. The three LIKE-pattern lines below explicitly
# exclude the p2m75_* / P2M75 fixtures. SQL LIKE treats `_` as a
# single-char wildcard, and the substring `p2m7` / `P2M7` is
# contained in `p2m75` / `P2M75`, so an unguarded `like "p2m7_"`
# would sweep the persistent p2m7_5_smoke fixtures along with this
# smoke's own. (P2.M7.5.1 fixture refactor 2026-05-18 — see the
# polish backlog for the broader SQL-_-wildcard sweep.)
env["commercial.job"].sudo().search([("name", "like", "JOB-")]).unlink()
env["commercial.job.crew"].sudo().search([]).unlink()
env["res.users"].sudo().search([
    ("login", "like", "p2m7_"),
    ("login", "not like", "p2m75_"),
]).unlink()
env["venue.room"].sudo().search([
    ("name", "like", "P2M7"),
    ("name", "not like", "P2M75"),
]).unlink()
env["res.partner"].sudo().search([
    ("name", "like", "P2M7"),
    ("name", "not like", "P2M75"),
]).unlink()
env.cr.commit()

venue = env["res.partner"].create({
    "name": "P2M7 Venue", "is_company": True, "is_venue": True,
})
room = env["venue.room"].create({
    "name": "P2M7 Room", "venue_id": venue.id, "capacity": 100,
})
client = env["res.partner"].create({
    "name": "P2M7 Client", "is_company": True,
})

# Users for crew + role scoping
# crew_user: a regular internal user that ALSO has the crew group. Used
# in T6/T7 where the schedule needs to read commercial.job records.
crew_user = env["res.users"].create({
    "name": "P2M7 Crew", "login": "p2m7_crew",
    "email": "p2m7_crew@test.local",
    "groups_id": [(6, 0, [
        env.ref("base.group_user").id,
        env.ref("neon_jobs.group_neon_jobs_crew").id,
    ])],
})
# crew_only: a portal-tier user with ONLY group_neon_jobs_crew. Used in
# T8 to verify the access CSV blocks Operations Dashboard for non-
# user/non-manager principals. base.group_portal does NOT imply
# group_neon_jobs_user, so this user is genuinely crew-only.
crew_only = env["res.users"].create({
    "name": "P2M7 Crew Only", "login": "p2m7_crew_only",
    "email": "p2m7_crew_only@test.local",
    "groups_id": [(6, 0, [
        env.ref("base.group_user").id,
        env.ref("neon_jobs.group_neon_jobs_crew").id,
    ])],
})
print("crew_user has user?", crew_user.has_group("neon_jobs.group_neon_jobs_user"),
      "manager?", crew_user.has_group("neon_jobs.group_neon_jobs_manager"),
      "crew?", crew_user.has_group("neon_jobs.group_neon_jobs_crew"))
print("crew_only has user?", crew_only.has_group("neon_jobs.group_neon_jobs_user"),
      "manager?", crew_only.has_group("neon_jobs.group_neon_jobs_manager"),
      "crew?", crew_only.has_group("neon_jobs.group_neon_jobs_crew"))
env.cr.commit()

today = fields.Date.today()
base_date = fields.Date.add(today, days=30)


def mk_job(**kw):
    vals = {
        "partner_id": client.id, "venue_id": venue.id,
        "venue_room_id": room.id, "event_date": base_date,
        "currency_id": env.company.currency_id.id,
    }
    vals.update(kw)
    return env["commercial.job"].create(vals)


results = {}

# ============================================================
print()
print("=" * 72)
print("T1 - Operations Dashboard creates cleanly")
print("=" * 72)
db = env["commercial.job.dashboard"].create({})
ok = bool(db.id)
print("T1: created id=", db.id)
print("T1:", "PASS" if ok else "FAIL")
results["T1"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T2 - All 5 counts compute to 0 on empty DB")
print("=" * 72)
db = env["commercial.job.dashboard"].create({})
counts = [db.gate_issues_count, db.soft_hold_count, db.crew_gap_count,
          db.needs_attention_count, db.cash_flow_count]
ok = all(c == 0 for c in counts)
print("T2: counts =", counts)
print("T2:", "PASS" if ok else "FAIL")
results["T2"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T3 - All 5 counters populate from targeted fixtures")
print("=" * 72)

# 2 active jobs with gate=reject (different venues to avoid soft-hold gate trip)
v2 = env["res.partner"].create({"name": "P2M7 Venue 2", "is_company": True, "is_venue": True})
r2 = env["venue.room"].create({"name": "P2M7 Room 2", "venue_id": v2.id, "capacity": 80})

gj1 = mk_job(venue_id=v2.id, venue_room_id=r2.id, event_date=fields.Date.add(today, days=50))
gj1.write({"state": "active", "soft_hold_until": False, "gate_result": "reject"})
gj2 = mk_job(venue_id=v2.id, venue_room_id=r2.id, event_date=fields.Date.add(today, days=52))
gj2.write({"state": "active", "soft_hold_until": False, "gate_result": "reject"})

# 1 pending with soft_hold_state=expired
sh = mk_job(event_date=fields.Date.add(today, days=80))
sh.write({"soft_hold_until": fields.Date.subtract(today, days=2)})
sh.invalidate_recordset(["soft_hold_state"])
sh._compute_soft_hold_state()

# 1 active with crew_total=2, crew_confirmed=0
v3 = env["res.partner"].create({"name": "P2M7 Venue 3", "is_company": True, "is_venue": True})
r3 = env["venue.room"].create({"name": "P2M7 Room 3", "venue_id": v3.id, "capacity": 50})
crew_job = mk_job(venue_id=v3.id, venue_room_id=r3.id, event_date=fields.Date.add(today, days=90))
env["commercial.job.crew"].create({"job_id": crew_job.id, "user_id": crew_user.id,
                                     "role": "tech", "state": "pending"})
env["commercial.job.crew"].create({"job_id": crew_job.id, "user_id": env.uid,
                                     "role": "tech", "state": "pending"})
crew_job.write({"state": "active", "soft_hold_until": False})

# 1 pending with needs_attention=True (auto-set on auto-create from CRM lead with no date_deadline)
na = mk_job(event_date=fields.Date.add(today, days=100))
na.write({"event_date_is_placeholder": True})
na.invalidate_recordset(["needs_attention"])
na._compute_needs_attention()

# 1 pending with finance_status=quoted, event_date within 14 days
cf = mk_job(event_date=fields.Date.add(today, days=7))
cf.write({"finance_status": "quoted"})

env.cr.commit()
db = env["commercial.job.dashboard"].create({})
counts = {
    "gate_issues_count": db.gate_issues_count,
    "soft_hold_count": db.soft_hold_count,
    "crew_gap_count": db.crew_gap_count,
    "needs_attention_count": db.needs_attention_count,
    "cash_flow_count": db.cash_flow_count,
}
# Expected minimums (other prior fixtures may inflate)
expected = {"gate_issues_count": 2, "soft_hold_count": 1, "crew_gap_count": 1,
            "needs_attention_count": 1, "cash_flow_count": 1}
ok = all(counts[k] >= v for k, v in expected.items())
print("T3: counts =", counts)
print("    expected min =", expected)
print("T3:", "PASS" if ok else "FAIL")
results["T3"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T4 - top3 fields contain the right records")
print("=" * 72)
db = env["commercial.job.dashboard"].create({})
# Read m2m fields directly (no count read first) — verifies the
# split-compute fix from this session: form views may fetch fields in
# any order and the top3 must populate regardless.
ok_gate = gj1 in db.gate_issues_top3 or gj2 in db.gate_issues_top3
ok_sh = sh in db.soft_hold_top3
ok_crew = crew_job in db.crew_gap_top3
ok_attn = na in db.needs_attention_top3
ok_cf = cf in db.cash_flow_top3
ok = all([ok_gate, ok_sh, ok_crew, ok_attn, ok_cf])
# All top3s have len <= 3
sizes = {
    "gate_issues": len(db.gate_issues_top3),
    "soft_hold": len(db.soft_hold_top3),
    "crew_gap": len(db.crew_gap_top3),
    "needs_attention": len(db.needs_attention_top3),
    "cash_flow": len(db.cash_flow_top3),
}
print("T4: sizes =", sizes,
      " contains fixtures: gate=", ok_gate, " sh=", ok_sh, " crew=", ok_crew,
      " attn=", ok_attn, " cf=", ok_cf)
size_ok = all(s <= 3 for s in sizes.values())
print("T4:", "PASS" if (ok and size_ok) else "FAIL")
results["T4"] = ok and size_ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T5 - action_open_gate_issues returns correct action dict")
print("=" * 72)
db = env["commercial.job.dashboard"].create({})
action = db.action_open_gate_issues()
ok = (action.get("type") == "ir.actions.act_window"
      and action.get("res_model") == "commercial.job"
      and ("gate_result", "in", ("reject", "warning")) in action.get("domain", []))
print("T5: action =", {k: v for k, v in action.items() if k != "context"})
print("T5:", "PASS" if ok else "FAIL")
results["T5"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T6 - My Schedule upcoming for the crew user")
print("=" * 72)
# Assign crew_user as confirmed on crew_job (already active, event_date in future)
crew_assignment = env["commercial.job.crew"].search([
    ("job_id", "=", crew_job.id), ("user_id", "=", crew_user.id),
])
crew_assignment.write({"state": "confirmed"})
env.cr.commit()
sched = env["commercial.job.crew.schedule"].with_user(crew_user).create({})
ok = (sched.my_upcoming_count >= 1 and crew_job in sched.my_upcoming_top3)
print("T6: count =", sched.my_upcoming_count,
      " crew_job in top3:", crew_job in sched.my_upcoming_top3)
print("T6:", "PASS" if ok else "FAIL")
results["T6"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T7 - My Schedule pending confirms")
print("=" * 72)
# Make a new active job and assign crew_user as pending
pj = mk_job(venue_id=v3.id, venue_room_id=r3.id, event_date=fields.Date.add(today, days=120))
pj.write({"state": "active", "soft_hold_until": False})
pending_assignment = env["commercial.job.crew"].create({
    "job_id": pj.id, "user_id": crew_user.id, "role": "tech", "state": "pending",
})
env.cr.commit()
sched = env["commercial.job.crew.schedule"].with_user(crew_user).create({})
ok = (sched.my_pending_confirms_count >= 1
      and pending_assignment in sched.my_pending_confirms_top3)
print("T7: count =", sched.my_pending_confirms_count,
      " assignment in top3:", pending_assignment in sched.my_pending_confirms_top3)
print("T7:", "PASS" if ok else "FAIL")
results["T7"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T8 - Crew-only user cannot access Operations Dashboard")
print("=" * 72)
try:
    env["commercial.job.dashboard"].with_user(crew_only).create({})
    print("T8 FAIL: crew-only user was able to access Operations Dashboard")
    results["T8"] = False
except AccessError as e:
    print("T8: AccessError raised as expected:", str(e)[:120])
    results["T8"] = True
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T9 - action_refresh returns act_window with res_id (persisted record)")
print("=" * 72)
ref = env["commercial.job.dashboard"].action_refresh()
ok = bool(ref.get("type") == "ir.actions.act_window"
          and ref.get("res_model") == "commercial.job.dashboard"
          and ref.get("res_id"))
print("T9: action =", ref)
print("T9:", "PASS" if ok else "FAIL")
results["T9"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T10 - Empty-state dashboard for a crew-only user with no fixtures")
print("=" * 72)
# Internal-tier crew-only user. P2.M7.6 removed the base.group_user →
# neon_jobs_user implication, so adding only neon_jobs_crew (no
# neon_jobs_user) makes this user crew-only → _is_crew_only() True →
# user_id filter applies → no own assignments → empty state.
fresh = env["res.users"].create({
    "name": "P2M7 Fresh", "login": "p2m7_fresh",
    "email": "p2m7_fresh@test.local",
    "groups_id": [(6, 0, [
        env.ref("base.group_user").id,
        env.ref("neon_jobs.group_neon_jobs_crew").id,
    ])],
})
sched = env["commercial.job.crew.schedule"].with_user(fresh).create({})
ok = bool(sched.my_upcoming_count == 0
          and sched.my_pending_confirms_count == 0
          and not sched.my_upcoming_top3
          and not sched.my_pending_confirms_top3)
print("T10: upcoming=", sched.my_upcoming_count, " pending=",
      sched.my_pending_confirms_count, " top3s empty=",
      not (sched.my_upcoming_top3 or sched.my_pending_confirms_top3))
print("T10:", "PASS" if ok else "FAIL")
results["T10"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T11 - Crew confirm button")
print("=" * 72)
# Use the pending_assignment from T7
pending_assignment.invalidate_recordset()
pending_assignment.with_user(crew_user).action_confirm()
pending_assignment.invalidate_recordset()
ok = bool(pending_assignment.state == "confirmed"
          and pending_assignment.responded_on)
print("T11: state=", pending_assignment.state,
      " responded_on=", pending_assignment.responded_on)
print("T11:", "PASS" if ok else "FAIL")
results["T11"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T12 - Crew decline wizard flow")
print("=" * 72)
# Create another pending assignment for crew_user
pj2 = mk_job(venue_id=v3.id, venue_room_id=r3.id, event_date=fields.Date.add(today, days=140))
pj2.write({"state": "active", "soft_hold_until": False})
decl_assign = env["commercial.job.crew"].create({
    "job_id": pj2.id, "user_id": crew_user.id, "role": "tech", "state": "pending",
})
env.cr.commit()
wiz = env["commercial.job.crew.decline.wizard"].with_user(crew_user).create({
    "crew_id": decl_assign.id,
    "decline_reason": "T12 — unavailable that weekend",
})
wiz.action_confirm()
decl_assign.invalidate_recordset()
ok = bool(decl_assign.state == "declined"
          and "unavailable" in (decl_assign.decline_reason or "")
          and decl_assign.responded_on)
print("T12: state=", decl_assign.state,
      " reason=", decl_assign.decline_reason,
      " responded=", bool(decl_assign.responded_on))
print("T12:", "PASS" if ok else "FAIL")
results["T12"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T13 - action_open is a per-user singleton (no record accumulation)")
print("=" * 72)
env["commercial.job.dashboard"].search([("create_uid", "=", env.uid)]).unlink()
env.cr.commit()
env["commercial.job.dashboard"].action_open()
after_first = env["commercial.job.dashboard"].search_count(
    [("create_uid", "=", env.uid)])
env["commercial.job.dashboard"].action_open()
after_second = env["commercial.job.dashboard"].search_count(
    [("create_uid", "=", env.uid)])
ok = (after_first == 1 and after_second == 1)
print("T13: after 1st open =", after_first, " after 2nd open =", after_second)
print("T13:", "PASS" if ok else "FAIL")
results["T13"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T14 - action_open returns act_window with res_id (browser-path fix)")
print("=" * 72)
action = env["commercial.job.dashboard"].action_open()
ok = bool(action.get("res_id")
          and action.get("view_mode") == "form"
          and action.get("type") == "ir.actions.act_window")
print("T14: action =", action)
print("T14:", "PASS" if ok else "FAIL")
results["T14"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T15 - Browser read path: open + read(res_id) returns populated data")
print("=" * 72)
action = env["commercial.job.dashboard"].action_open()
rec = env["commercial.job.dashboard"].browse(action["res_id"])
data = rec.read([
    "gate_issues_count", "soft_hold_count", "crew_gap_count",
    "needs_attention_count", "cash_flow_count",
    "gate_issues_top3", "soft_hold_top3",
])[0]
# Counts depend on fixtures; just verify they're integers and that at
# least one section returned something (we created fixtures earlier).
total = (data["gate_issues_count"] + data["soft_hold_count"]
         + data["crew_gap_count"] + data["needs_attention_count"]
         + data["cash_flow_count"])
ok = total > 0 and isinstance(data["gate_issues_top3"], list)
print("T15: data =", {k: v for k, v in data.items()
                       if k != "id" and not k.endswith("top3")})
print("    gate_issues_top3 ids =", data["gate_issues_top3"])
print("T15:", "PASS" if ok else "FAIL")
results["T15"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T16 - Crew-only user: my_upcoming_top3 limited to own assignments")
print("=" * 72)
# Set up: jobA confirmed for crew_only, jobB confirmed for crew_user.
# crew_only should see jobA but NOT jobB.
v_t16 = env["res.partner"].create({
    "name": "P2M7 T16 Venue", "is_company": True, "is_venue": True,
})
r_t16 = env["venue.room"].create({
    "name": "P2M7 T16 Room", "venue_id": v_t16.id, "capacity": 50,
})
jobA = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": v_t16.id,
    "venue_room_id": r_t16.id,
    "event_date": fields.Date.add(today, days=160),
    "currency_id": env.company.currency_id.id,
})
jobA.write({"state": "active", "soft_hold_until": False})
env["commercial.job.crew"].create({
    "job_id": jobA.id, "user_id": crew_only.id,
    "role": "tech", "state": "confirmed",
})
jobB = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": v_t16.id,
    "venue_room_id": r_t16.id,
    "event_date": fields.Date.add(today, days=170),
    "currency_id": env.company.currency_id.id,
})
jobB.write({"state": "active", "soft_hold_until": False})
env["commercial.job.crew"].create({
    "job_id": jobB.id, "user_id": crew_user.id,
    "role": "tech", "state": "confirmed",
})
env.cr.commit()

# Open schedule as crew_only — should see jobA, NOT jobB.
# Verify via the scoped helper (no limit=3 truncation noise) instead
# of the top3 M2M.
action_crew = env["commercial.job.crew.schedule"].with_user(crew_only).action_open()
sched_crew = env["commercial.job.crew.schedule"].with_user(crew_only).browse(action_crew["res_id"])
scoped_ids = sched_crew._scoped_confirmed_job_ids()
ok = bool(jobA.id in scoped_ids and jobB.id not in scoped_ids)
print("T16: crew_only scoped confirmed job ids =", scoped_ids,
      " jobA in:", jobA.id in scoped_ids,
      " jobB in:", jobB.id in scoped_ids)
print("T16:", "PASS" if ok else "FAIL")
results["T16"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T17 - Manager: my_upcoming_top3 sees all users' assignments")
print("=" * 72)
# Same fixtures from T16 are still active. Open as env.user (admin/manager).
# Should see BOTH jobA and jobB (no user_id filter for non-crew-only users).
# Verify via the scoped helper, NOT the limit=3 top3 (other earlier
# fixtures crowd out jobB by event_date ordering).
action_mgr = env["commercial.job.crew.schedule"].action_open()
sched_mgr = env["commercial.job.crew.schedule"].browse(action_mgr["res_id"])
scoped_ids = sched_mgr._scoped_confirmed_job_ids()
ok = bool(jobA.id in scoped_ids
          and jobB.id in scoped_ids
          and not sched_mgr._is_crew_only())
print("T17: manager scoped confirmed job ids count =", len(scoped_ids),
      " jobA in:", jobA.id in scoped_ids,
      " jobB in:", jobB.id in scoped_ids,
      " is_crew_only =", sched_mgr._is_crew_only())
print("T17:", "PASS" if ok else "FAIL")
results["T17"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10",
         "T11", "T12", "T13", "T14", "T15", "T16", "T17"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
