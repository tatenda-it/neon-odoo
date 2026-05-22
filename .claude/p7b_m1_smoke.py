"""P7b.M1 smoke -- neon.onboarding.candidate model + skip
wizard + audit log (6 tests).

T7b100  candidate.create produces state='candidate'
T7b101  candidate.write({'state': 'cert_collection'}) succeeds
        for superuser
T7b102  ACL boundary -- crew_existing cannot read another's
        candidate (record rule filters)
T7b103  ACL boundary -- sales_rep cannot create candidate
        (no ACL row at all)
T7b104  skip_wizard executes; state='active',
        bypass_actor_id + bypass_reason set, audit_log entry
        created
T7b105  audit_log cannot be deleted (model unlink raises
        UserError even via sudo)

Fixtures (get-or-create, password test123 per CLAUDE.md):
  p7b_m1_superuser     -- group_neon_superuser
  p7b_m1_training_admin -- group_neon_training_admin
  p7b_m1_crew_existing -- group_neon_jobs_crew, paired with
                           a candidate
  p7b_m1_sales_rep     -- group_neon_sales_rep (for T7b103
                           negative-case ACL check)
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
AuditLog = env["neon.onboarding.audit.log"]
SkipWizard = env["neon.onboarding.skip.wizard"]


def _get_or_create_user(login, name, group_xmlids):
    """Get-or-create idempotent fixture user. Adds the
    requested groups via ORM (4, id) write so implied_ids
    cascade fires. Password baked in for downstream smoke.
    """
    u = Users.sudo().search(
        [("login", "=", login)], limit=1)
    if not u:
        u = Users.sudo().create({
            "name": name,
            "login": login,
            "password": "test123",
        })
    # Ensure groups -- additive, idempotent.
    for g_xmlid in group_xmlids:
        g = env.ref(g_xmlid, raise_if_not_found=False)
        if g and u not in g.users:
            g.sudo().write({"users": [(4, u.id)]})
    return u


u_superuser = _get_or_create_user(
    "p7b_m1_superuser", "P7b M1 Superuser",
    ["neon_core.group_neon_superuser"])
u_train_admin = _get_or_create_user(
    "p7b_m1_training_admin", "P7b M1 Training Admin",
    ["neon_training.group_neon_training_admin"])
u_crew_existing = _get_or_create_user(
    "p7b_m1_crew_existing", "P7b M1 Crew Existing",
    ["neon_jobs.group_neon_jobs_crew"])
u_sales_rep = _get_or_create_user(
    "p7b_m1_sales_rep", "P7b M1 Sales Rep",
    ["neon_core.group_neon_sales_rep"])

print(f"  u_superuser     uid={u_superuser.id}")
print(f"  u_train_admin   uid={u_train_admin.id}")
print(f"  u_crew_existing uid={u_crew_existing.id}")
print(f"  u_sales_rep     uid={u_sales_rep.id}")
env.cr.commit()


# ============================================================
print()
print("=" * 72)
print("T7b100 - candidate.create produces state='candidate'")
print("=" * 72)
c_100 = Candidate.with_user(u_superuser).create({
    "name": "T7b100 Test Candidate",
    "intended_role": "runner",
    "contact_phone": "+263771000100",
})
ok = (c_100.state == "candidate"
      and c_100.intended_role == "runner"
      and c_100.contact_phone == "+263771000100"
      and bool(c_100.date_started))
print(f"  state={c_100.state} role={c_100.intended_role} "
      f"date_started_set={bool(c_100.date_started)}")
print("T7b100:", "PASS" if ok else "FAIL")
results["T7b100"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b101 - superuser write state -> cert_collection")
print("=" * 72)
c_100.with_user(u_superuser).write({"state": "cert_collection"})
ok = c_100.state == "cert_collection"
print(f"  state after write: {c_100.state}")
print("T7b101:", "PASS" if ok else "FAIL")
results["T7b101"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b102 - crew cannot read another candidate (rule)")
print("=" * 72)
# Create a candidate linked to u_crew_existing.
crew_candidate = Candidate.sudo().create({
    "name": "P7b M1 Crew Existing Candidate",
    "intended_role": "runner",
    "contact_phone": "+263771000102",
    "user_id": u_crew_existing.id,
    "state": "candidate",
})
# u_crew_existing reads OWN candidate -> ok
err_own, own_browsed = _try(
    lambda: crew_candidate.with_user(u_crew_existing).read(["name"]))
own_readable = (err_own is None)
# u_crew_existing reads c_100 (not theirs) -> should raise
# AccessError per record rule
err_other, _r = _try(
    lambda: c_100.with_user(u_crew_existing).read(["name"]))
other_blocked = isinstance(err_other, AccessError)
ok = own_readable and other_blocked
print(f"  own readable: {own_readable}  "
      f"other blocked (AccessError): {other_blocked}")
if err_other and not isinstance(err_other, AccessError):
    print(f"  unexpected err class: {type(err_other).__name__}")
print("T7b102:", "PASS" if ok else "FAIL")
results["T7b102"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b103 - sales_rep cannot create candidate (no ACL)")
print("=" * 72)
err, _r = _try(
    lambda: Candidate.with_user(u_sales_rep).create({
        "name": "T7b103 should fail",
        "intended_role": "runner",
        "contact_phone": "+263771000103",
    }))
ok = isinstance(err, AccessError)
print(f"  err class: {type(err).__name__ if err else None}")
print("T7b103:", "PASS" if ok else "FAIL")
results["T7b103"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b104 - skip_wizard -> active + bypass meta + audit")
print("=" * 72)
# crew_candidate has user_id set; skip wizard transitions
# state to active and writes audit entry.
prev_state = crew_candidate.state
wiz = SkipWizard.with_user(u_superuser).create({
    "candidate_id": crew_candidate.id,
    "reason": "Existing crew from pre-Phase-7b deploy, "
              "T7b104 smoke run.",
})
wiz.action_skip()
crew_candidate.invalidate_recordset()
audit_entries = AuditLog.sudo().search([
    ("candidate_id", "=", crew_candidate.id),
    ("action", "=", "skip_onboarding"),
])
ok = (crew_candidate.state == "active"
      and crew_candidate.bypass_actor_id == u_superuser
      and crew_candidate.bypass_reason
      and "T7b104" in crew_candidate.bypass_reason
      and bool(crew_candidate.date_activated)
      and len(audit_entries) == 1
      and audit_entries[0].previous_state == prev_state
      and audit_entries[0].new_state == "active"
      and audit_entries[0].actor_id == u_superuser)
print(f"  candidate.state={crew_candidate.state} "
      f"bypass_actor={crew_candidate.bypass_actor_id.login if crew_candidate.bypass_actor_id else None}")
print(f"  audit_entries count={len(audit_entries)}")
if audit_entries:
    print(f"  audit prev={audit_entries[0].previous_state} "
          f"new={audit_entries[0].new_state} "
          f"actor={audit_entries[0].actor_id.login}")
print("T7b104:", "PASS" if ok else "FAIL")
results["T7b104"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b105 - audit_log unlink raises UserError")
print("=" * 72)
# Even as sudo / SUPERUSER, the model.unlink() override should
# raise UserError. This catches the audit-immutability contract.
audit_to_kill = audit_entries[:1]
err, _r = _try(lambda: audit_to_kill.sudo().unlink())
ok = isinstance(err, UserError)
print(f"  err class: {type(err).__name__ if err else None}")
if err:
    print(f"  msg: {str(err)[:100]}")
print("T7b105:", "PASS" if ok else "FAIL")
results["T7b105"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T7b100", "T7b101", "T7b102", "T7b103",
        "T7b104", "T7b105"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
