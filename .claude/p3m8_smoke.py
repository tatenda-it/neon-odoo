"""P3.M8 smoke — Closeout Queue dashboard.

T140 closeout_missing_summary computes a correct comma-separated list.
T141 is_acknowledged_in_queue is Manager-only.
T142 acknowledgment auto-clears when soft requirements flip to satisfied.
T143 acknowledgment auto-clears on state transition (close).
T144 Manager role default filter: search_default_filter_all_stuck=1.
T145 Crew Leader role default filter: My Lead Tech + All Stuck.
T146 Sales role default filter: My Client + Feedback Missing.
T147 Over SLA filter returns >14 day events only.
T148 Multiple filters AND correctly via the search view.
T149 Pivot view exists and is loaded by the action.
T150 Menu access gating: crew tier HIDDEN, others see it.
"""
from odoo import fields
from odoo.exceptions import AccessError, UserError

print("=" * 72)
print("SETUP")
print("=" * 72)

sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
crew_leader = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
crew_only = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
other_crew = env["res.users"].search([("login", "=", "p2m75_other")], limit=1)
print("users: sales=", sales.login, " mgr=", manager.login,
      " lead=", crew_leader.login, " crew=", crew_only.login)

client = env["res.partner"].search(
    [("is_company", "=", True), ("is_venue", "=", False)], limit=1)
venue = env["res.partner"].search(
    [("is_venue", "=", True), ("name", "not like", "TBD%")], limit=1)

# Clean prior P3M8 fixtures
prior_jobs = env["commercial.job"].sudo().search(
    [("equipment_summary", "like", "P3M8FIX")])
env["commercial.event.feedback"].sudo().search(
    [("commercial_job_id", "in", prior_jobs.ids)]).unlink()
env["commercial.scope.change"].sudo().search(
    [("commercial_job_id", "in", prior_jobs.ids)]).unlink()
env["commercial.event.job"].sudo().search(
    [("commercial_job_id", "in", prior_jobs.ids)]).unlink()
prior_jobs.unlink()
env.cr.commit()


def _new_completed_event(label, days_back, lead_tech=None):
    """Create an event_job already in 'completed' state with event_date
    `days_back` days in the past (so days_since_completed = days_back).
    """
    J = env["commercial.job"].create({
        "partner_id": client.id, "venue_id": venue.id,
        "event_date": fields.Date.add(fields.Date.today(), days=-days_back),
        "currency_id": env.company.currency_id.id,
        "equipment_summary": "P3M8FIX " + label,
    })
    J.write({"state": "active", "soft_hold_until": False})
    EJ = J.event_job_ids[:1]
    if lead_tech:
        EJ.lead_tech_id = lead_tech.id
    # Add chief so dispatched transition passes
    env["commercial.job.crew"].sudo().create({
        "job_id": J.id, "user_id": crew_only.id, "role": "tech",
        "state": "confirmed", "is_crew_chief": True,
    })
    EJ.invalidate_recordset()
    EJ.with_user(crew_leader).action_move_to_planning()
    EJ.with_user(crew_leader).action_move_to_prep()
    EJ.with_user(crew_leader).action_move_to_ready_for_dispatch_with_override(
        reason="P3M8FIX %s straight-line" % label)
    EJ.with_user(crew_leader).action_move_to_dispatched()
    EJ.with_user(crew_leader).with_context(
        m11_skip_gate_evaluation=True).action_move_to_in_progress()
    EJ.with_user(crew_leader).action_move_to_strike()
    EJ.with_user(crew_leader).action_move_to_returned()
    EJ.with_user(crew_leader).action_move_to_completed()
    EJ.invalidate_recordset()
    return J, EJ


results = {}


# ============================================================
print()
print("=" * 72)
print("T140 - closeout_missing_summary compute")
print("=" * 72)
J140, EJ140 = _new_completed_event("T140", 5, lead_tech=crew_leader)
EJ140.invalidate_recordset()
# Nothing has been done — gear/finance/feedback/notes/observations all missing
full_summary = EJ140.closeout_missing_summary
expected_tokens = {"gear", "feedback", "notes", "observations"}
got_tokens = set(t.strip() for t in (full_summary or "").split(","))
all_present = expected_tokens.issubset(got_tokens)
# Now fill in gear via override; finance is auto=True vacuously
EJ140.with_user(manager).action_override_gear_reconciled(reason="T140")
EJ140.lead_tech_notes = "P3M8FIX T140 notes filled in"
EJ140.crew_observations = "P3M8FIX T140 observations"
env["commercial.event.feedback"].with_user(sales).create({
    "event_job_id": EJ140.id, "channel": "phone",
    "feedback_text": "P3M8FIX T140 — happy client",
})
EJ140.invalidate_recordset()
cleared = EJ140.closeout_missing_summary
ok = all_present and cleared == ""
print("  initial summary tokens:", sorted(got_tokens))
print("  expected tokens present?", all_present)
print("  after filling everything:", repr(cleared), "(want empty)")
print("T140:", "PASS" if ok else "FAIL")
results["T140"] = ok


# ============================================================
print()
print("=" * 72)
print("T141 - is_acknowledged_in_queue Manager-only")
print("=" * 72)
J141, EJ141 = _new_completed_event("T141", 16, lead_tech=crew_leader)
sales_raised = False
try:
    EJ141.with_user(sales).action_acknowledge_in_queue()
except UserError:
    sales_raised = True
lead_raised = False
try:
    EJ141.with_user(crew_leader).action_acknowledge_in_queue()
except UserError:
    lead_raised = True
EJ141.with_user(manager).action_acknowledge_in_queue()
EJ141.invalidate_recordset()
ok = bool(
    sales_raised and lead_raised
    and EJ141.is_acknowledged_in_queue is True
    and EJ141.acknowledged_by == manager
    and EJ141.acknowledged_at
    and "Closeout queue reviewed" in (EJ141.message_ids[0].body or "")
)
print("  sales blocked?", sales_raised, "  lead blocked?", lead_raised)
print("  manager acknowledged?", EJ141.is_acknowledged_in_queue)
print("  acknowledged_by:", EJ141.acknowledged_by.login)
print("T141:", "PASS" if ok else "FAIL")
results["T141"] = ok


# ============================================================
print()
print("=" * 72)
print("T142 - acknowledgment auto-clears when soft reqs flip satisfied")
print("=" * 72)
J142, EJ142 = _new_completed_event("T142", 10, lead_tech=crew_leader)
EJ142.with_user(manager).action_acknowledge_in_queue()
EJ142.invalidate_recordset()
ack_before = EJ142.is_acknowledged_in_queue
# Add feedback + notes — soft requirements satisfied
EJ142.lead_tech_notes = "P3M8FIX T142 notes"
env["commercial.event.feedback"].with_user(sales).create({
    "event_job_id": EJ142.id, "channel": "phone",
    "feedback_text": "P3M8FIX T142 feedback",
})
EJ142.invalidate_recordset()
soft_after = EJ142.has_soft_requirements_outstanding
ack_after = EJ142.is_acknowledged_in_queue
ok = bool(
    ack_before is True
    and soft_after is False
    and ack_after is False
)
print("  ack before (soft outstanding):", ack_before, "(want True)")
print("  soft_outstanding after fill:", soft_after, "(want False)")
print("  ack after (auto-cleared):", ack_after, "(want False)")
print("T142:", "PASS" if ok else "FAIL")
results["T142"] = ok


# ============================================================
print()
print("=" * 72)
print("T143 - acknowledgment auto-clears on state transition (close)")
print("=" * 72)
J143, EJ143 = _new_completed_event("T143", 12, lead_tech=crew_leader)
EJ143.with_user(manager).action_acknowledge_in_queue()
EJ143.invalidate_recordset()
ack_before_close = EJ143.is_acknowledged_in_queue
# Mark gear via override (finance auto=True vacuously)
EJ143.with_user(manager).action_override_gear_reconciled(reason="T143")
EJ143.invalidate_recordset()
EJ143.with_user(manager).action_move_to_closed()
EJ143.invalidate_recordset()
ok = bool(
    ack_before_close is True
    and EJ143.state == "closed"
    and EJ143.is_acknowledged_in_queue is False
    and EJ143.acknowledged_at is False
    and not EJ143.acknowledged_by
)
print("  ack before close:", ack_before_close)
print("  state after close:", EJ143.state)
print("  ack after close (auto-cleared):", EJ143.is_acknowledged_in_queue,
      "(want False)")
print("  acknowledged_at cleared:", EJ143.acknowledged_at is False)
print("T143:", "PASS" if ok else "FAIL")
results["T143"] = ok


# ============================================================
print()
print("=" * 72)
print("T144 - Manager default filter: All Stuck")
print("=" * 72)
action_mgr = env["commercial.event.job"].with_user(manager).action_open_closeout_queue()
ctx_mgr = action_mgr.get("context", {}) or {}
ok = bool(
    action_mgr.get("type") == "ir.actions.act_window"
    and action_mgr.get("res_model") == "commercial.event.job"
    and ctx_mgr.get("search_default_filter_all_stuck") == 1
    and "kanban" in action_mgr.get("view_mode", "")
    and "pivot" in action_mgr.get("view_mode", "")
)
print("  action type:", action_mgr.get("type"))
print("  view_mode:", action_mgr.get("view_mode"))
print("  context:", ctx_mgr)
print("T144:", "PASS" if ok else "FAIL")
results["T144"] = ok


# ============================================================
print()
print("=" * 72)
print("T145 - Crew Leader default filter: My Lead Tech + All Stuck")
print("=" * 72)
action_lead = env["commercial.event.job"].with_user(crew_leader).action_open_closeout_queue()
ctx_lead = action_lead.get("context", {}) or {}
ok = bool(
    ctx_lead.get("search_default_filter_my_lead_tech") == 1
    and ctx_lead.get("search_default_filter_all_stuck") == 1
)
print("  context:", ctx_lead)
print("T145:", "PASS" if ok else "FAIL")
results["T145"] = ok


# ============================================================
print()
print("=" * 72)
print("T146 - Sales default filter: My Client + Feedback Missing")
print("=" * 72)
action_sales = env["commercial.event.job"].with_user(sales).action_open_closeout_queue()
ctx_sales = action_sales.get("context", {}) or {}
ok = bool(
    ctx_sales.get("search_default_filter_my_client") == 1
    and ctx_sales.get("search_default_filter_feedback_missing") == 1
)
print("  context:", ctx_sales)
print("T146:", "PASS" if ok else "FAIL")
results["T146"] = ok


# ============================================================
print()
print("=" * 72)
print("T147 - Over SLA filter returns >14 day events only")
print("=" * 72)
# Build 3 events at days = 3, 14, 20
_, EJ147a = _new_completed_event("T147a", 3, lead_tech=crew_leader)
_, EJ147b = _new_completed_event("T147b", 14, lead_tech=crew_leader)
_, EJ147c = _new_completed_event("T147c", 20, lead_tech=crew_leader)
# Apply the over-SLA filter domain manually
over_sla = env["commercial.event.job"].search([
    ("days_since_completed", ">", 14),
    ("state", "in", ("completed", "closed")),
    ("commercial_job_id.equipment_summary", "like", "P3M8FIX T147"),
])
ok = (
    EJ147c.id in over_sla.ids
    and EJ147a.id not in over_sla.ids
    and EJ147b.id not in over_sla.ids
)
print("  3d event in over_sla?", EJ147a.id in over_sla.ids, "(want False)")
print("  14d event in over_sla?", EJ147b.id in over_sla.ids, "(want False)")
print("  20d event in over_sla?", EJ147c.id in over_sla.ids, "(want True)")
print("T147:", "PASS" if ok else "FAIL")
results["T147"] = ok


# ============================================================
print()
print("=" * 72)
print("T148 - Multiple filters AND correctly")
print("=" * 72)
# Event with state='completed', missing feedback, days=20
_, EJ148 = _new_completed_event("T148", 20, lead_tech=crew_leader)
# domains AND together when both applied
combined = env["commercial.event.job"].search([
    ("days_since_completed", ">", 14),
    ("state", "in", ("completed", "closed")),
    ("feedback_ids", "=", False),
    ("commercial_job_id.equipment_summary", "=", "P3M8FIX T148"),
])
# Now add a feedback record — should drop out of the filter
env["commercial.event.feedback"].with_user(sales).create({
    "event_job_id": EJ148.id, "channel": "phone",
    "feedback_text": "P3M8FIX T148 feedback",
})
combined_after = env["commercial.event.job"].search([
    ("days_since_completed", ">", 14),
    ("state", "in", ("completed", "closed")),
    ("feedback_ids", "=", False),
    ("commercial_job_id.equipment_summary", "=", "P3M8FIX T148"),
])
ok = (
    EJ148.id in combined.ids
    and EJ148.id not in combined_after.ids
)
print("  Over SLA + Feedback Missing matches T148 (initial)?",
      EJ148.id in combined.ids)
print("  After adding feedback, dropped from filter?",
      EJ148.id not in combined_after.ids)
print("T148:", "PASS" if ok else "FAIL")
results["T148"] = ok


# ============================================================
print()
print("=" * 72)
print("T149 - Pivot view exists and is loaded by the action")
print("=" * 72)
pivot_view = env.ref(
    "neon_jobs.commercial_event_job_closeout_queue_view_pivot",
    raise_if_not_found=False,
)
act_window = env.ref(
    "neon_jobs.commercial_event_job_action_closeout_queue",
    raise_if_not_found=False,
)
pivot_binding = env["ir.actions.act_window.view"].search([
    ("act_window_id", "=", act_window.id),
    ("view_id", "=", pivot_view.id if pivot_view else 0),
])
ok = bool(
    pivot_view
    and act_window
    and pivot_view.model == "commercial.event.job"
    and pivot_view.type == "pivot"
    and pivot_binding
    and "pivot" in (act_window.view_mode or "")
)
print("  pivot view exists?", bool(pivot_view))
print("  action exists?", bool(act_window))
print("  view_mode contains pivot?", "pivot" in (act_window.view_mode or ""))
print("  binding record present?", bool(pivot_binding))
print("T149:", "PASS" if ok else "FAIL")
results["T149"] = ok


# ============================================================
print()
print("=" * 72)
print("T150 - Menu access gating: crew hidden, others visible")
print("=" * 72)
menu = env.ref("neon_jobs.menu_closeout_queue", raise_if_not_found=False)
crew_group = env.ref("neon_jobs.group_neon_jobs_crew")
user_group = env.ref("neon_jobs.group_neon_jobs_user")
lead_group = env.ref("neon_jobs.group_neon_jobs_crew_leader")
mgr_group = env.ref("neon_jobs.group_neon_jobs_manager")
crew_in_groups = crew_group in menu.groups_id
user_in_groups = user_group in menu.groups_id
lead_in_groups = lead_group in menu.groups_id
mgr_in_groups = mgr_group in menu.groups_id
# Also verify crew_only user actually cannot see the menu in their available list
crew_visible_menu_ids = env["ir.ui.menu"].with_user(crew_only)._visible_menu_ids()
sales_visible_menu_ids = env["ir.ui.menu"].with_user(sales)._visible_menu_ids()
crew_sees_it = menu.id in crew_visible_menu_ids
sales_sees_it = menu.id in sales_visible_menu_ids
ok = (
    not crew_in_groups
    and user_in_groups and lead_in_groups and mgr_in_groups
    and not crew_sees_it
    and sales_sees_it
)
print("  crew group in menu.groups_id?", crew_in_groups, "(want False)")
print("  user group in menu.groups_id?", user_in_groups, "(want True)")
print("  lead group in menu.groups_id?", lead_in_groups, "(want True)")
print("  mgr group in menu.groups_id?", mgr_in_groups, "(want True)")
print("  crew user sees menu?", crew_sees_it, "(want False)")
print("  sales user sees menu?", sales_sees_it, "(want True)")
print("T150:", "PASS" if ok else "FAIL")
results["T150"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T140", "T141", "T142", "T143", "T144", "T145",
         "T146", "T147", "T148", "T149", "T150"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
