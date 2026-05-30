"""P3.M2 smoke — Event Job field groups (v4.1 §6).

T73 Form view has 12 notebook tabs with expected fields.
T74 FINANCE tab hidden from crew_leader via groups attribute.
T75 Menu sequence is 15 (between Crew Assignments and Configuration).
T76 New placeholder fields exist on the model.
T77 crew_confirmed_count compute correct (1 confirmed of 3 assigned).
"""
import re

from odoo import fields

print("=" * 72)
print("SETUP")
print("=" * 72)

manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
crew_leader = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
crew_only = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
other_crew = env["res.users"].search([("login", "=", "p2m75_other")], limit=1)
print("users: manager=", manager.login, " leader=", crew_leader.login,
      " crew=", crew_only.login, " other_crew=", other_crew.login if other_crew else "MISSING")

results = {}


# ============================================================
print()
print("=" * 72)
print("T73 - Form has 12 notebook tabs with expected pages")
print("=" * 72)
form_view = env.ref("neon_jobs.commercial_event_job_view_form")
arch = form_view.arch
# Count <page> elements with name="page_*"
pages = re.findall(r'<page\s+[^>]*name="(page_[a-z_]+)"', arch)
# P3.M5 added page_checklists (Tab 11) between Quality and Closeout.
# P3.M6 added page_scope_changes (Tab 12) between Checklists and Closeout.
expected_pages = [
    "page_identity", "page_client", "page_venue", "page_schedule",
    "page_scope", "page_finance", "page_people", "page_equipment",
    "page_quality", "page_checklists", "page_scope_changes",
    "page_closeout",
]
missing = [p for p in expected_pages if p not in pages]
ok = (len(pages) == 12) and not missing
print("  pages found:", pages)
print("  count:", len(pages), "(want 12)")
print("  missing:", missing or "none")
print("T73:", "PASS" if ok else "FAIL")
results["T73"] = ok


# ============================================================
print()
print("=" * 72)
print("T74 - FINANCE tab hidden from crew_leader (groups attribute)")
print("=" * 72)
view_for_leader = env["commercial.event.job"].with_user(crew_leader).get_view(
    view_id=form_view.id, view_type="form",
)
arch_leader = view_for_leader["arch"]
# Odoo's get_view strips elements not allowed by user's groups.
# After rendering, FINANCE page should be absent from arch_leader.
has_finance_in_raw = "page_finance" in arch
has_finance_for_leader = "page_finance" in arch_leader
ok = has_finance_in_raw and not has_finance_for_leader
print("  page_finance in raw arch?         ", has_finance_in_raw, "(want True)")
print("  page_finance in crew_leader arch? ", has_finance_for_leader, "(want False)")
print("T74:", "PASS" if ok else "FAIL")
results["T74"] = ok


# ============================================================
print()
print("=" * 72)
print("T75 - menu_event_job sequence == 15")
print("=" * 72)
menu = env.ref("neon_jobs.menu_event_job")
ok = menu.sequence == 15
print("  menu.sequence:", menu.sequence, "(want 15)")
print("T75:", "PASS" if ok else "FAIL")
results["T75"] = ok


# ============================================================
print()
print("=" * 72)
print("T76 - New placeholder fields exist on the model")
print("=" * 72)
expected_fields = [
    "client_notes", "venue_access_notes", "parking_arrangements",
    "on_site_contact_id", "prep_start_datetime", "dispatch_datetime",
    "strike_start_datetime", "return_eta_datetime",
    "expected_attendee_count", "scope_complexity",
    "crew_total_count", "crew_confirmed_count",
    "partner_email", "partner_phone",
    "quoted_value", "deposit_received", "finance_status", "currency_id",
]
field_get = env["commercial.event.job"].fields_get(expected_fields)
missing_fields = [f for f in expected_fields if f not in field_get]
ok = not missing_fields
print("  fields requested:", len(expected_fields))
print("  fields found:    ", len(field_get))
print("  missing:         ", missing_fields or "none")
print("T76:", "PASS" if ok else "FAIL")
results["T76"] = ok


# ============================================================
print()
print("=" * 72)
print("T77 - crew_confirmed_count compute (1 confirmed of 3 assigned)")
print("=" * 72)
client = env["res.partner"].search(
    [("is_company", "=", True), ("is_venue", "=", False)], limit=1)
venue = env["res.partner"].search(
    [("is_venue", "=", True), ("name", "not like", "TBD%")], limit=1)
# Cleanup any prior P3M2 fixture
prior = env["commercial.job"].sudo().search(
    [("equipment_summary", "like", "P3M2FIX")])
env["commercial.event.job"].sudo().search(
    [("commercial_job_id", "in", prior.ids)]).unlink()
prior.unlink()
env.cr.commit()

J = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.add(fields.Date.today(), days=55),
    "currency_id": env.company.currency_id.id,
    "equipment_summary": "P3M2FIX T77 fixture",
})
J.write({"state": "active", "soft_hold_until": False})
EJ = J.event_job_ids[:1]

env["commercial.job.crew"].sudo().search([("job_id", "=", J.id)]).unlink()
env["commercial.job.crew"].create({
    "job_id": J.id, "user_id": crew_only.id,
    "role": "tech", "state": "confirmed",
})
env["commercial.job.crew"].create({
    "job_id": J.id, "user_id": other_crew.id,
    "role": "tech", "state": "pending",
})
# need a third crew with state=declined; reuse manager since smoke fixtures
# don't have a dedicated "third crew" account
env["commercial.job.crew"].create({
    "job_id": J.id, "user_id": manager.id,
    "role": "tech", "state": "declined",
})
EJ.invalidate_recordset()
total = EJ.crew_total_count
confirmed = EJ.crew_confirmed_count
ok = total == 3 and confirmed == 1
print("  crew_total_count:    ", total, "(want 3)")
print("  crew_confirmed_count:", confirmed, "(want 1)")
print("T77:", "PASS" if ok else "FAIL")
results["T77"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T73", "T74", "T75", "T76", "T77"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
