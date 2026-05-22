"""P7b.M2 smoke -- requirement template model + seed records
+ candidate auto-apply (6 tests).

T7b200  4 requirement templates exist after install
T7b201  each template has expected required_cert_type_ids
        count (driver:2, lead_tech:3, tech:2, runner:2)
T7b202  candidate.intended_role='driver' triggers auto-
        populate of requirement_template_id
T7b203  manual override of requirement_template_id sticks
        (readonly=False allows it)
T7b204  sales_rep cannot create requirement template
        (ACL boundary; sales_rep gets read via
        base.group_user implication but not create)
T7b205  training_admin can edit a template

Fixtures: reuse the p7b_m1_* users (idempotent get-or-create
in M1 smoke handled this). M2 doesn't add new fixtures.
"""
from odoo import fields
from odoo.exceptions import AccessError


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
Template = env["neon.onboarding.requirement.template"]

# Fixture users reuse M1's get-or-create. If user is absent
# (smoke run in isolation), recreate.
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


u_superuser = _get_or_create_user(
    "p7b_m1_superuser", "P7b M1 Superuser",
    ["neon_core.group_neon_superuser"])
u_train_admin = _get_or_create_user(
    "p7b_m1_training_admin", "P7b M1 Training Admin",
    ["neon_training.group_neon_training_admin"])
u_sales_rep = _get_or_create_user(
    "p7b_m1_sales_rep", "P7b M1 Sales Rep",
    ["neon_core.group_neon_sales_rep"])

print(f"  u_superuser   uid={u_superuser.id}")
print(f"  u_train_admin uid={u_train_admin.id}")
print(f"  u_sales_rep   uid={u_sales_rep.id}")
env.cr.commit()


# ============================================================
print()
print("=" * 72)
print("T7b200 - 4 requirement templates exist after install")
print("=" * 72)
xmlids = [
    "neon_onboarding.template_driver",
    "neon_onboarding.template_lead_tech",
    "neon_onboarding.template_tech",
    "neon_onboarding.template_runner",
]
templates = [env.ref(x, raise_if_not_found=False) for x in xmlids]
ok = all(t is not None for t in templates)
for x, t in zip(xmlids, templates):
    print(f"  {x}: {'OK id=' + str(t.id) if t else 'MISSING'}")
print("T7b200:", "PASS" if ok else "FAIL")
results["T7b200"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b201 - cert counts match expected per role")
print("=" * 72)
expected_counts = {
    "driver": 2,
    "lead_tech": 3,
    "tech": 2,
    "runner": 2,
}
counts_pass = True
for xid, role in zip(xmlids, expected_counts.keys()):
    t = env.ref(xid)
    actual = len(t.required_cert_type_ids)
    expected = expected_counts[role]
    p = actual == expected
    counts_pass = counts_pass and p
    print(f"  {role:10s} expected={expected} actual={actual} "
          f"{'OK' if p else 'FAIL'}")
print("T7b201:", "PASS" if counts_pass else "FAIL")
results["T7b201"] = counts_pass


# ============================================================
print()
print("=" * 72)
print("T7b202 - intended_role='driver' auto-applies template")
print("=" * 72)
c_202 = Candidate.with_user(u_superuser).create({
    "name": "T7b202 Auto-Template Candidate",
    "intended_role": "driver",
    "contact_phone": "+263771000202",
})
c_202.invalidate_recordset()
driver_template = env.ref("neon_onboarding.template_driver")
ok = c_202.requirement_template_id == driver_template
print(f"  requirement_template_id={c_202.requirement_template_id.name if c_202.requirement_template_id else None} "
      f"(expected: Driver Requirements)")
print("T7b202:", "PASS" if ok else "FAIL")
results["T7b202"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b203 - manual override of requirement_template_id sticks")
print("=" * 72)
# Override driver candidate's template to lead_tech template.
# readonly=False on the compute lets this through.
lead_tech_template = env.ref(
    "neon_onboarding.template_lead_tech")
c_202.with_user(u_superuser).write({
    "requirement_template_id": lead_tech_template.id,
})
c_202.invalidate_recordset()
override_stuck = (c_202.requirement_template_id
                  == lead_tech_template)
# Now if intended_role re-triggers the compute (e.g. user
# edits role), the compute would re-fire and reset. Verify
# the override doesn't get clobbered until intended_role
# changes.
c_202.flush_recordset()
c_202.invalidate_recordset()
still_lead_tech = (c_202.requirement_template_id
                   == lead_tech_template)
ok = override_stuck and still_lead_tech
print(f"  override stuck immediately: {override_stuck}  "
      f"persists after flush+invalidate: {still_lead_tech}")
print("T7b203:", "PASS" if ok else "FAIL")
results["T7b203"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b204 - sales_rep cannot create template (ACL)")
print("=" * 72)
err, _r = _try(
    lambda: Template.with_user(u_sales_rep).create({
        "name": "T7b204 should fail",
        "intended_role": "tech",
        "required_cert_type_ids": [(6, 0, [])],
    }))
# Sales rep has base.group_user (read only) -- create must
# raise AccessError. Also catch potential ValidationError
# from the partial-unique constraint if reps somehow got
# through (defensive).
ok = isinstance(err, AccessError)
print(f"  err class: {type(err).__name__ if err else None}")
print("T7b204:", "PASS" if ok else "FAIL")
results["T7b204"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b205 - training_admin can edit a template")
print("=" * 72)
runner_template = env.ref("neon_onboarding.template_runner")
prior_desc = runner_template.description
runner_template.with_user(u_train_admin).write({
    "description": "T7b205 test description -- edited by "
                   "training_admin to verify write ACL.",
})
runner_template.invalidate_recordset()
ok = "T7b205 test description" in (
    runner_template.description or "")
print(f"  description after edit: "
      f"{(runner_template.description or '')[:60]}")
# Restore to avoid polluting downstream tests.
runner_template.sudo().write({"description": prior_desc})
print("T7b205:", "PASS" if ok else "FAIL")
results["T7b205"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T7b200", "T7b201", "T7b202", "T7b203",
        "T7b204", "T7b205"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
