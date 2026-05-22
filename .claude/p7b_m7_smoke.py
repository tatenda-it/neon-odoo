"""P7b.M7 smoke -- Skip wizard polish + user creation parity
(9 tests).

T7b700  Skip from 'candidate' state + create_user=True + null
        user_id -> res.users created with base+crew+training_user
T7b701  Skip from 'cert_collection' state succeeds (any-state
        to active; unlike M6 Promote which requires probationary)
T7b702  Skip with create_user=False + null user_id -> no user
        created, state transitions to active (constraint:
        active needs user_id -- expect this to RAISE because
        the candidate constraint blocks active without user)
T7b703  Audit log action='skip_onboarding' (NOT
        'promote_active') -- preserves Skip vs Promote
        distinction
T7b704  Audit log reason contains 'Skipped from state:
        <prev_state>'
T7b705  Duplicate login -> UserError
T7b706  candidate.user_id already set + create_user=False ->
        no new user, state transition clean
T7b707  sales_rep cannot launch Skip wizard (ACL block via
        ir.model.access.csv -- no row for sales_rep)
T7b708  bookkeeper cannot launch Skip wizard (only superuser
        has the access row)
"""
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
Wizard = env["neon.onboarding.skip.wizard"]
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
u_sales = _get_or_create_user(
    "p7b_m1_sales_rep", "P7b M1 Sales Rep",
    ["neon_core.group_neon_sales_rep"])
u_bookkeeper = _get_or_create_user(
    "p7b_m7_bookkeeper", "P7b M7 Bookkeeper",
    ["neon_core.group_neon_bookkeeper"])
print(f"  fixture users ready")
env.cr.commit()


# ============================================================
print()
print("=" * 72)
print("T7b700 - Skip from 'candidate' + create_user=True")
print("=" * 72)
cand_700 = Candidate.sudo().create({
    "name": "T7b700 Skip+CreateUser",
    "intended_role": "runner",
    "contact_phone": "+263771000700",
    "contact_email": "t7b700@example.com",
    "state": "candidate",
})
wiz_700 = Wizard.with_user(u_super).create({
    "candidate_id": cand_700.id,
    "reason": "T7b700 -- existing crew bulk-import",
    "create_user": True,
    "proposed_login": "t7b700@example.com",
})
wiz_700.action_skip()
cand_700.invalidate_recordset()
new_user = cand_700.user_id
g_base = env.ref("base.group_user")
g_crew = env.ref("neon_jobs.group_neon_jobs_crew")
g_train = env.ref("neon_training.group_neon_training_user")
ok = bool(new_user) and (
    new_user.login == "t7b700@example.com"
    and new_user in g_base.users
    and new_user in g_crew.users
    and new_user in g_train.users
    and cand_700.state == "active"
)
print(f"  new_user.login={new_user.login if new_user else None}")
print(f"  groups: base={new_user in g_base.users if new_user else False} "
      f"crew={new_user in g_crew.users if new_user else False} "
      f"training={new_user in g_train.users if new_user else False}")
print(f"  cand state={cand_700.state}")
print("T7b700:", "PASS" if ok else "FAIL")
results["T7b700"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b701 - Skip from 'cert_collection' succeeds")
print("=" * 72)
cand_701 = Candidate.sudo().create({
    "name": "T7b701 From Cert Collection",
    "intended_role": "tech",
    "contact_phone": "+263771000701",
    "contact_email": "t7b701@example.com",
    "state": "cert_collection",
})
wiz_701 = Wizard.with_user(u_super).create({
    "candidate_id": cand_701.id,
    "reason": "T7b701 -- skip from cert_collection",
    "create_user": True,
    "proposed_login": "t7b701@example.com",
})
wiz_701.action_skip()
cand_701.invalidate_recordset()
ok = (cand_701.state == "active"
      and bool(cand_701.user_id)
      and bool(cand_701.bypass_actor_id))
print(f"  state={cand_701.state} "
      f"user_id_set={bool(cand_701.user_id)} "
      f"bypass_actor_set={bool(cand_701.bypass_actor_id)}")
print("T7b701:", "PASS" if ok else "FAIL")
results["T7b701"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b702 - Skip + create_user=False + null user_id"
      " (constraint should block)")
print("=" * 72)
cand_702 = Candidate.sudo().create({
    "name": "T7b702 No User Skip",
    "intended_role": "runner",
    "contact_phone": "+263771000702",
    "state": "candidate",
})
wiz_702 = Wizard.with_user(u_super).create({
    "candidate_id": cand_702.id,
    "reason": "T7b702 -- skip without user",
    "create_user": False,
})
err, _r = _try(lambda: wiz_702.action_skip())
# Candidate's _check_active_requires_user constraint should
# fire -- state='active' requires user_id.
ok = isinstance(err, ValidationError) and (
    "user account" in (str(err) or "").lower()
    or "user_id" in (str(err) or "").lower())
print(f"  err class: {type(err).__name__ if err else None}")
print(f"  msg: {str(err)[:90] if err else ''}")
print("T7b702:", "PASS" if ok else "FAIL")
results["T7b702"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b703 - audit action='skip_onboarding'")
print("=" * 72)
audit_700 = AuditLog.sudo().search([
    ("candidate_id", "=", cand_700.id),
])
ok = (len(audit_700) == 1
      and audit_700.action == "skip_onboarding")
print(f"  audit count={len(audit_700)} "
      f"action={audit_700.action if audit_700 else None}")
print("T7b703:", "PASS" if ok else "FAIL")
results["T7b703"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b704 - audit reason captures 'Skipped from state'")
print("=" * 72)
ok = bool(audit_700) and (
    "Skipped from state: candidate"
    in (audit_700.reason or ""))
print(f"  reason: {(audit_700.reason or '')[:120]}")
print("T7b704:", "PASS" if ok else "FAIL")
results["T7b704"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b705 - duplicate login -> UserError")
print("=" * 72)
# t7b700@example.com user created in T7b700. Try skipping a
# new candidate with the same proposed login.
cand_705 = Candidate.sudo().create({
    "name": "T7b705 Dup Login",
    "intended_role": "runner",
    "contact_phone": "+263771000705",
    "contact_email": "t7b700@example.com",
    "state": "candidate",
})
wiz_705 = Wizard.with_user(u_super).create({
    "candidate_id": cand_705.id,
    "reason": "T7b705 -- testing duplicate",
    "create_user": True,
    "proposed_login": "t7b700@example.com",
})
err, _r = _try(lambda: wiz_705.action_skip())
ok = isinstance(err, UserError) and "already exists" in (str(err) or "").lower()
print(f"  err class: {type(err).__name__ if err else None}")
print(f"  msg: {str(err)[:90] if err else ''}")
print("T7b705:", "PASS" if ok else "FAIL")
results["T7b705"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b706 - candidate with user_id + create_user=False")
print("=" * 72)
u_existing = _get_or_create_user(
    "p7b_m7_existing", "P7b M7 Existing User",
    ["neon_jobs.group_neon_jobs_crew"])
cand_706 = Candidate.sudo().create({
    "name": "T7b706 Linked Candidate",
    "intended_role": "runner",
    "contact_phone": "+263771000706",
    "user_id": u_existing.id,
    "state": "probationary",
})
prev_user_count = Users.sudo().search_count([])
wiz_706 = Wizard.with_user(u_super).create({
    "candidate_id": cand_706.id,
    "reason": "T7b706 -- linked user skip",
    "create_user": False,
})
wiz_706.action_skip()
post_user_count = Users.sudo().search_count([])
cand_706.invalidate_recordset()
ok = (cand_706.state == "active"
      and cand_706.user_id == u_existing
      and post_user_count == prev_user_count)
print(f"  state={cand_706.state} "
      f"linked={cand_706.user_id.login} "
      f"users_delta={post_user_count - prev_user_count}")
print("T7b706:", "PASS" if ok else "FAIL")
results["T7b706"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b707 - sales_rep cannot create Skip wizard (ACL)")
print("=" * 72)
cand_707 = Candidate.sudo().create({
    "name": "T7b707 No ACL",
    "intended_role": "runner",
    "contact_phone": "+263771000707",
    "state": "candidate",
})
err, _r = _try(
    lambda: Wizard.with_user(u_sales).create({
        "candidate_id": cand_707.id,
        "reason": "T7b707 -- should fail",
    }))
ok = isinstance(err, AccessError)
print(f"  err class: {type(err).__name__ if err else None}")
print("T7b707:", "PASS" if ok else "FAIL")
results["T7b707"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b708 - bookkeeper cannot create Skip wizard (ACL)")
print("=" * 72)
err, _r = _try(
    lambda: Wizard.with_user(u_bookkeeper).create({
        "candidate_id": cand_707.id,
        "reason": "T7b708 -- should fail",
    }))
ok = isinstance(err, AccessError)
print(f"  err class: {type(err).__name__ if err else None}")
print("T7b708:", "PASS" if ok else "FAIL")
results["T7b708"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T7b700", "T7b701", "T7b702", "T7b703", "T7b704",
        "T7b705", "T7b706", "T7b707", "T7b708"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
