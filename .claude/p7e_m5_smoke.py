"""P7e.M5 smoke -- practical scenario + completion + signoff (9 tests)."""
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

Scenario = env["neon.lms.practical.scenario"]
Completion = env["neon.lms.scenario.completion"]
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


u_admin = _get_or_create_user(
    "p7e_m4_admin", "P7e M4 Train Admin",
    ["neon_training.group_neon_training_admin"])
u_crew_a = _get_or_create_user(
    "p7e_m5_crew_a", "P7e M5 Crew A",
    ["neon_jobs.group_neon_jobs_crew"])
u_crew_b = _get_or_create_user(
    "p7e_m5_crew_b", "P7e M5 Crew B",
    ["neon_jobs.group_neon_jobs_crew"])
u_lead_tech = _get_or_create_user(
    "p7e_m5_lead", "P7e M5 Lead Tech",
    ["neon_core.group_neon_lead_tech"])
env.cr.commit()

m08 = env.ref("neon_lms.module_m08")


# ============================================================
print()
print("T7e500 - scenario creates with required fields")
print("=" * 72)
sc1 = Scenario.sudo().create({
    "module_id": m08.id,
    "title": "Live mains discovery",
    "description": "You discover an unlabeled live cable.",
    "expected_actions": "Lockout/tagout immediately, notify lead.",
    "signoff_authority": "superuser",
})
ok = bool(sc1) and sc1.module_id == m08
print(f"  id={sc1.id} title={sc1.title}")
print("T7e500:", "PASS" if ok else "FAIL")
results["T7e500"] = ok


# ============================================================
print()
print("T7e501 - completion creates with required fields")
print("=" * 72)
comp = Completion.sudo().create({
    "learner_id": u_crew_a.id,
    "scenario_id": sc1.id,
})
ok = bool(comp) and comp.learner_id == u_crew_a
print(f"  id={comp.id} learner={comp.learner_id.login}")
print("T7e501:", "PASS" if ok else "FAIL")
results["T7e501"] = ok


# ============================================================
print()
print("T7e502 - duplicate (learner, scenario) raises")
print("=" * 72)
err, _r = _try(lambda: Completion.sudo().create({
    "learner_id": u_crew_a.id,
    "scenario_id": sc1.id,
}))
ok = err is not None and (
    "unique" in (str(err) or "").lower()
    or "duplicate" in (str(err) or "").lower())
print(f"  err: {type(err).__name__ if err else None}")
print("T7e502:", "PASS" if ok else "FAIL")
results["T7e502"] = ok


# ============================================================
print()
print("T7e503 - superuser routes to Robin + Munashe partners")
print("=" * 72)
partners = sc1._get_signoff_partners()
robin = Users.sudo().search(
    [("login", "=", "robin@neonhiring.co.zw")], limit=1)
munashe = Users.sudo().search(
    [("login", "=", "munashe@neonhiring.co.zw")], limit=1)
expected = set()
if robin:
    expected.add(robin.partner_id.id)
if munashe:
    expected.add(munashe.partner_id.id)
ok = (len(partners) >= 1
      and (expected.issubset(set(partners.ids))
           or len(partners) == 0 and len(expected) == 0))
# In test env Robin + Munashe should exist (per neon_core).
# If both exist, both must be in partners.
if robin and munashe:
    ok = (robin.partner_id in partners
          and munashe.partner_id in partners)
print(f"  partner count: {len(partners)}")
print(f"  Robin partner in result: "
      f"{robin.partner_id in partners if robin else 'N/A'}")
print(f"  Munashe partner in result: "
      f"{munashe.partner_id in partners if munashe else 'N/A'}")
print("T7e503:", "PASS" if ok else "FAIL")
results["T7e503"] = ok


# ============================================================
print()
print("T7e504 - lead_tech routes to group members")
print("=" * 72)
sc_lt = Scenario.sudo().create({
    "module_id": m08.id,
    "title": "Lead tech scenario",
    "description": "Test",
    "signoff_authority": "lead_tech",
})
lt_partners = sc_lt._get_signoff_partners()
ok = (u_lead_tech.partner_id in lt_partners)
print(f"  partner count: {len(lt_partners)}")
print(f"  u_lead_tech partner in result: "
      f"{u_lead_tech.partner_id in lt_partners}")
print("T7e504:", "PASS" if ok else "FAIL")
results["T7e504"] = ok


# ============================================================
print()
print("T7e505 - external routes to empty")
print("=" * 72)
sc_ext = Scenario.sudo().create({
    "module_id": m08.id,
    "title": "External scenario",
    "description": "Test",
    "signoff_authority": "external",
})
ext_partners = sc_ext._get_signoff_partners()
ok = len(ext_partners) == 0
print(f"  partner count: {len(ext_partners)} (expected 0)")
print("T7e505:", "PASS" if ok else "FAIL")
results["T7e505"] = ok


# ============================================================
print()
print("T7e506 - learner reads own completion")
print("=" * 72)
err, own = _try(lambda: Completion.with_user(u_crew_a).search([
    ("learner_id", "=", u_crew_a.id),
]).read(["passed"]))
ok = err is None and len(own) >= 1
print(f"  err: {err} read count: {len(own) if own else 0}")
print("T7e506:", "PASS" if ok else "FAIL")
results["T7e506"] = ok


# ============================================================
print()
print("T7e507 - learner cannot read other's completion")
print("=" * 72)
# Create completion for u_crew_b.
comp_b = Completion.sudo().create({
    "learner_id": u_crew_b.id,
    "scenario_id": sc_lt.id,
})
# u_crew_a tries to read u_crew_b's completion via search.
# Record rule filters: search returns empty, not AccessError.
visible = Completion.with_user(u_crew_a).search([
    ("learner_id", "=", u_crew_b.id),
])
ok = len(visible) == 0
print(f"  visible to crew_a: {len(visible)} (expected 0)")
print("T7e507:", "PASS" if ok else "FAIL")
results["T7e507"] = ok


# ============================================================
print()
print("T7e508 - lead_tech marks completion passed=True")
print("=" * 72)
err_w, _r = _try(
    lambda: comp_b.with_user(u_lead_tech).write({
        "passed": True,
        "signed_off_by_id": u_lead_tech.id,
    }))
comp_b.invalidate_recordset()
ok = err_w is None and comp_b.passed is True
print(f"  write err: {err_w}")
print(f"  passed after write: {comp_b.passed}")
print("T7e508:", "PASS" if ok else "FAIL")
results["T7e508"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7e500", "T7e501", "T7e502", "T7e503", "T7e504",
         "T7e505", "T7e506", "T7e507", "T7e508"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
