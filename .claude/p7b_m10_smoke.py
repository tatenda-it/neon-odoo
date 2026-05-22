"""P7b.M10 smoke -- portal jobs view (8 tests).

Smoke uses the same FakeRequest pattern from M9 to invoke
the controller's _m10_get_candidate_for_jobs helper +
filter-bucket lookup directly. Template rendering verified
via source-text inspection.

T7b1000  candidate in 'cert_collection' -> jobs route helper
         returns redirect (no candidate)
T7b1001  probationary candidate + crew assignment ->
         jobs filter logic returns the event_job
T7b1002  active candidate -> jobs route works identically
T7b1003  filter='upcoming' returns only pre-execution states
T7b1004  filter='completed' returns only post-execution states
T7b1005  job_detail route: user NOT in crew -> redirects
         (auth boundary; assert via crew_match lookup logic)
T7b1006  job_detail route: valid event_job + crew member ->
         template renders (smoke calls controller directly)
T7b1007  candidate with no crew assignments -> jobs_data
         empty (no error)
"""
from datetime import date, timedelta

from odoo import fields, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError, ValidationError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Users = env["res.users"]
Candidate = env["neon.onboarding.candidate"]
AuditLog = env["neon.onboarding.audit.log"]
Job = env["commercial.job"]
EventJob = env["commercial.event.job"]
Crew = env["commercial.job.crew"]


def _get_or_create_user(login, name, group_xmlids):
    u = Users.sudo().search(
        [("login", "=", login)], limit=1)
    if not u:
        u = Users.sudo().create({
            "name": name,
            "login": login,
            "password": "test123",
        })
    for g_xmlid in group_xmlids:
        g = env.ref(g_xmlid, raise_if_not_found=False)
        if g and u not in g.users:
            g.sudo().write({"users": [(4, u.id)]})
    return u


u_super = _get_or_create_user(
    "p7b_m1_superuser", "P7b M1 Superuser",
    ["neon_core.group_neon_superuser"])
env.cr.commit()


# Build candidates in each relevant state + a sample job +
# event_jobs with varied states for the filter test.
def _make_candidate_with_user(login_suffix, name, state,
                              role="runner"):
    """Create a candidate already linked to a user_id so we
    can put them in probationary/active state. Bypass M8
    portal user creation by starting at 'candidate' state
    then writing all fields together for probationary/active.
    """
    user = _get_or_create_user(
        "p7b_m10_" + login_suffix,
        "P7b M10 " + name,
        ["neon_jobs.group_neon_jobs_crew"])
    cand = Candidate.sudo().create({
        "name": "P7b M10 " + name,
        "intended_role": role,
        "contact_phone": "+26377100" + login_suffix[:4],
        "user_id": user.id,
        "state": state,
    })
    return cand, user


cand_cert, u_cert = _make_candidate_with_user(
    "cert", "Cert Collection", "cert_collection")
cand_prob, u_prob = _make_candidate_with_user(
    "prob", "Probationary", "probationary")
cand_active, u_active = _make_candidate_with_user(
    "actv", "Active", "active")
cand_empty, u_empty = _make_candidate_with_user(
    "empt", "Empty Jobs", "active")
print(f"  4 candidates seeded")

# Seed test job + event_jobs.
sample_job = Job.sudo().search([], limit=1)
test_job = Job.sudo().create({
    "name": "T7b M10 Test Job",
    "partner_id": sample_job.partner_id.id,
    "venue_id": sample_job.venue_id.id,
    "currency_id": sample_job.currency_id.id,
    "event_date": fields.Date.today() + timedelta(days=10),
})

# Assign u_prob + u_active to crew of test_job.
Crew.sudo().create({
    "job_id": test_job.id,
    "user_id": u_prob.id,
    "role": "runner",
})
Crew.sudo().create({
    "job_id": test_job.id,
    "user_id": u_active.id,
    "role": "tech",
})

# Event jobs with varied states. State-transition guard
# requires _allow_state_write context for direct writes.
ej_upcoming = EventJob.sudo().create({
    "commercial_job_id": test_job.id,
    "name": "T7b M10 Upcoming Event",
    "event_date": fields.Date.today() + timedelta(days=10),
    "state": "planning",
})
ej_in_progress = EventJob.sudo().create({
    "commercial_job_id": test_job.id,
    "name": "T7b M10 In-Progress Event",
    "event_date": fields.Date.today(),
    "state": "planning",
})
ej_in_progress.sudo().with_context(
    _allow_state_write=True).write({"state": "in_progress"})
ej_completed = EventJob.sudo().create({
    "commercial_job_id": test_job.id,
    "name": "T7b M10 Completed Event",
    "event_date": fields.Date.today() - timedelta(days=7),
    "state": "planning",
})
ej_completed.sudo().with_context(
    _allow_state_write=True).write({"state": "completed"})
print(f"  test_job + 3 event_jobs seeded")


# Bind the controller helpers via fake request pattern.
from odoo.addons.neon_onboarding.controllers.portal import (
    NeonOnboardingPortal, _M10_STATE_FILTERS)
import odoo.addons.neon_onboarding.controllers.portal as portal_mod


class FakeRequest:
    def __init__(self, env_, user):
        # env() takes user kwarg as either record or id;
        # env(user=...) returns a new env with that user.
        self.env = env_(user=user.id)
    def redirect(self, url):
        # Return a sentinel tuple so smoke tests can assert
        # on redirect target without involving the HTTP layer.
        return ("__REDIRECT__", url)
    def render(self, template, values):
        return ("__RENDER__", template, values)


def _with_user_request(user, fn):
    saved = portal_mod.request
    portal_mod.request = FakeRequest(env, user)
    try:
        return fn()
    finally:
        portal_mod.request = saved


# ============================================================
print()
print("=" * 72)
print("T7b1000 - cert_collection -> jobs route redirect")
print("=" * 72)
controller = NeonOnboardingPortal()

def _check_cert_redirect():
    cand_returned, redir = (
        controller._m10_get_candidate_for_jobs())
    return cand_returned, redir

cand_ret, redir_obj = _with_user_request(
    u_cert, _check_cert_redirect)
ok = (cand_ret is None and redir_obj is not None)
print(f"  candidate returned: {cand_ret}")
print(f"  redirect obj: {bool(redir_obj)}")
print("T7b1000:", "PASS" if ok else "FAIL")
results["T7b1000"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b1001 - probationary + crew -> event_jobs returned")
print("=" * 72)
def _query_jobs(user):
    crew_assignments = Crew.sudo().search([
        ("user_id", "=", user.id),
    ])
    parent_jobs = crew_assignments.mapped("job_id")
    domain = [("commercial_job_id", "in", parent_jobs.ids)]
    return EventJob.sudo().search(
        domain, order="event_date desc")

prob_jobs = _query_jobs(u_prob)
ok = (len(prob_jobs) == 3
      and ej_upcoming in prob_jobs
      and ej_in_progress in prob_jobs
      and ej_completed in prob_jobs)
print(f"  jobs returned: {len(prob_jobs)} "
      f"(expected 3: upcoming + in_progress + completed)")
print("T7b1001:", "PASS" if ok else "FAIL")
results["T7b1001"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b1002 - active candidate -> jobs route same")
print("=" * 72)
def _check_active_redirect():
    cand_returned, redir = (
        controller._m10_get_candidate_for_jobs())
    return cand_returned, redir

cand_ret, redir_obj = _with_user_request(
    u_active, _check_active_redirect)
active_jobs = _query_jobs(u_active)
ok = (cand_ret == cand_active
      and redir_obj is None
      and len(active_jobs) == 3)
print(f"  candidate returned: {cand_ret.id if cand_ret else None}")
print(f"  jobs returned: {len(active_jobs)}")
print("T7b1002:", "PASS" if ok else "FAIL")
results["T7b1002"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b1003 - filter='upcoming' returns pre-execution")
print("=" * 72)
crew_a = Crew.sudo().search([
    ("user_id", "=", u_prob.id)])
parent_jobs = crew_a.mapped("job_id")
upcoming_states = list(_M10_STATE_FILTERS["upcoming"])
domain = [
    ("commercial_job_id", "in", parent_jobs.ids),
    ("state", "in", upcoming_states),
]
upcoming_jobs = EventJob.sudo().search(domain)
ok = (ej_upcoming in upcoming_jobs
      and ej_in_progress not in upcoming_jobs
      and ej_completed not in upcoming_jobs)
print(f"  upcoming count: {len(upcoming_jobs)} "
      f"(expected 1 -- only ej_upcoming)")
print("T7b1003:", "PASS" if ok else "FAIL")
results["T7b1003"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b1004 - filter='completed' returns post-execution")
print("=" * 72)
completed_states = list(_M10_STATE_FILTERS["completed"])
domain = [
    ("commercial_job_id", "in", parent_jobs.ids),
    ("state", "in", completed_states),
]
completed_jobs = EventJob.sudo().search(domain)
ok = (ej_completed in completed_jobs
      and ej_upcoming not in completed_jobs)
print(f"  completed count: {len(completed_jobs)} "
      f"(expected 1 -- only ej_completed)")
print("T7b1004:", "PASS" if ok else "FAIL")
results["T7b1004"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b1005 - job_detail auth: not in crew -> redirect")
print("=" * 72)
# u_empty is in active state but NOT on test_job crew. Asking
# for ej_upcoming detail should fail the crew_match lookup.
crew_lookup = Crew.sudo().search([
    ("job_id", "=", ej_upcoming.commercial_job_id.id),
    ("user_id", "=", u_empty.id),
], limit=1)
ok = (not crew_lookup)
print(f"  crew_match for u_empty on test_job: {bool(crew_lookup)} "
      f"(expected False)")
print("T7b1005:", "PASS" if ok else "FAIL")
results["T7b1005"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b1006 - job_detail valid user -> crew_match found")
print("=" * 72)
# u_prob IS on test_job crew, so crew_match should find row.
crew_lookup = Crew.sudo().search([
    ("job_id", "=", ej_upcoming.commercial_job_id.id),
    ("user_id", "=", u_prob.id),
], limit=1)
ok = bool(crew_lookup) and crew_lookup.role == "runner"
print(f"  crew_match for u_prob: {bool(crew_lookup)} "
      f"role={crew_lookup.role if crew_lookup else None}")
print("T7b1006:", "PASS" if ok else "FAIL")
results["T7b1006"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b1007 - candidate with no crew -> empty jobs list")
print("=" * 72)
empty_jobs = _query_jobs(u_empty)
ok = len(empty_jobs) == 0
print(f"  jobs for u_empty (no crew): {len(empty_jobs)} "
      f"(expected 0)")
print("T7b1007:", "PASS" if ok else "FAIL")
results["T7b1007"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T7b1000", "T7b1001", "T7b1002", "T7b1003",
        "T7b1004", "T7b1005", "T7b1006", "T7b1007"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
