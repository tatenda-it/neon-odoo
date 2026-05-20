"""P3.M1 smoke — Event Job model (operational execution layer).

T67 Auto-create on commercial.job state='active'.
T68 has_operational_scope toggle.
T69 Related fields populate / propagate from commercial.job.
T70 Crew Chief uniqueness constraint (one is_crew_chief per job).
T71 Security boundaries: sales full, crew read-only on own only.
T72 Smart button: commercial.job.action_open_event_job returns the
    correct act_window dict.
"""
from odoo import fields
from odoo.exceptions import AccessError, ValidationError

print("=" * 72)
print("SETUP")
print("=" * 72)

sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
crew_only = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
other_crew = env["res.users"].search([("login", "=", "p2m75_other")], limit=1)
print("users: sales=", sales.login, " manager=", manager.login,
      " crew=", crew_only.login, " other_crew=", other_crew.login if other_crew else "MISSING")

client = env["res.partner"].search(
    [("is_company", "=", True), ("is_venue", "=", False)], limit=1)
venue = env["res.partner"].search(
    [("is_venue", "=", True), ("name", "not like", "TBD%")], limit=1)

# Clean any prior P3M1 fixtures so each run is reproducible.
prior_jobs = env["commercial.job"].sudo().search([("name", "like", "JOB-%")])
# only nuke ones referenced as fixtures by this smoke (carry a P3M1 marker
# in the equipment_summary text)
prior_p3m1 = prior_jobs.filtered(lambda j: j.equipment_summary and "P3M1FIX" in j.equipment_summary)
env["commercial.event.job"].sudo().search(
    [("commercial_job_id", "in", prior_p3m1.ids)]).unlink()
prior_p3m1.unlink()
env.cr.commit()

results = {}

# ============================================================
print()
print("=" * 72)
print("T67 - Auto-create event_job on commercial.job state='active'")
print("=" * 72)
J = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.add(fields.Date.today(), days=60),
    "currency_id": env.company.currency_id.id,
    "equipment_summary": "P3M1FIX T67 fixture",
})
# Pre-condition: no event_job yet
assert not J.event_job_ids, "expected no event_job before activate"
J.write({"state": "active", "soft_hold_until": False})
J.invalidate_recordset()
created = J.event_job_ids
ok = (
    len(created) == 1
    and created.commercial_job_id == J
    and created.state == "draft"
    and created.has_operational_scope is True
    and created.name.startswith("EVT-")
)
print("  event_job count:    ", len(created), "(want 1)")
print("  commercial_job_id:  ", created.commercial_job_id == J)
print("  state:              ", created.state, "(want draft)")
print("  has_operational_scope:", created.has_operational_scope)
print("  name:               ", created.name)
print("T67:", "PASS" if ok else "FAIL")
results["T67"] = ok


# ============================================================
print()
print("=" * 72)
print("T68 - has_operational_scope toggle")
print("=" * 72)
EJ67 = created
EJ67.has_operational_scope = False
EJ67.invalidate_recordset()
ok = (EJ67.has_operational_scope is False) and bool(EJ67.exists())
print("  has_operational_scope after toggle:", EJ67.has_operational_scope)
print("  record still exists?              ", bool(EJ67.exists()))
print("T68:", "PASS" if ok else "FAIL")
results["T68"] = ok


# ============================================================
print()
print("=" * 72)
print("T69 - Related fields propagate from commercial.job")
print("=" * 72)
new_date = fields.Date.add(fields.Date.today(), days=90)
J.event_date = new_date
J.invalidate_recordset()
EJ67.invalidate_recordset()
ok = (
    EJ67.event_date == new_date
    and EJ67.partner_id == J.partner_id
    and EJ67.venue_id == J.venue_id
)
print("  event_date propagated?", EJ67.event_date == new_date,
      "(EJ:", EJ67.event_date, "vs J:", J.event_date, ")")
print("  partner_id propagated?", EJ67.partner_id == J.partner_id)
print("  venue_id propagated?  ", EJ67.venue_id == J.venue_id)
print("T69:", "PASS" if ok else "FAIL")
results["T69"] = ok


# ============================================================
print()
print("=" * 72)
print("T70 - Crew Chief uniqueness constraint")
print("=" * 72)
# Wipe any prior crew on this job for a clean fixture
env["commercial.job.crew"].sudo().search([("job_id", "=", J.id)]).unlink()
env["commercial.job.crew"].create({
    "job_id": J.id, "user_id": crew_only.id, "role": "tech",
    "is_crew_chief": True,
})
raised = False
try:
    env["commercial.job.crew"].create({
        "job_id": J.id, "user_id": other_crew.id, "role": "tech",
        "is_crew_chief": True,
    })
except ValidationError as e:
    raised = True
    msg = str(e)
ok = raised and "Only one Crew Chief" in msg
print("  second is_crew_chief raised?", raised)
print("  message contains expected phrase?", "Only one Crew Chief" in (msg if raised else ""))
# Verify event_job.crew_chief_id reflects the single chief
EJ67.invalidate_recordset()
chief_match = EJ67.crew_chief_id == crew_only
print("  event_job.crew_chief_id == crew_only?", chief_match)
ok = ok and chief_match
print("T70:", "PASS" if ok else "FAIL")
results["T70"] = ok


# ============================================================
print()
print("=" * 72)
print("T71 - Security boundaries (Phase F Y-aware)")
print("=" * 72)
# Phase F walkthrough Y (Robin 20 May 2026): sales-tier read on
# commercial.event.job is now scoped via ir.rule to event_jobs the
# user is salesperson for on a linked neon.finance.quote. The
# pre-Y T71 assertion "sales has full CRUD on EJ67" was incidentally
# satisfied via the over-broad neon_jobs_user fixture group. After
# Y, sales tier does NOT see event_jobs they don't own a quote on.
#
# The test fixture p2m75_sales has no quote linked to EJ67, so the
# Y rule denies read. That is the correct post-Y semantic. The
# sales-CRUD assertion is dropped; the crew-tier and unrelated-
# invisible assertions remain (Y did not touch crew rules).

# Crew user with assignment on this job — read-only
crew_read_ok = True
try:
    EJ67.with_user(crew_only).read(["name", "state"])
except AccessError as e:
    print("  crew read failed:", str(e)[:120])
    crew_read_ok = False
crew_write_blocked = False
try:
    EJ67.with_user(crew_only).write({"lead_tech_notes": "should fail"})
except AccessError:
    crew_write_blocked = True

# Crew user WITHOUT assignment — cannot see it
J2 = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.add(fields.Date.today(), days=70),
    "currency_id": env.company.currency_id.id,
    "equipment_summary": "P3M1FIX T71 other-job fixture",
})
J2.write({"state": "active", "soft_hold_until": False})
EJ_other = J2.event_job_ids
# crew_only is NOT on J2's crew list, so should not see EJ_other
unrelated_invisible = (
    EJ_other.id not in env["commercial.event.job"].with_user(crew_only).search([]).ids
)

# Y-aware: sales tier with no quote on EJ67 is denied read. The
# rule's semantic is "narrow to own-quote scope"; sales without a
# matching quote sees nothing. This is the intended Robin outcome.
sales_denied_unrelated = (
    EJ67.id not in env["commercial.event.job"].with_user(sales).search([]).ids
)

ok = (crew_read_ok and crew_write_blocked
      and unrelated_invisible and sales_denied_unrelated)
print("  crew read on own?              ", crew_read_ok)
print("  crew write blocked?            ", crew_write_blocked)
print("  unrelated event_job hidden?    ", unrelated_invisible)
print("  sales without quote -> hidden? ", sales_denied_unrelated)
print("T71:", "PASS" if ok else "FAIL")
results["T71"] = ok


# ============================================================
print()
print("=" * 72)
print("T72 - Smart button on commercial.job")
print("=" * 72)
action = J.action_open_event_job()
ok = (
    action.get("type") == "ir.actions.act_window"
    and action.get("res_model") == "commercial.event.job"
    and action.get("view_mode") == "form"
    and action.get("res_id") == EJ67.id
)
print("  type:     ", action.get("type"))
print("  res_model:", action.get("res_model"))
print("  view_mode:", action.get("view_mode"))
print("  res_id:   ", action.get("res_id"), "(want", EJ67.id, ")")
print("T72:", "PASS" if ok else "FAIL")
results["T72"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T67", "T68", "T69", "T70", "T71", "T72"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
