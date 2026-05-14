"""P5.M1 Sub-task A — commercial.job.crew partner_id (Q18) smoke.

T242 create with user_id only → partner_id auto-fills from user
T243 create with partner_id only (no user_id) → freelance crew record
T244 create with both, mismatched → ValidationError raised
T245 existing crew records still readable post-migration
T246 is_crew_chief requires user_id (constraint raises for freelancer chief)
T247 UNIQUE (job_id, partner_id) blocks duplicates
"""
from odoo.exceptions import ValidationError


print("=" * 72)
print("SETUP")
print("=" * 72)

sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
crew_leader = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
crew_only = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
client = env["res.partner"].search(
    [("is_company", "=", True), ("is_venue", "=", False)], limit=1)
venue = env["res.partner"].search(
    [("is_venue", "=", True), ("name", "not like", "TBD%")], limit=1)
print("users:", sales.login, manager.login, crew_leader.login, crew_only.login)
print("client:", client.name, "venue:", venue.name)

# Cleanup prior P5M1A fixtures
prior_jobs = env["commercial.job"].sudo().search(
    [("equipment_summary", "like", "P5M1A_FIX")])
env["commercial.event.job"].sudo().search(
    [("commercial_job_id", "in", prior_jobs.ids)]).unlink()
prior_jobs.unlink()
env["res.partner"].sudo().search(
    [("name", "like", "P5M1A FREELANCER")]).unlink()
env.cr.commit()


def _new_job(label):
    from odoo import fields
    J = env["commercial.job"].sudo().create({
        "partner_id": client.id, "venue_id": venue.id,
        "event_date": fields.Date.add(fields.Date.today(), days=60),
        "currency_id": env.company.currency_id.id,
        "equipment_summary": "P5M1A_FIX " + label,
    })
    return J


results = {}


# ============================================================
print()
print("=" * 72)
print("T242 - create with user_id only → partner_id auto-fills")
print("=" * 72)
J242 = _new_job("T242")
c242 = env["commercial.job.crew"].sudo().create({
    "job_id": J242.id,
    "user_id": crew_only.id,
    "role": "tech",
})
ok = (
    c242.partner_id == crew_only.partner_id
    and c242.user_id == crew_only
)
print("  partner_id:", c242.partner_id.name,
      "(want", crew_only.partner_id.name + ")")
print("  user_id:   ", c242.user_id.login)
print("T242:", "PASS" if ok else "FAIL")
results["T242"] = ok


# ============================================================
print()
print("=" * 72)
print("T243 - create freelancer (partner_id only, no user_id)")
print("=" * 72)
J243 = _new_job("T243")
freelancer = env["res.partner"].sudo().create({
    "name": "P5M1A FREELANCER Joe Khumalo",
    "is_company": False,
    "phone": "+263 77 555 0123",
})
c243 = env["commercial.job.crew"].sudo().create({
    "job_id": J243.id,
    "partner_id": freelancer.id,
    "role": "runner",
})
ok = (
    c243.partner_id == freelancer
    and not c243.user_id
)
print("  partner_id:", c243.partner_id.name)
print("  user_id:   ", c243.user_id.login if c243.user_id else "(none)")
print("T243:", "PASS" if ok else "FAIL")
results["T243"] = ok


# ============================================================
print()
print("=" * 72)
print("T244 - mismatched user_id/partner_id → ValidationError")
print("=" * 72)
J244 = _new_job("T244")
raised = False
try:
    env["commercial.job.crew"].sudo().create({
        "job_id": J244.id,
        "user_id": crew_only.id,
        "partner_id": freelancer.id,  # mismatched on purpose
        "role": "tech",
    })
except ValidationError as e:
    raised = "must refer to the same person" in str(e)
print("  ValidationError raised with expected message?", raised)
print("T244:", "PASS" if raised else "FAIL")
results["T244"] = raised


# ============================================================
print()
print("=" * 72)
print("T245 - existing crew records still readable post-migration")
print("=" * 72)
all_crew = env["commercial.job.crew"].sudo().search([])
print("  total crew records:", len(all_crew))
ok = True
unfixable = []
for c in all_crew:
    if not c.partner_id:
        ok = False
        unfixable.append(c.id)
    # Force display name to render — surfaces any error in name_get fallback
    _ = c.display_name
if not ok:
    print("  rows with NULL partner_id:", unfixable)
else:
    print("  all rows have partner_id; name_get renders cleanly")
print("T245:", "PASS" if ok else "FAIL")
results["T245"] = ok


# ============================================================
print()
print("=" * 72)
print("T246 - Crew Chief requires user_id (raises for freelancer)")
print("=" * 72)
J246 = _new_job("T246")
raised = False
try:
    env["commercial.job.crew"].sudo().create({
        "job_id": J246.id,
        "partner_id": freelancer.id,
        "role": "tech",
        "is_crew_chief": True,  # freelancer can't be chief
    })
except ValidationError as e:
    raised = "must be a registered system user" in str(e)
print("  ValidationError raised with expected message?", raised)
print("T246:", "PASS" if raised else "FAIL")
results["T246"] = raised


# ============================================================
print()
print("=" * 72)
print("T247 - UNIQUE (job_id, partner_id) blocks duplicate assignment")
print("=" * 72)
J247 = _new_job("T247")
env["commercial.job.crew"].sudo().create({
    "job_id": J247.id, "user_id": crew_only.id, "role": "tech",
})
raised = False
try:
    env["commercial.job.crew"].sudo().create({
        "job_id": J247.id, "user_id": crew_only.id, "role": "tech",
    })
except Exception as e:
    # IntegrityError wrapped as psycopg2 UniqueViolation
    raised = ("unique" in str(e).lower()
              or "already assigned" in str(e).lower())
print("  duplicate blocked?", raised)
print("T247:", "PASS" if raised else "FAIL")
results["T247"] = raised


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T242", "T243", "T244", "T245", "T246", "T247"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()  # don't persist the test fixtures into DB
