"""P2.M7.7.3 smoke — deep-link defense + consolidated cleanup verification.

T42-T43: ir.rule restricts crew commercial.job reads to own crewed jobs.
T44-T45: commercial_job_action gated to user+manager+crew_leader.
T46:     Configuration sub-menu visible to manager.
T47:     Implication edges actually exist (the noupdate=1 trap).
"""
from odoo import fields
from odoo.exceptions import AccessError

print("=" * 72)
print("SETUP")
print("=" * 72)

# Resolve fresh references
crew_only = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
other_crew = env["res.users"].search([("login", "=", "p2m75_other")], limit=1)
sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
crew_leader = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)

# Ensure p2m75_other exists for T42 — recreate if missing (the
# user-recreate script only covered the 4 main test users).
if not other_crew:
    other_crew = env["res.users"].create({
        "name": "P2M75 Other Crew", "login": "p2m75_other",
        "email": "p2m75_other@test.local",
        "password": "test123",
        "groups_id": [(6, 0, [
            env.ref("base.group_user").id,
            env.ref("neon_jobs.group_neon_jobs_crew").id,
        ])],
    })
    env.cr.commit()

print("Test users:")
for u in (crew_only, other_crew, sales, manager, crew_leader):
    print("  ", u.login, " neon groups =",
          [g.name for g in u.groups_id
           if g.category_id.name == "Neon Operations"])

# Fresh fixtures
env["commercial.job.crew"].sudo().search([
    ("user_id", "in", [crew_only.id, other_crew.id]),
]).unlink()
client = env["res.partner"].search(
    [("is_company", "=", True), ("is_venue", "=", False)], limit=1)
venue = env["res.partner"].search(
    [("is_venue", "=", True), ("name", "not like", "TBD%")], limit=1)
env.cr.commit()

base_date = fields.Date.add(fields.Date.today(), days=45)
J1 = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": base_date,
    "currency_id": env.company.currency_id.id,
})
J1.write({"state": "active", "soft_hold_until": False})
env["commercial.job.crew"].create({
    "job_id": J1.id, "user_id": crew_only.id,
    "role": "tech", "state": "confirmed",
})

J2 = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.add(base_date, days=7),
    "currency_id": env.company.currency_id.id,
})
J2.write({"state": "active", "soft_hold_until": False})
env["commercial.job.crew"].create({
    "job_id": J2.id, "user_id": other_crew.id,
    "role": "tech", "state": "confirmed",
})
env.cr.commit()
print("Fixtures: J1=", J1.name, "(crew=p2m75_crew), J2=", J2.name,
      "(crew=p2m75_other)")

results = {}

# ============================================================
print()
print("=" * 72)
print("T42 - Crew cannot read commercial.job they're NOT crewed on")
print("=" * 72)
visible_to_crew = env["commercial.job"].with_user(crew_only).search([])
ok_j1_in = J1 in visible_to_crew
ok_j2_out = J2 not in visible_to_crew
# Targeted search by id — definitively triggers ir.rule filter
j2_targeted = env["commercial.job"].with_user(crew_only).search([("id", "=", J2.id)])
targeted_blocked = len(j2_targeted) == 0
# check_access_rule fires the rule explicitly (independent of cache)
try:
    env["commercial.job"].with_user(crew_only).browse(J2.id).check_access_rule("read")
    rule_blocked = False
except AccessError:
    rule_blocked = True
ok = ok_j1_in and ok_j2_out and targeted_blocked and rule_blocked
print("T42: search([]) returned", len(visible_to_crew), "jobs (want 1)")
print("     J1 in own search:        ", ok_j1_in, " (want True)")
print("     J2 absent from own search:", ok_j2_out, " (want True)")
print("     targeted search([id=J2]) empty:", targeted_blocked, " (want True)")
print("     check_access_rule('read') on J2 blocked:", rule_blocked, " (want True)")
print("T42:", "PASS" if ok else "FAIL")
results["T42"] = ok

# ============================================================
print()
print("=" * 72)
print("T43 - Crew CAN read jobs they ARE crewed on")
print("=" * 72)
try:
    j1_as_crew = env["commercial.job"].with_user(crew_only).browse(J1.id)
    name = j1_as_crew.name
    partner = j1_as_crew.partner_id.name
    ok = bool(name and partner)
    print("T43: J1.name=", name, " partner=", partner)
    print("T43:", "PASS" if ok else "FAIL")
    results["T43"] = ok
except AccessError as e:
    print("T43 FAIL: AccessError on own job — ", str(e)[:100])
    results["T43"] = False

# ============================================================
print()
print("=" * 72)
print("T44 - Crew NOT in commercial_job_action.groups_id (action-level gate)")
print("=" * 72)
# ir.actions.act_window model isn't crew-readable; inspect groups_id
# directly via sudo and assert the crew tier is not in the allowed set.
action = env.ref("neon_jobs.commercial_job_action").sudo()
crew_grp = env.ref("neon_jobs.group_neon_jobs_crew")
allowed_groups = action.groups_id
ok = crew_grp not in allowed_groups and bool(allowed_groups)
print("T44: action.groups_id =", [g.name for g in allowed_groups])
print("     crew group in allowed?", crew_grp in allowed_groups,
      " (want False)")
print("T44:", "PASS" if ok else "FAIL")
results["T44"] = ok

# ============================================================
print()
print("=" * 72)
print("T45 - commercial_job_action allows user / manager / crew_leader")
print("=" * 72)
user_grp = env.ref("neon_jobs.group_neon_jobs_user")
manager_grp = env.ref("neon_jobs.group_neon_jobs_manager")
leader_grp = env.ref("neon_jobs.group_neon_jobs_crew_leader")
needed = [user_grp, manager_grp, leader_grp]
ok = all(g in allowed_groups for g in needed)
print("T45: all three tiers in groups_id?", ok)
print("T45:", "PASS" if ok else "FAIL")
results["T45"] = ok

# ============================================================
print()
print("=" * 72)
print("T46 - Configuration sub-menu visible to manager")
print("=" * 72)
cfg_menu = env.ref("neon_jobs.menu_operations_config")
mgr_sees = env["ir.ui.menu"].with_user(manager).search([("id", "=", cfg_menu.id)])
crew_sees = env["ir.ui.menu"].with_user(crew_only).search([("id", "=", cfg_menu.id)])
ok = bool(mgr_sees) and not bool(crew_sees)
print("T46: manager sees Configuration? ", bool(mgr_sees), "(want True)")
print("     crew sees Configuration?   ", bool(crew_sees), "(want False)")
print("T46:", "PASS" if ok else "FAIL")
results["T46"] = ok

# ============================================================
print()
print("=" * 72)
print("T47 - Implication edges exist in res_groups_implied_rel")
print("=" * 72)
user_grp = env.ref("neon_jobs.group_neon_jobs_user")
manager_grp = env.ref("neon_jobs.group_neon_jobs_manager")
salesman = env.ref("sales_team.group_sale_salesman_all_leads")
sale_mgr = env.ref("sales_team.group_sale_manager")
billing = env.ref("account.group_account_invoice")

edges = {
    "neon_jobs_user → salesman_all_leads": salesman in user_grp.implied_ids,
    "neon_jobs_manager → sale_manager": sale_mgr in manager_grp.implied_ids,
    "neon_jobs_manager → account.group_account_invoice": billing in manager_grp.implied_ids,
}
ok = all(edges.values())
for k, v in edges.items():
    print("    ", k, ":", v, "(want True)")
print("T47:", "PASS" if ok else "FAIL")
results["T47"] = ok

# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T42", "T43", "T44", "T45", "T46", "T47"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
