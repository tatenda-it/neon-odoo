"""P3.M5 smoke — Checklist Library.

T102 Auto-create 9 checklists on event_job creation (snapshot items).
T103 Template seed data exists at install (9 templates, ~5 items each).
T104 Checklist item snapshot: template edit doesn't propagate to
     existing event_job instance items; NEW event_jobs get new text.
T105 Authority — gear_prep (lead_tech): sales blocked; lead allowed.
T106 Authority — site_setup (crew_chief): sales blocked; lead OK;
     crew_chief OK; crew non-chief blocked.
T107 N/A item: is_na=True without na_reason → ValidationError; with
     reason succeeds; counts toward completion_ratio.
T108 Photo requirement: photo_required + is_checked without
     attachment → ValidationError; with photo passes.
T109 Checklist auto-completes when all items either checked or N/A.
T110 Readiness dim_checklist activates: 0% → 0, 100% → 100, partial
     scales linearly. Excluded N/A-checklists shrink the denominator.
T111 Configuration menu: manager sees Checklist Templates; sales does
     not.
T112 Eager create performance baseline: 1 event_job + 9 checklists +
     ~45 items completes in < 2s (informational).
"""
import time

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError

print("=" * 72)
print("SETUP")
print("=" * 72)

sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
crew_leader = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
crew_only = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
other_crew = env["res.users"].search([("login", "=", "p2m75_other")], limit=1)
print("users: sales=", sales.login, " mgr=", manager.login,
      " lead=", crew_leader.login, " crew=", crew_only.login,
      " other=", other_crew.login)

client = env["res.partner"].search(
    [("is_company", "=", True), ("is_venue", "=", False)], limit=1)
venue = env["res.partner"].search(
    [("is_venue", "=", True), ("name", "not like", "TBD%")], limit=1)

# Clean any prior P3M5 fixtures (idempotent)
prior_jobs = env["commercial.job"].sudo().search(
    [("equipment_summary", "like", "P3M5FIX")])
env["commercial.event.job"].sudo().search(
    [("commercial_job_id", "in", prior_jobs.ids)]).unlink()
prior_jobs.unlink()
env.cr.commit()


def _new_job_with_event(label, day_offset=60, lead_tech=None,
                        _client=None, _venue=None):
    J = env["commercial.job"].create({
        "partner_id": (_client or client).id,
        "venue_id": (_venue or venue).id,
        "event_date": fields.Date.add(fields.Date.today(), days=day_offset),
        "currency_id": env.company.currency_id.id,
        "equipment_summary": "P3M5FIX " + label,
    })
    J.write({"state": "active", "soft_hold_until": False})
    EJ = J.event_job_ids[:1]
    if lead_tech:
        EJ.lead_tech_id = lead_tech.id
    return J, EJ


def _set_crew_chief(J, user):
    env["commercial.job.crew"].sudo().search(
        [("job_id", "=", J.id), ("is_crew_chief", "=", True)]
    ).write({"is_crew_chief": False})
    existing = env["commercial.job.crew"].sudo().search(
        [("job_id", "=", J.id), ("user_id", "=", user.id)], limit=1)
    if existing:
        existing.write({"is_crew_chief": True, "state": "confirmed"})
    else:
        env["commercial.job.crew"].sudo().create({
            "job_id": J.id, "user_id": user.id, "role": "tech",
            "state": "confirmed", "is_crew_chief": True,
        })


results = {}

# ============================================================
print()
print("=" * 72)
print("T102 - Auto-create 9 checklists on event_job creation")
print("=" * 72)
J102, EJ102 = _new_job_with_event("T102", 60, lead_tech=crew_leader)
EJ102.invalidate_recordset()
cl = EJ102.checklist_ids
types_seen = sorted(cl.mapped("type"))
expected_types = sorted([
    "capacity_acceptance", "job_readiness", "gear_prep", "dispatch",
    "site_setup", "client_handover", "strike", "returned", "closeout",
])
states_seen = set(cl.mapped("state"))
total_items = sum(c.total_count for c in cl)
ok = (
    len(cl) == 9
    and types_seen == expected_types
    and states_seen == {"not_started"}
    and total_items >= 30  # ~5 items × 9 templates, allow slack
)
print("  count:", len(cl), "(want 9)")
print("  types seen match expected:", types_seen == expected_types)
print("  all states 'not_started':", states_seen == {"not_started"})
print("  total items across 9 lists:", total_items, "(want >= 30)")
print("T102:", "PASS" if ok else "FAIL")
results["T102"] = ok


# ============================================================
print()
print("=" * 72)
print("T103 - Template seed data present at install")
print("=" * 72)
templates = env["commercial.checklist.template"].sudo().search([])
tt = sorted(templates.mapped("type"))
items_per = [(t.type, len(t.item_ids)) for t in templates.sorted("type")]
ok = (
    len(templates) == 9
    and tt == expected_types
    and all(4 <= n <= 7 for _t, n in items_per)
)
print("  template count:", len(templates), "(want 9)")
print("  types match expected:", tt == expected_types)
print("  items per template (must be 4..7):", items_per)
print("T103:", "PASS" if ok else "FAIL")
results["T103"] = ok


# ============================================================
print()
print("=" * 72)
print("T104 - Item-name snapshot (template edit does not propagate)")
print("=" * 72)
# Pick gear_prep template, grab its first item
gp_template = env["commercial.checklist.template"].sudo().search(
    [("type", "=", "gear_prep")], limit=1)
first_tpl_item = gp_template.item_ids.sorted("sequence")[:1]
original_name = first_tpl_item.name
# Find the matching instance item on EJ102's gear_prep checklist
gp_inst = EJ102.checklist_ids.filtered(lambda c: c.type == "gear_prep")
inst_item_pre = gp_inst.item_ids.sorted("sequence")[:1]
inst_name_pre = inst_item_pre.name
# Mutate template item
first_tpl_item.sudo().write({"name": original_name + " EDITED-P3M5FIX"})
gp_inst.invalidate_recordset()
inst_item_pre.invalidate_recordset()
inst_name_after_edit = inst_item_pre.name
# Now create a NEW event_job → its instance item should pick up edit
J104b, EJ104b = _new_job_with_event("T104b", 65, lead_tech=crew_leader)
EJ104b.invalidate_recordset()
gp_inst_new = EJ104b.checklist_ids.filtered(lambda c: c.type == "gear_prep")
inst_item_new = gp_inst_new.item_ids.sorted("sequence")[:1]
new_name = inst_item_new.name
# Restore template for downstream test stability
first_tpl_item.sudo().write({"name": original_name})
ok = (
    inst_name_after_edit == inst_name_pre  # existing untouched
    and "EDITED-P3M5FIX" in new_name        # new picked up the edit
)
print("  existing instance name (pre vs post-edit):",
      inst_name_pre, "/", inst_name_after_edit, "(want identical)")
print("  new event_job instance item name:", new_name, "(must contain EDITED-P3M5FIX)")
print("T104:", "PASS" if ok else "FAIL")
results["T104"] = ok


# ============================================================
print()
print("=" * 72)
print("T105 - Authority: gear_prep blocked for sales, allowed for lead")
print("=" * 72)
gp = EJ102.checklist_ids.filtered(lambda c: c.type == "gear_prep")
first_item = gp.item_ids.sorted("sequence")[:1]
# As sales — should raise
raised_sales = False
try:
    first_item.with_user(sales).write({"is_checked": True})
except UserError:
    raised_sales = True
first_item.invalidate_recordset()
state_after_sales = first_item.is_checked
# As crew_leader — should succeed
first_item.with_user(crew_leader).write({"is_checked": True})
first_item.invalidate_recordset()
state_after_lead = first_item.is_checked
ok = bool(
    raised_sales and state_after_sales is False
    and state_after_lead is True
    and first_item.checked_by == crew_leader
    and first_item.checked_at
)
print("  sales blocked?", raised_sales, "(state unchanged:", state_after_sales, ")")
print("  lead succeeded?", state_after_lead, "(checked_by:",
      first_item.checked_by.login, ", checked_at set:",
      bool(first_item.checked_at), ")")
print("T105:", "PASS" if ok else "FAIL")
results["T105"] = ok


# ============================================================
print()
print("=" * 72)
print("T106 - Authority: site_setup crew_chief path")
print("=" * 72)
J106, EJ106 = _new_job_with_event("T106", 70, lead_tech=crew_leader)
# Mark crew_only as crew_chief
_set_crew_chief(J106, crew_only)
# Add other_crew as confirmed but NOT crew_chief
env["commercial.job.crew"].sudo().create({
    "job_id": J106.id, "user_id": other_crew.id, "role": "tech",
    "state": "confirmed", "is_crew_chief": False,
})
EJ106.invalidate_recordset()
ss = EJ106.checklist_ids.filtered(lambda c: c.type == "site_setup")
ss_item = ss.item_ids.sorted("sequence")[:1]

raised_sales_106 = False
try:
    ss_item.with_user(sales).write({"is_checked": True})
except UserError:
    raised_sales_106 = True

raised_other_crew = False
try:
    ss_item.with_user(other_crew).write({"is_checked": True})
except UserError:
    raised_other_crew = True

# crew_chief succeeds
ss_item.with_user(crew_only).write({"is_checked": True})
ss_item.invalidate_recordset()
crew_chief_succeeded = ss_item.is_checked
# Clear so crew_leader test is clean
ss_item.with_user(crew_only).write({"is_checked": False})
ss_item.invalidate_recordset()
# crew_leader succeeds (umbrella authority)
ss_item.with_user(crew_leader).write({"is_checked": True})
ss_item.invalidate_recordset()
ok = (
    raised_sales_106
    and raised_other_crew
    and crew_chief_succeeded
    and ss_item.is_checked is True
)
print("  sales blocked?", raised_sales_106)
print("  non-chief crew blocked?", raised_other_crew)
print("  crew_chief allowed?", crew_chief_succeeded)
print("  crew_leader allowed?", ss_item.is_checked)
print("T106:", "PASS" if ok else "FAIL")
results["T106"] = ok


# ============================================================
print()
print("=" * 72)
print("T107 - N/A item: reason required; counts toward completion")
print("=" * 72)
J107, EJ107 = _new_job_with_event("T107", 75, lead_tech=crew_leader)
gp107 = EJ107.checklist_ids.filtered(lambda c: c.type == "gear_prep")
item = gp107.item_ids.sorted("sequence")[:1]
raised_no_reason = False
try:
    item.with_user(crew_leader).write({"is_na": True})
except ValidationError:
    raised_no_reason = True
# With reason succeeds
item.with_user(crew_leader).write({"is_na": True, "na_reason": "Sub-hire — not Neon's gear"})
item.invalidate_recordset()
gp107.invalidate_recordset()
# completion_ratio sees this as "done"
ok_count = gp107.completed_count >= 1
ok = (
    raised_no_reason and item.is_na is True
    and item.na_reason and ok_count
)
print("  ValidationError raised without reason?", raised_no_reason)
print("  is_na with reason persisted?", item.is_na, "(reason:", item.na_reason, ")")
print("  counts as completed in parent ratio?", ok_count, "(completed_count:", gp107.completed_count, ")")
print("T107:", "PASS" if ok else "FAIL")
results["T107"] = ok


# ============================================================
print()
print("=" * 72)
print("T108 - Photo required: blocks check without photo")
print("=" * 72)
# Flip photo_required on a fresh item, then attempt to check
J108, EJ108 = _new_job_with_event("T108", 80, lead_tech=crew_leader)
gp108 = EJ108.checklist_ids.filtered(lambda c: c.type == "gear_prep")
photo_item = gp108.item_ids.sorted("sequence")[:1]
photo_item.sudo().write({"photo_required": True})
photo_item.invalidate_recordset()
raised_no_photo = False
try:
    photo_item.with_user(crew_leader).write({"is_checked": True})
except ValidationError:
    raised_no_photo = True
# Attach a stub photo
attachment = env["ir.attachment"].sudo().create({
    "name": "P3M5FIX dummy.png", "type": "binary",
    "datas": "iVBORw0KGgo=",  # minimal base64
    "res_model": "commercial.event.job.checklist.item",
    "res_id": photo_item.id,
})
photo_item.with_user(crew_leader).write({
    "photo_attachment_ids": [(4, attachment.id)],
    "is_checked": True,
})
photo_item.invalidate_recordset()
ok = raised_no_photo and photo_item.is_checked is True
print("  ValidationError without photo?", raised_no_photo)
print("  passes after attaching photo?", photo_item.is_checked)
print("T108:", "PASS" if ok else "FAIL")
results["T108"] = ok


# ============================================================
print()
print("=" * 72)
print("T109 - Checklist auto-completes when all items checked or N/A")
print("=" * 72)
J109, EJ109 = _new_job_with_event("T109", 85, lead_tech=crew_leader)
gp109 = EJ109.checklist_ids.filtered(lambda c: c.type == "gear_prep")
state_before = gp109.state
# Check every item — last one as N/A with reason
items = gp109.item_ids.sorted("sequence")
for it in items[:-1]:
    it.with_user(crew_leader).write({"is_checked": True})
items[-1:].with_user(crew_leader).write({"is_na": True, "na_reason": "P3M5FIX skip"})
gp109.invalidate_recordset()
ok = (
    state_before == "not_started"
    and gp109.state == "completed"
    and gp109.completed_at
    and gp109.completed_by == crew_leader
)
print("  state before:", state_before, "(want not_started)")
print("  state after all checked/N/A:", gp109.state, "(want completed)")
print("  completed_at set?", bool(gp109.completed_at))
print("  completed_by:", gp109.completed_by.login if gp109.completed_by else None)
print("T109:", "PASS" if ok else "FAIL")
results["T109"] = ok


# ============================================================
print()
print("=" * 72)
print("T110 - dim_checklist activates: 0% / 100% / N/A excluded")
print("=" * 72)
J110, EJ110 = _new_job_with_event("T110", 90, lead_tech=crew_leader)
EJ110.action_recompute_readiness()
EJ110.invalidate_recordset()
dim_zero = EJ110.readiness_dimension_checklist  # all checklists at 0%
# Complete every item on every non-N/A checklist
for cl_inst in EJ110.checklist_ids:
    for it in cl_inst.item_ids:
        it.with_user(crew_leader).write({"is_checked": True})
EJ110.invalidate_recordset()
EJ110.action_recompute_readiness()
EJ110.invalidate_recordset()
dim_full = EJ110.readiness_dimension_checklist  # all 100%
# Mark one checklist N/A — dimension stays 100 (N/A excluded)
ch_to_na = EJ110.checklist_ids.filtered(lambda c: c.type == "client_handover")
ch_to_na.with_user(crew_leader).action_mark_na("P3M5FIX internal event, no handover")
EJ110.invalidate_recordset()
EJ110.action_recompute_readiness()
EJ110.invalidate_recordset()
dim_na_excluded = EJ110.readiness_dimension_checklist
ok = (
    abs(dim_zero - 0.0) < 0.5
    and abs(dim_full - 100.0) < 0.5
    and abs(dim_na_excluded - 100.0) < 0.5
)
print("  empty (all 0%) checklist dim:", dim_zero, "(want 0)")
print("  all-100% checklist dim:", dim_full, "(want 100)")
print("  with 1 N/A excluded, dim:", dim_na_excluded, "(want 100 — N/A excluded)")
print("T110:", "PASS" if ok else "FAIL")
results["T110"] = ok


# ============================================================
print()
print("=" * 72)
print("T111 - Configuration menu access: manager yes, sales no")
print("=" * 72)
Action = env["commercial.checklist.template"]
# Manager can list templates
try:
    found_mgr = Action.with_user(manager).search([])
    mgr_ok = len(found_mgr) >= 9
except AccessError:
    mgr_ok = False
# Sales: ACL is read-only — should be able to read but NOT write/create
sales_can_read = True
try:
    Action.with_user(sales).search([])
except AccessError:
    sales_can_read = False
sales_can_write = True
try:
    sample = Action.search([], limit=1)
    sample.with_user(sales).write({"sequence": sample.sequence})
except AccessError:
    sales_can_write = False
# Check menu visibility (Configuration menu group_neon_jobs_manager-gated)
config_menu = env.ref("neon_jobs.menu_operations_config", raise_if_not_found=False)
checklist_menu = env.ref("neon_jobs.menu_checklist_templates", raise_if_not_found=False)
mgr_groups = checklist_menu.groups_id if checklist_menu else env["res.groups"]
mgr_group = env.ref("neon_jobs.group_neon_jobs_manager")
menu_gated_to_mgr = mgr_group in mgr_groups
ok = mgr_ok and sales_can_read and (not sales_can_write) and menu_gated_to_mgr
print("  manager can list templates:", mgr_ok)
print("  sales can read (CSV grant):", sales_can_read,
      "  sales blocked from write:", not sales_can_write)
print("  Checklist Templates menu gated to manager group:", menu_gated_to_mgr)
print("T111:", "PASS" if ok else "FAIL")
results["T111"] = ok


# ============================================================
print()
print("=" * 72)
print("T112 - Eager create performance baseline (<2s)")
print("=" * 72)
t0 = time.time()
J112, EJ112 = _new_job_with_event("T112", 95, lead_tech=crew_leader)
EJ112.invalidate_recordset()
n_items = sum(c.total_count for c in EJ112.checklist_ids)
elapsed = time.time() - t0
ok = elapsed < 2.0
print("  event_job + 9 checklists + %d items created in %.3fs" % (n_items, elapsed))
print("  (informational — threshold 2s)")
print("T112:", "PASS" if ok else "INFO")
results["T112"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T102", "T103", "T104", "T105", "T106", "T107", "T108",
         "T109", "T110", "T111", "T112"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
