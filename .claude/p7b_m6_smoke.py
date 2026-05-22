"""P7b.M6 smoke -- activation flow + Promote wizard
(13 tests including M6 amendment).

T7b600  candidate in 'candidate' state -> UserError on promote
T7b601  candidate in 'cert_collection' state -> UserError
T7b602  probationary candidate + no user_id + create_user=True
        -> res.users created with base.group_user + jobs_crew
        + training_user
T7b603  state='active' + date_activated set after promote
T7b604  audit_log entry created: action='promote_active',
        actor=current_user
T7b605  candidate WITH user_id + create_user=False -> no new
        user, just state transition
T7b606  duplicate login attempt -> UserError
T7b607  ready_for_promotion=True when state=probationary AND
        jobs_completed >= jobs_target
T7b608  ready_for_promotion=False after state=active
T7b609  sales_rep cannot launch promote wizard (group_id on
        the action filters it out -- assert via _get_view
        groups behaviour OR direct call raises AccessError)

M6 amendment (22 May 2026):
T7b610  event_job state -> 'completed' refreshes candidate.
        probationary_jobs_completed in real-time (no cron)
T7b611  Promote wizard with jobs_completed < jobs_target ->
        audit log reason contains 'OVERRIDE'
T7b612  Promote wizard with jobs_completed >= jobs_target ->
        audit log reason does NOT contain 'OVERRIDE'
"""
from datetime import timedelta

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

Users = env["res.users"]
Candidate = env["neon.onboarding.candidate"]
Wizard = env["neon.onboarding.promote.wizard"]
AuditLog = env["neon.onboarding.audit.log"]


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
u_train_admin = _get_or_create_user(
    "p7b_m1_training_admin", "P7b M1 Training Admin",
    ["neon_training.group_neon_training_admin"])
u_sales = _get_or_create_user(
    "p7b_m1_sales_rep", "P7b M1 Sales Rep",
    ["neon_core.group_neon_sales_rep"])
print(f"  fixture users ready")
env.cr.commit()


# ============================================================
print()
print("=" * 72)
print("T7b600 - candidate state -> UserError")
print("=" * 72)
cand_600 = Candidate.sudo().create({
    "name": "T7b600 Test",
    "intended_role": "runner",
    "contact_phone": "+263771000600",
    "contact_email": "t7b600@example.com",
    "state": "candidate",
})
wiz_600 = Wizard.with_user(u_super).create({
    "candidate_id": cand_600.id,
    "create_user": True,
    "proposed_login": "t7b600@example.com",
})
err, _r = _try(lambda: wiz_600.action_promote())
ok = isinstance(err, UserError) and "probationary" in (str(err) or "").lower()
print(f"  err class: {type(err).__name__ if err else None}")
print(f"  msg: {str(err)[:90] if err else ''}")
print("T7b600:", "PASS" if ok else "FAIL")
results["T7b600"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b601 - cert_collection state -> UserError")
print("=" * 72)
cand_601 = Candidate.sudo().create({
    "name": "T7b601 Test",
    "intended_role": "runner",
    "contact_phone": "+263771000601",
    "contact_email": "t7b601@example.com",
    "state": "cert_collection",
})
wiz_601 = Wizard.with_user(u_super).create({
    "candidate_id": cand_601.id,
    "create_user": True,
    "proposed_login": "t7b601@example.com",
})
err, _r = _try(lambda: wiz_601.action_promote())
ok = isinstance(err, UserError)
print(f"  err class: {type(err).__name__ if err else None}")
print("T7b601:", "PASS" if ok else "FAIL")
results["T7b601"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b602 - probationary + create_user=True -> new user")
print("=" * 72)
cand_602 = Candidate.sudo().create({
    "name": "T7b602 New Crew",
    "intended_role": "runner",
    "contact_phone": "+263771000602",
    "contact_email": "t7b602@example.com",
    "state": "probationary",
})
wiz_602 = Wizard.with_user(u_super).create({
    "candidate_id": cand_602.id,
    "create_user": True,
    "proposed_login": "t7b602@example.com",
})
wiz_602.action_promote()
cand_602.invalidate_recordset()
new_user = cand_602.user_id
# Group membership check.
g_base = env.ref("base.group_user")
g_crew = env.ref("neon_jobs.group_neon_jobs_crew")
g_train = env.ref("neon_training.group_neon_training_user")
ok = bool(new_user) and (
    new_user.login == "t7b602@example.com"
    and new_user in g_base.users
    and new_user in g_crew.users
    and new_user in g_train.users
)
print(f"  new_user.login={new_user.login if new_user else None}")
print(f"  in base.group_user: {new_user in g_base.users if new_user else False}")
print(f"  in jobs_crew:       {new_user in g_crew.users if new_user else False}")
print(f"  in training_user:   {new_user in g_train.users if new_user else False}")
print("T7b602:", "PASS" if ok else "FAIL")
results["T7b602"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b603 - state='active' + date_activated set")
print("=" * 72)
ok = (cand_602.state == "active"
      and bool(cand_602.date_activated))
print(f"  state={cand_602.state} date_activated={cand_602.date_activated}")
print("T7b603:", "PASS" if ok else "FAIL")
results["T7b603"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b604 - audit_log entry created")
print("=" * 72)
audit_602 = AuditLog.sudo().search([
    ("candidate_id", "=", cand_602.id),
    ("action", "=", "promote_active"),
])
ok = (len(audit_602) == 1
      and audit_602.previous_state == "probationary"
      and audit_602.new_state == "active"
      and audit_602.actor_id == u_super)
print(f"  audit count={len(audit_602)} "
      f"prev={audit_602.previous_state if audit_602 else None} "
      f"new={audit_602.new_state if audit_602 else None} "
      f"actor={audit_602.actor_id.login if audit_602 else None}")
print("T7b604:", "PASS" if ok else "FAIL")
results["T7b604"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b605 - candidate with user_id + create_user=False")
print("=" * 72)
# Pre-existing user.
u_existing = _get_or_create_user(
    "p7b_m6_existing", "P7b M6 Existing User",
    ["neon_jobs.group_neon_jobs_crew"])
cand_605 = Candidate.sudo().create({
    "name": "T7b605 Linked Candidate",
    "intended_role": "runner",
    "contact_phone": "+263771000605",
    "user_id": u_existing.id,
    "state": "probationary",
})
prev_user_count = Users.sudo().search_count([])
wiz_605 = Wizard.with_user(u_super).create({
    "candidate_id": cand_605.id,
    "create_user": False,
})
wiz_605.action_promote()
post_user_count = Users.sudo().search_count([])
cand_605.invalidate_recordset()
ok = (cand_605.state == "active"
      and cand_605.user_id == u_existing
      and post_user_count == prev_user_count)
print(f"  cand state={cand_605.state} "
      f"linked user={cand_605.user_id.login} "
      f"users delta={post_user_count - prev_user_count}")
print("T7b605:", "PASS" if ok else "FAIL")
results["T7b605"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b606 - duplicate login attempt -> UserError")
print("=" * 72)
# T7b602 created t7b602@example.com user. Try creating another
# candidate that wants to promote with the same login.
cand_606 = Candidate.sudo().create({
    "name": "T7b606 Dup Login",
    "intended_role": "runner",
    "contact_phone": "+263771000606",
    "contact_email": "t7b602@example.com",  # collides
    "state": "probationary",
})
wiz_606 = Wizard.with_user(u_super).create({
    "candidate_id": cand_606.id,
    "create_user": True,
    "proposed_login": "t7b602@example.com",
})
err, _r = _try(lambda: wiz_606.action_promote())
ok = isinstance(err, UserError) and "already exists" in (str(err) or "").lower()
print(f"  err class: {type(err).__name__ if err else None}")
print(f"  msg: {str(err)[:90] if err else ''}")
print("T7b606:", "PASS" if ok else "FAIL")
results["T7b606"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b607 - ready_for_promotion=True when jobs met")
print("=" * 72)
cand_607 = Candidate.sudo().create({
    "name": "T7b607 Ready",
    "intended_role": "runner",
    "contact_phone": "+263771000607",
    "state": "probationary",
    # Set target=0 so jobs_completed=0 satisfies the >=
    # comparison. The full path (target=3, completed via
    # event_job state writes) requires the M5 stored-compute
    # workaround (env.cr.execute UPDATE on event_job state
    # plus explicit _compute call). M6 ready_for_promotion
    # is non-stored, so the compute fires on access -- this
    # variant exercises that path cleanly.
    "probationary_jobs_target": 0,
})
cand_607.invalidate_recordset()
ok = cand_607.ready_for_promotion is True
print(f"  jobs_completed={cand_607.probationary_jobs_completed} "
      f"jobs_target={cand_607.probationary_jobs_target} "
      f"ready={cand_607.ready_for_promotion}")
print("T7b607:", "PASS" if ok else "FAIL")
results["T7b607"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b608 - ready_for_promotion=False after state=active")
print("=" * 72)
# cand_602 was promoted to active in T7b602; check ready flag.
cand_602.invalidate_recordset()
ok = cand_602.ready_for_promotion is False
print(f"  state={cand_602.state} ready={cand_602.ready_for_promotion}")
print("T7b608:", "PASS" if ok else "FAIL")
results["T7b608"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b609 - sales_rep cannot use Promote wizard (ACL)")
print("=" * 72)
# ir.model.access.csv has no row for sales_rep on the wizard
# model. Wizard create as sales_rep should raise AccessError.
cand_609 = Candidate.sudo().create({
    "name": "T7b609 No ACL",
    "intended_role": "runner",
    "contact_phone": "+263771000609",
    "state": "probationary",
})
err, _r = _try(
    lambda: Wizard.with_user(u_sales).create({
        "candidate_id": cand_609.id,
        "create_user": False,
    }))
ok = isinstance(err, AccessError)
print(f"  err class: {type(err).__name__ if err else None}")
print("T7b609:", "PASS" if ok else "FAIL")
results["T7b609"] = ok


# ============================================================
# M6 amendment tests (22 May 2026)
# ============================================================
print()
print("=" * 72)
print("T7b610 - event_job complete -> jobs_completed refresh")
print("=" * 72)
# Test the inherit hook in neon_onboarding/models/commercial_
# event_job.py. The hook fires on ORM write where vals
# contains state='completed' and triggers a recompute of
# probationary_jobs_completed on candidates whose user is on
# the crew. Use Phase 7a's _allow_state_write context flag
# (per the state-transition-only guard) to perform the write
# without walking every action_move_to_* method.
u_610 = _get_or_create_user(
    "p7b_m6_amend_610", "P7b M6 Amend 610",
    ["neon_jobs.group_neon_jobs_crew"])
cand_610 = Candidate.sudo().create({
    "name": "T7b610 Real-Time Counter",
    "intended_role": "runner",
    "contact_phone": "+263771000610",
    "state": "probationary",
    "user_id": u_610.id,
})
AuditLog.sudo().create({
    "candidate_id": cand_610.id,
    "action": "promote_probationary",
    "actor_id": SUPERUSER_ID,
    "reason": "T7b610 fixture",
    "previous_state": "cert_collection",
    "new_state": "probationary",
})
Job = env["commercial.job"]
EventJob = env["commercial.event.job"]
Crew = env["commercial.job.crew"]
sample_job = Job.sudo().search([], limit=1)
job_610 = Job.sudo().create({
    "name": "T7b610 Test Job",
    "partner_id": sample_job.partner_id.id,
    "venue_id": sample_job.venue_id.id,
    "currency_id": sample_job.currency_id.id,
    "event_date": fields.Date.today() + timedelta(days=7),
})
crew_610 = Crew.sudo().create({
    "job_id": job_610.id,
    "user_id": u_610.id,
    "role": "runner",
})
ej_610 = EventJob.sudo().create({
    "commercial_job_id": job_610.id,
    "name": "T7b610 Event",
    "event_date": fields.Date.today() + timedelta(days=7),
    "state": "planning",
})
cand_610.invalidate_recordset()
prior_count = cand_610.probationary_jobs_completed
# Bypass the state-write guard via the documented context
# flag _allow_state_write=True. This invokes the FULL write
# chain including the neon_onboarding inherit hook.
ej_610.sudo().with_context(_allow_state_write=True).write({
    "state": "completed",
})
cand_610.invalidate_recordset()
new_count = cand_610.probationary_jobs_completed
ok = (new_count == prior_count + 1)
print(f"  prior_count={prior_count} new_count={new_count}")
print("T7b610:", "PASS" if ok else "FAIL")
results["T7b610"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b611 - early promote -> OVERRIDE in audit reason")
print("=" * 72)
cand_611 = Candidate.sudo().create({
    "name": "T7b611 Early Promote",
    "intended_role": "runner",
    "contact_phone": "+263771000611",
    "contact_email": "t7b611@example.com",
    "state": "probationary",
    "probationary_jobs_target": 3,
})
# jobs_completed defaults to 0 from compute (no completed
# event_jobs). 0 < 3 -> OVERRIDE expected.
wiz_611 = Wizard.with_user(u_super).create({
    "candidate_id": cand_611.id,
    "create_user": True,
    "proposed_login": "t7b611@example.com",
})
wiz_611.action_promote()
audit_611 = AuditLog.sudo().search([
    ("candidate_id", "=", cand_611.id),
    ("action", "=", "promote_active"),
])
ok = (len(audit_611) == 1
      and "OVERRIDE" in (audit_611.reason or ""))
print(f"  audit count={len(audit_611)}")
print(f"  reason: {(audit_611.reason or '')[:120]}")
print("T7b611:", "PASS" if ok else "FAIL")
results["T7b611"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b612 - target met -> no OVERRIDE in audit reason")
print("=" * 72)
u_612 = _get_or_create_user(
    "p7b_m6_amend_612", "P7b M6 Amend 612",
    ["neon_jobs.group_neon_jobs_crew"])
cand_612 = Candidate.sudo().create({
    "name": "T7b612 Target Met",
    "intended_role": "runner",
    "contact_phone": "+263771000612",
    "state": "probationary",
    "probationary_jobs_target": 0,
    "user_id": u_612.id,
})
# target=0; jobs_completed=0; 0 >= 0 -> not OVERRIDE.
wiz_612 = Wizard.with_user(u_super).create({
    "candidate_id": cand_612.id,
    "create_user": False,
})
wiz_612.action_promote()
audit_612 = AuditLog.sudo().search([
    ("candidate_id", "=", cand_612.id),
    ("action", "=", "promote_active"),
])
ok = (len(audit_612) == 1
      and "OVERRIDE" not in (audit_612.reason or ""))
print(f"  audit count={len(audit_612)}")
print(f"  reason: {(audit_612.reason or '')[:120]}")
print("T7b612:", "PASS" if ok else "FAIL")
results["T7b612"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T7b600", "T7b601", "T7b602", "T7b603", "T7b604",
        "T7b605", "T7b606", "T7b607", "T7b608", "T7b609",
        "T7b610", "T7b611", "T7b612"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
