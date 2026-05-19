"""P2.M7.5 smoke — role model hardening + Lead Tech + crew calendar.

P2.M7.5.1 refactor (2026-05-18): test users are now PERSISTENT via
_get_or_create_user. user_ids stay stable across regression runs,
which avoids advancing the res_users id sequence on every cycle and
preserves audit-trail FKs (mail.activity, action.centre.item.history)
pointing at the fixtures.

Baseline groups_id is enforced on every setUp via (6, 0, [...])
replace semantics. Manual UI customisations on the fixture users
(e.g. an admin granting an extra group via Settings → Users) are
WIPED on next setUp. Tests that mutate fixture groups mid-run
(notably T25 — adds crew_leader to sales) rely on this reset
between regression cycles to start each run from a clean baseline;
within a single run, downstream tests must not depend on the
baseline state of a mid-test-mutated user.

Sub-record state — commercial.job, commercial.job.crew,
mail.activity tied to p2m75_* users, P2M75-prefixed partners — IS
still cleared on every setUp by _cleanup_per_test_state. Fixture
users live; their per-test debris does not.
"""
from odoo import fields, SUPERUSER_ID
from odoo.exceptions import AccessError


# ============================================================
# Fixture helpers — get-or-create pattern.
# Mirrors .claude/seed_p4m9_production_smoke.py:_get_or_create_user.
# ============================================================
def _get_or_create_user(login, name, group_xmlids):
    """Return the user with this login, or create it. On existing
    users, write the baseline groups_id (replace, not add) so the
    fixture starts each smoke run in a known state."""
    user = env["res.users"].sudo().search(
        [("login", "=", login)], limit=1)
    grp_ids = [env.ref(x).id for x in group_xmlids]
    if user:
        user.sudo().write({
            "name": name,
            "password": "test123",
            "groups_id": [(6, 0, grp_ids)],
        })
        return user, False
    return env["res.users"].sudo().create({
        "login": login,
        "name": name,
        "email": "%s@test.local" % login,
        "password": "test123",
        "groups_id": [(6, 0, grp_ids)],
    }), True


def _cleanup_per_test_state():
    """Clear sub-records that accumulate between regression runs.
    Does NOT touch res.users — those are persistent fixtures.
    Test-fixture partners ("P2M75 Venue" / "P2M75 Client") are
    cleared and re-created each run; user partners ("P2M75 Sales"
    etc.) are skipped because Odoo's _unlink_except_user blocks
    unlink of any partner with a linked active user."""
    p2m75_users = env["res.users"].sudo().search(
        [("login", "like", "p2m75_")])
    p2m75_user_ids = p2m75_users.ids
    p2m75_user_partner_ids = p2m75_users.partner_id.ids
    env["mail.activity"].sudo().search(
        [("user_id", "in", p2m75_user_ids)]).unlink()
    env["commercial.job.crew"].sudo().search([]).unlink()
    # Polish-backlog: narrow this LIKE 'JOB-' match to test-marked
    # records only. Currently matches every commercial.job in the DB
    # because JOB-NNNNNN is the auto-sequence prefix. Acceptable on
    # local dev DB; reckless on production. Don't run this smoke
    # against any DB that holds real job records.
    env["commercial.job"].sudo().search(
        [("name", "like", "JOB-")]).unlink()
    env["res.partner"].sudo().search([
        ("name", "like", "P2M75"),
        ("id", "not in", p2m75_user_partner_ids),
    ]).unlink()
    env.cr.commit()


# ============================================================
# SETUP
# ============================================================
print("=" * 72)
print("SETUP")
print("=" * 72)
env.user.write({
    "groups_id": [(4, env.ref("neon_jobs.group_neon_jobs_manager").id)],
})

_cleanup_per_test_state()

# Fixture partners (re-created each run — these are scoped to the
# smoke and not referenced across smokes).
venue = env["res.partner"].create({
    "name": "P2M75 Venue", "is_company": True, "is_venue": True,
})
client = env["res.partner"].create({
    "name": "P2M75 Client", "is_company": True,
})

# Fixture users — 7 baseline + p2m75_t20 spawned mid-T20.
# - sales:     internal user, neon_jobs_user; quote drafting / read
# - mgr:       Operations manager (NOT a finance role)
# - lead:      Lead Tech, internal + crew_leader
# - crew:      internal + crew tier ("self" in ownership tests)
# - other:     internal + crew tier (counterpart in ownership tests)
# - book:      Phase 6+ bookkeeper — rate cards, conversion rates
# - approver:  Phase 6+ approver — quote / cost-line approval
USER_SPECS = [
    ("p2m75_sales",    "P2M75 Sales", [
        "base.group_user",
        "neon_jobs.group_neon_jobs_user",
        # P6.M2 — Phase 6 sales reps carry the finance/sales group in
        # production so they can draft quotes. Adding here keeps the
        # fixture consistent with that reality; P6.M1's transient
        # bind in p6m1_smoke.py is now idempotent (no breakage).
        "neon_finance.group_neon_finance_sales"]),
    ("p2m75_mgr",      "P2M75 Manager", [
        "base.group_user",
        "neon_jobs.group_neon_jobs_manager"]),
    ("p2m75_lead",     "P2M75 Crew Leader", [
        "base.group_user",
        "neon_jobs.group_neon_jobs_crew_leader"]),
    ("p2m75_crew",     "P2M75 Crew", [
        "base.group_user",
        "neon_jobs.group_neon_jobs_crew"]),
    ("p2m75_other",    "P2M75 Other Crew", [
        "base.group_user",
        "neon_jobs.group_neon_jobs_crew"]),
    ("p2m75_book",     "P2M75 Bookkeeper", [
        "base.group_user",
        "neon_finance.group_neon_finance_bookkeeper"]),
    ("p2m75_approver", "P2M75 Approver", [
        "base.group_user",
        "neon_finance.group_neon_finance_approver"]),
]

users = {}
for login, name, groups in USER_SPECS:
    u, _was_new = _get_or_create_user(login, name, groups)
    users[login] = u

sales = users["p2m75_sales"]
manager = users["p2m75_mgr"]
crew_leader = users["p2m75_lead"]
crew_only = users["p2m75_crew"]
other_crew = users["p2m75_other"]
bookkeeper = users["p2m75_book"]
approver = users["p2m75_approver"]
env.cr.commit()

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
# Get-or-create so the second regression run finds the existing
# p2m75_t20 instead of hitting a UNIQUE login violation. Baseline
# groups are re-asserted on every run.
t20_user, _ = _get_or_create_user(
    "p2m75_t20", "P2M75 T20 Target",
    ["base.group_user", "neon_jobs.group_neon_jobs_crew"])
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
print("T_USER_STABILITY - setUp twice; all p2m75_* user_ids unchanged")
print("=" * 72)
# Capture baseline ids from the current setUp, then re-invoke the
# get-or-create helpers for every fixture login. Existing rows must
# be found and reused; no new res.users records may appear.
baseline_ids = {
    login: env["res.users"].sudo().search(
        [("login", "=", login)], limit=1).id
    for login, _, _ in USER_SPECS
}
baseline_ids["p2m75_t20"] = env["res.users"].sudo().search(
    [("login", "=", "p2m75_t20")], limit=1).id

for login, name, groups in USER_SPECS:
    _get_or_create_user(login, name, groups)
_get_or_create_user(
    "p2m75_t20", "P2M75 T20 Target",
    ["base.group_user", "neon_jobs.group_neon_jobs_crew"])
env.cr.commit()

post_ids = {
    login: env["res.users"].sudo().search(
        [("login", "=", login)], limit=1).id
    for login in baseline_ids
}
diffs = [
    (login, baseline_ids[login], post_ids[login])
    for login in baseline_ids
    if baseline_ids[login] != post_ids[login]
]
ok = not diffs
for login in sorted(baseline_ids):
    before = baseline_ids[login]
    after = post_ids[login]
    print("  %-16s id=%d  -> %d  %s" % (
        login, before, after,
        "OK" if before == after else "CHANGED"))
print("T_USER_STABILITY:", "PASS" if ok else "FAIL")
results["T_USER_STABILITY"] = ok


# ============================================================
print()
print("=" * 72)
print("T_USER_BOOK_EXISTS - p2m75_book has bookkeeper group")
print("=" * 72)
book = env["res.users"].sudo().search(
    [("login", "=", "p2m75_book")], limit=1)
g_book = env.ref("neon_finance.group_neon_finance_bookkeeper")
ok = bool(book) and book.has_group(
    "neon_finance.group_neon_finance_bookkeeper")
print("  user exists:", bool(book), " id:", book.id if book else None)
print("  in group_neon_finance_bookkeeper:",
      book.has_group("neon_finance.group_neon_finance_bookkeeper")
      if book else None)
print("T_USER_BOOK_EXISTS:", "PASS" if ok else "FAIL")
results["T_USER_BOOK_EXISTS"] = ok


# ============================================================
print()
print("=" * 72)
print("T_USER_APPROVER_EXISTS - p2m75_approver has approver group")
print("=" * 72)
appr = env["res.users"].sudo().search(
    [("login", "=", "p2m75_approver")], limit=1)
g_appr = env.ref("neon_finance.group_neon_finance_approver")
ok = bool(appr) and appr.has_group(
    "neon_finance.group_neon_finance_approver")
print("  user exists:", bool(appr), " id:", appr.id if appr else None)
print("  in group_neon_finance_approver:",
      appr.has_group("neon_finance.group_neon_finance_approver")
      if appr else None)
print("T_USER_APPROVER_EXISTS:", "PASS" if ok else "FAIL")
results["T_USER_APPROVER_EXISTS"] = ok


# ============================================================
print()
print("=" * 72)
print("T_USER_BASELINE_SYNC - non-baseline group on p2m75_mgr wiped by setUp")
print("=" * 72)
# Guardrail against future regressions toward a "preserve manual
# grants" anti-pattern. Add an extra group to p2m75_mgr that is NOT
# in its baseline spec, re-invoke the get-or-create helper, then
# assert the extra group is gone.
extra_group = env.ref("neon_jobs.group_neon_jobs_crew_leader")
manager.sudo().write({"groups_id": [(4, extra_group.id)]})
manager.invalidate_recordset()
assert extra_group in manager.groups_id, (
    "Pre-condition failed: extra group did not land on p2m75_mgr.")

# Re-invoke the same get-or-create spec from USER_SPECS — the
# baseline groups_id should be re-asserted via (6, 0, [...]).
_get_or_create_user(
    "p2m75_mgr", "P2M75 Manager",
    ["base.group_user", "neon_jobs.group_neon_jobs_manager"])
env.cr.commit()
manager.invalidate_recordset()
ok = extra_group not in manager.groups_id
print("  extra group (crew_leader) after re-setUp:",
      "absent (good)" if ok else "still present (bad)")
print("  p2m75_mgr current groups:",
      [g.name for g in manager.groups_id])
print("T_USER_BASELINE_SYNC:", "PASS" if ok else "FAIL")
results["T_USER_BASELINE_SYNC"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T18", "T19", "T20", "T21", "T22", "T23", "T24", "T25", "T26",
         "T_USER_STABILITY", "T_USER_BOOK_EXISTS",
         "T_USER_APPROVER_EXISTS", "T_USER_BASELINE_SYNC"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
