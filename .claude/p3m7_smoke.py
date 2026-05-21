"""P3.M7 smoke — Closeout Workflow + Client Feedback.

T127 gear_reconciled_auto computes True only when Returned +
     Closeout checklists both complete.
T128 gear_reconciled override flow: sales blocked; lead/mgr OK
     with reason; audit fields populated.
T129 finance_handoff_auto computes correctly (pending scope
     change blocks; cleared after finalisation).
T130 finance_handoff override: lead blocked; manager OK; audit
     fields populated.
T131 Hard close gate honors auto OR override: passes with either
     path; blocks when one is missing.
T132 Soft requirements don't block close: completed with hard
     reqs met + empty soft reqs → close succeeds;
     has_soft_requirements_outstanding=True.
T133 has_soft_requirements_outstanding compute: True when no
     feedback OR no lead_tech_notes; False when both present.
T134 Feedback record creation by sales; defaults to neutral
     sentiment, captured_by populated.
T135 Multi-channel feedback: 3 records w/ different channels;
     feedback_count = 3.
T136 Follow-up flag: required + owner populated; manager can
     complete via action_complete_follow_up.
T137 days_since_completed compute: 0 when not completed; computes
     correctly when state in (completed, closed).
T138 Crew tier ir.rule on feedback: sees own events' feedback,
     not others'.
T139 Migration: pre-existing client_feedback Text becomes a
     written-channel feedback record after upgrade.
"""
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

# Clean prior P3M7 fixtures
prior_jobs = env["commercial.job"].sudo().search(
    [("equipment_summary", "like", "P3M7FIX")])
env["commercial.event.feedback"].sudo().search(
    [("commercial_job_id", "in", prior_jobs.ids)]).unlink()
env["commercial.scope.change"].sudo().search(
    [("commercial_job_id", "in", prior_jobs.ids)]).unlink()
env["commercial.event.job"].sudo().search(
    [("commercial_job_id", "in", prior_jobs.ids)]).unlink()
prior_jobs.unlink()
env.cr.commit()


def _new_job_with_event(label, day_offset=60, lead_tech=None):
    J = env["commercial.job"].create({
        "partner_id": client.id, "venue_id": venue.id,
        "event_date": fields.Date.add(fields.Date.today(), days=day_offset),
        "currency_id": env.company.currency_id.id,
        "equipment_summary": "P3M7FIX " + label,
    })
    J.write({"state": "active", "soft_hold_until": False})
    EJ = J.event_job_ids[:1]
    if lead_tech:
        EJ.lead_tech_id = lead_tech.id
    return J, EJ


def _add_confirmed_crew(J, user, is_chief=False):
    existing = env["commercial.job.crew"].sudo().search(
        [("job_id", "=", J.id), ("user_id", "=", user.id)], limit=1)
    if existing:
        existing.write({"state": "confirmed", "is_crew_chief": is_chief})
    else:
        env["commercial.job.crew"].sudo().create({
            "job_id": J.id, "user_id": user.id, "role": "tech",
            "state": "confirmed", "is_crew_chief": is_chief,
        })


def _complete_checklist(EJ, ctype, user):
    """Tick every item on the given checklist as the given user."""
    cl = EJ.checklist_ids.filtered(lambda c: c.type == ctype)
    for it in cl.item_ids:
        if it.photo_required:
            it.sudo().write({"photo_required": False})
        if not it.is_checked:
            it.with_user(user).write({"is_checked": True})
    cl.invalidate_recordset()


results = {}


# ============================================================
print()
print("=" * 72)
print("T127 - gear_reconciled_auto: True only when both checklists complete")
print("=" * 72)
J127, EJ127 = _new_job_with_event("T127", 30, lead_tech=crew_leader)
EJ127.invalidate_recordset()
# Initially: no checklists complete → auto False
auto_initial = EJ127.gear_reconciled_auto
# Complete returned only
_complete_checklist(EJ127, "returned", crew_leader)
EJ127.invalidate_recordset()
auto_partial = EJ127.gear_reconciled_auto
# Complete closeout too
_complete_checklist(EJ127, "closeout", crew_leader)
EJ127.invalidate_recordset()
auto_full = EJ127.gear_reconciled_auto
ok = (auto_initial is False
      and auto_partial is False
      and auto_full is True
      and EJ127.gear_reconciled is True)
print("  auto initial:", auto_initial, "(want False)")
print("  auto after returned only:", auto_partial, "(want False)")
print("  auto after both done:", auto_full, "(want True)")
print("  effective gear_reconciled:", EJ127.gear_reconciled, "(want True)")
print("T127:", "PASS" if ok else "FAIL")
results["T127"] = ok


# ============================================================
print()
print("=" * 72)
print("T128 - gear_reconciled override flow")
print("=" * 72)
J128, EJ128 = _new_job_with_event("T128", 32, lead_tech=crew_leader)
EJ128.invalidate_recordset()
# Sales blocked
sales_blocked = False
try:
    EJ128.with_user(sales).action_override_gear_reconciled(reason="test")
except UserError:
    sales_blocked = True
# Lead succeeds
EJ128.with_user(crew_leader).action_override_gear_reconciled(
    reason="P3M7FIX T128 — sub-hire returned direct to supplier")
EJ128.invalidate_recordset()
ok = (
    sales_blocked
    and EJ128.gear_reconciled is True
    and EJ128.gear_reconciled_auto is False
    and EJ128.gear_reconciled_override_by == crew_leader
    and EJ128.gear_reconciled_override_at
    and "sub-hire" in (EJ128.gear_reconciled_override_reason or "")
)
print("  sales blocked?", sales_blocked)
print("  effective gear_reconciled:", EJ128.gear_reconciled, "(want True)")
print("  auto value:", EJ128.gear_reconciled_auto, "(want False)")
print("  override_by:", EJ128.gear_reconciled_override_by.login,
      "  override_at set?", bool(EJ128.gear_reconciled_override_at))
print("T128:", "PASS" if ok else "FAIL")
results["T128"] = ok


# ============================================================
print()
print("=" * 72)
print("T129 - finance_handoff_auto computes correctly")
print("=" * 72)
J129, EJ129 = _new_job_with_event("T129", 35, lead_tech=crew_leader)
EJ129.invalidate_recordset()
# No scope changes, no draft invoices → auto True (vacuous)
auto_clean = EJ129.finance_handoff_auto
# Add a scope_change in 'logged' state
sc = env["commercial.scope.change"].with_user(crew_leader).create({
    "event_job_id": EJ129.id,
    "description": "P3M7FIX T129 — pending review",
})
EJ129.invalidate_recordset()
auto_with_pending = EJ129.finance_handoff_auto
# Cancel the scope_change (terminal) → auto True again
sc.with_user(manager).action_cancel(reason="P3M7FIX T129 cleanup")
EJ129.invalidate_recordset()
auto_after_cancel = EJ129.finance_handoff_auto
ok = (
    auto_clean is True
    and auto_with_pending is False
    and auto_after_cancel is True
)
print("  no scope changes → auto:", auto_clean, "(want True)")
print("  pending scope change → auto:", auto_with_pending, "(want False)")
print("  after cancel (terminal) → auto:", auto_after_cancel, "(want True)")
print("T129:", "PASS" if ok else "FAIL")
results["T129"] = ok


# ============================================================
print()
print("=" * 72)
print("T130 - finance_handoff override flow")
print("=" * 72)
J130, EJ130 = _new_job_with_event("T130", 38, lead_tech=crew_leader)
# Block auto by adding a pending scope_change
sc130 = env["commercial.scope.change"].with_user(crew_leader).create({
    "event_job_id": EJ130.id,
    "description": "P3M7FIX T130 — blocks auto",
})
EJ130.invalidate_recordset()
# Lead blocked
lead_blocked = False
try:
    EJ130.with_user(crew_leader).action_override_finance_handoff(reason="test")
except UserError:
    lead_blocked = True
# Manager succeeds
EJ130.with_user(manager).action_override_finance_handoff(
    reason="P3M7FIX T130 — final invoice issued offline pending ZIMRA fix")
EJ130.invalidate_recordset()
ok = (
    lead_blocked
    and EJ130.finance_handoff_complete is True
    and EJ130.finance_handoff_auto is False
    and EJ130.finance_handoff_override_by == manager
    and EJ130.finance_handoff_override_at
    and "ZIMRA" in (EJ130.finance_handoff_override_reason or "")
)
print("  lead blocked?", lead_blocked)
print("  effective finance_handoff_complete:", EJ130.finance_handoff_complete)
print("  auto value:", EJ130.finance_handoff_auto, "(want False)")
print("  override_by:", EJ130.finance_handoff_override_by.login)
print("T130:", "PASS" if ok else "FAIL")
results["T130"] = ok


# ============================================================
print()
print("=" * 72)
print("T131 - Hard close gate honors auto OR override")
print("=" * 72)
# Two-phase: (a) gear missing + finance auto=True → close blocks on
# gear only, override gear → succeeds (proves both paths in one EJ).
# (b) finance auto=False via a pending scope_change → close blocks on
# finance, override finance → succeeds.
J131, EJ131 = _new_job_with_event("T131", 40, lead_tech=crew_leader)
_add_confirmed_crew(J131, crew_only, is_chief=True)
EJ131.invalidate_recordset()
EJ131.with_user(crew_leader).action_move_to_planning()
EJ131.with_user(crew_leader).action_move_to_prep()
EJ131.with_user(crew_leader).action_move_to_ready_for_dispatch_with_override(
    reason="P3M7FIX T131 — straight-line test")
EJ131.with_user(crew_leader).action_move_to_dispatched()
EJ131.with_user(crew_leader).with_context(
    m11_skip_gate_evaluation=True).action_move_to_in_progress()
EJ131.with_user(crew_leader).action_move_to_strike()
EJ131.with_user(crew_leader).action_move_to_returned()
EJ131.with_user(crew_leader).action_move_to_completed()
EJ131.invalidate_recordset()
# Phase A: finance auto=True (vacuous, no scope changes), gear=False.
# Close should block citing gear only.
assert EJ131.finance_handoff_auto is True, (
    "T131 setup: expected finance auto=True with no scope changes, got %s"
    % EJ131.finance_handoff_auto)
assert EJ131.gear_reconciled is False, (
    "T131 setup: expected gear=False, got %s" % EJ131.gear_reconciled)
raised_a = False
msg_a = ""
try:
    EJ131.with_user(manager).action_move_to_closed()
except UserError as e:
    raised_a = True
    msg_a = str(e)
# Override gear → close succeeds (gear via override, finance via auto)
EJ131.with_user(manager).action_override_gear_reconciled(
    reason="P3M7FIX T131A — gear via override path")
EJ131.invalidate_recordset()
EJ131.with_user(manager).action_move_to_closed()
EJ131.invalidate_recordset()

# Phase B: separate event_job with a pending scope_change blocks
# finance auto. Override finance → close succeeds.
J131B, EJ131B = _new_job_with_event("T131B", 41, lead_tech=crew_leader)
_add_confirmed_crew(J131B, crew_only, is_chief=True)
sc131 = env["commercial.scope.change"].with_user(crew_leader).create({
    "event_job_id": EJ131B.id,
    "description": "P3M7FIX T131B — pending blocks finance auto",
})
EJ131B.with_user(crew_leader).action_move_to_planning()
EJ131B.with_user(crew_leader).action_move_to_prep()
EJ131B.with_user(crew_leader).action_move_to_ready_for_dispatch_with_override(
    reason="P3M7FIX T131B")
EJ131B.with_user(crew_leader).action_move_to_dispatched()
EJ131B.with_user(crew_leader).with_context(
    m11_skip_gate_evaluation=True).action_move_to_in_progress()
EJ131B.with_user(crew_leader).action_move_to_strike()
EJ131B.with_user(crew_leader).action_move_to_returned()
EJ131B.with_user(crew_leader).action_move_to_completed()
EJ131B.invalidate_recordset()
assert EJ131B.finance_handoff_auto is False, (
    "T131B setup: expected finance auto=False with pending scope_change, got %s"
    % EJ131B.finance_handoff_auto)
# Override gear (no checklists complete on this fixture event either)
EJ131B.with_user(manager).action_override_gear_reconciled(
    reason="P3M7FIX T131B gear")
EJ131B.invalidate_recordset()
raised_b = False
msg_b = ""
try:
    EJ131B.with_user(manager).action_move_to_closed()
except UserError as e:
    raised_b = True
    msg_b = str(e)
EJ131B.with_user(manager).action_override_finance_handoff(
    reason="P3M7FIX T131B — finance via override path")
EJ131B.invalidate_recordset()
EJ131B.with_user(manager).action_move_to_closed()
EJ131B.invalidate_recordset()

ok = (
    raised_a
    and "Gear Reconciled" in msg_a
    and "Finance Handoff" not in msg_a
    and EJ131.state == "closed"
    and raised_b
    and "Finance Handoff" in msg_b
    and "Gear Reconciled" not in msg_b
    and EJ131B.state == "closed"
)
print("  Phase A: gear missing + finance auto=True")
print("    block raised?", raised_a,
      " (gear in msg:", "Gear Reconciled" in msg_a,
      ", finance NOT in msg:", "Finance Handoff" not in msg_a, ")")
print("    after gear override, state:", EJ131.state, "(want closed)")
print("  Phase B: gear via override + finance auto=False (pending scope)")
print("    block raised?", raised_b,
      " (finance in msg:", "Finance Handoff" in msg_b,
      ", gear NOT in msg:", "Gear Reconciled" not in msg_b, ")")
print("    after finance override, state:", EJ131B.state, "(want closed)")
print("T131:", "PASS" if ok else "FAIL")
results["T131"] = ok


# ============================================================
print()
print("=" * 72)
print("T132 - Soft requirements don't block close")
print("=" * 72)
J132, EJ132 = _new_job_with_event("T132", 42, lead_tech=crew_leader)
_add_confirmed_crew(J132, crew_only, is_chief=True)
EJ132.invalidate_recordset()
EJ132.with_user(crew_leader).action_move_to_planning()
EJ132.with_user(crew_leader).action_move_to_prep()
EJ132.with_user(crew_leader).action_move_to_ready_for_dispatch_with_override(
    reason="P3M7FIX T132 straight-line")
EJ132.with_user(crew_leader).action_move_to_dispatched()
EJ132.with_user(crew_leader).with_context(
    m11_skip_gate_evaluation=True).action_move_to_in_progress()
EJ132.with_user(crew_leader).action_move_to_strike()
EJ132.with_user(crew_leader).action_move_to_returned()
EJ132.with_user(crew_leader).action_move_to_completed()
# Mark gear via override; finance_handoff_auto is True vacuously
# (no scope_changes, no draft invoices) so no override needed there.
EJ132.with_user(manager).action_override_gear_reconciled(reason="T132 gear")
EJ132.invalidate_recordset()
assert EJ132.gear_reconciled and EJ132.finance_handoff_complete, (
    "T132 setup: hard reqs not satisfied — gear=%s, finance=%s"
    % (EJ132.gear_reconciled, EJ132.finance_handoff_complete))
# soft outstanding before close
soft_before = EJ132.has_soft_requirements_outstanding
# Close succeeds despite empty soft reqs
EJ132.with_user(manager).action_move_to_closed()
EJ132.invalidate_recordset()
soft_after = EJ132.has_soft_requirements_outstanding
ok = (
    EJ132.state == "closed"
    and soft_before is True
    and soft_after is True  # stays True even after close
)
print("  state after close:", EJ132.state)
print("  has_soft_requirements_outstanding before close:", soft_before)
print("  has_soft_requirements_outstanding after close:", soft_after,
      "(stays True — flags P3.M8 queue)")
print("T132:", "PASS" if ok else "FAIL")
results["T132"] = ok


# ============================================================
print()
print("=" * 72)
print("T133 - has_soft_requirements_outstanding compute")
print("=" * 72)
J133, EJ133 = _new_job_with_event("T133", 45, lead_tech=crew_leader)
EJ133.invalidate_recordset()
# Initial: no feedback, no notes → True
no_either = EJ133.has_soft_requirements_outstanding
# Add lead_tech_notes only → still True (no feedback)
EJ133.lead_tech_notes = "P3M7FIX T133 — handled cleanly"
EJ133.invalidate_recordset()
notes_only = EJ133.has_soft_requirements_outstanding
# Add a feedback record → now both present → False
env["commercial.event.feedback"].with_user(sales).create({
    "event_job_id": EJ133.id,
    "channel": "phone",
    "feedback_text": "P3M7FIX T133 — client was thrilled",
    "sentiment": "positive",
})
EJ133.invalidate_recordset()
both_present = EJ133.has_soft_requirements_outstanding
ok = (
    no_either is True
    and notes_only is True
    and both_present is False
)
print("  no feedback + no notes:", no_either, "(want True)")
print("  notes only:", notes_only, "(want True)")
print("  notes + feedback:", both_present, "(want False)")
print("T133:", "PASS" if ok else "FAIL")
results["T133"] = ok


# ============================================================
print()
print("=" * 72)
print("T134 - Feedback record creation by sales")
print("=" * 72)
J134, EJ134 = _new_job_with_event("T134", 48, lead_tech=crew_leader)
fb = env["commercial.event.feedback"].with_user(sales).create({
    "event_job_id": EJ134.id,
    "channel": "phone",
    "feedback_text": "Client was happy with the lighting design",
})
fb.invalidate_recordset()
ok = (
    fb.captured_by == sales
    and fb.sentiment == "neutral"
    and fb.channel == "phone"
    and fb.name.startswith("FB-")
    and fb.partner_id == EJ134.partner_id
)
print("  captured_by:", fb.captured_by.login)
print("  sentiment default:", fb.sentiment, "(want neutral)")
print("  channel:", fb.channel)
print("  name:", fb.name)
print("  partner_id propagated:", fb.partner_id == EJ134.partner_id)
print("T134:", "PASS" if ok else "FAIL")
results["T134"] = ok


# ============================================================
print()
print("=" * 72)
print("T135 - Multi-channel feedback (3 records, count compute)")
print("=" * 72)
J135, EJ135 = _new_job_with_event("T135", 50, lead_tech=crew_leader)
for ch in ("email_survey", "phone", "in_person"):
    env["commercial.event.feedback"].with_user(sales).create({
        "event_job_id": EJ135.id,
        "channel": ch,
        "feedback_text": "P3M7FIX T135 — %s channel feedback" % ch,
    })
EJ135.invalidate_recordset()
EJ135._compute_feedback_count()
channels = sorted(EJ135.feedback_ids.mapped("channel"))
ok = (
    EJ135.feedback_count == 3
    and channels == ["email_survey", "in_person", "phone"]
)
print("  feedback_count:", EJ135.feedback_count, "(want 3)")
print("  channels:", channels)
print("T135:", "PASS" if ok else "FAIL")
results["T135"] = ok


# ============================================================
print()
print("=" * 72)
print("T136 - Follow-up flag + manager completes")
print("=" * 72)
J136, EJ136 = _new_job_with_event("T136", 52, lead_tech=crew_leader)
fb136 = env["commercial.event.feedback"].with_user(sales).create({
    "event_job_id": EJ136.id,
    "channel": "phone",
    "feedback_text": "Client unhappy — wrong colour wash on the entrance",
    "sentiment": "negative",
    "is_follow_up_required": True,
    "follow_up_owner": manager.id,
})
# Lead blocked from completing
lead_blocked = False
try:
    fb136.with_user(crew_leader).action_complete_follow_up(
        notes="Lead trying")
except UserError:
    lead_blocked = True
# Manager completes
fb136.with_user(manager).action_complete_follow_up(
    notes="P3M7FIX T136 — apology + 10% discount on next event")
fb136.invalidate_recordset()
ok = (
    lead_blocked
    and fb136.follow_up_completed is True
    and fb136.follow_up_completed_by == manager
    and fb136.follow_up_completed_at
    and "discount" in (fb136.follow_up_notes or "")
)
print("  lead blocked?", lead_blocked)
print("  follow_up_completed:", fb136.follow_up_completed)
print("  follow_up_completed_by:", fb136.follow_up_completed_by.login)
print("T136:", "PASS" if ok else "FAIL")
results["T136"] = ok


# ============================================================
print()
print("=" * 72)
print("T137 - days_since_completed compute")
print("=" * 72)
# Build an event 20 days in the past, move it to completed, check compute
J137 = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.add(fields.Date.today(), days=-20),
    "currency_id": env.company.currency_id.id,
    "equipment_summary": "P3M7FIX T137",
})
J137.write({"state": "active", "soft_hold_until": False})
EJ137 = J137.event_job_ids[:1]
EJ137.lead_tech_id = crew_leader.id
_add_confirmed_crew(J137, crew_only, is_chief=True)
EJ137.invalidate_recordset()
# Not completed yet → days = 0
not_completed_days = EJ137.days_since_completed
EJ137.with_user(crew_leader).action_move_to_planning()
EJ137.with_user(crew_leader).action_move_to_prep()
EJ137.with_user(crew_leader).action_move_to_ready_for_dispatch_with_override(
    reason="T137 fast-track")
EJ137.with_user(crew_leader).action_move_to_dispatched()
EJ137.with_user(crew_leader).with_context(
    m11_skip_gate_evaluation=True).action_move_to_in_progress()
EJ137.with_user(crew_leader).action_move_to_strike()
EJ137.with_user(crew_leader).action_move_to_returned()
EJ137.with_user(crew_leader).action_move_to_completed()
EJ137.invalidate_recordset()
completed_days = EJ137.days_since_completed
ok = (
    not_completed_days == 0
    and completed_days >= 19  # ~20, allow some tolerance
    and completed_days <= 21
)
print("  days_since_completed (draft state):", not_completed_days)
print("  days_since_completed (completed, event 20d ago):", completed_days,
      "(want ~20)")
print("T137:", "PASS" if ok else "FAIL")
results["T137"] = ok


# ============================================================
print()
print("=" * 72)
print("T138 - Crew ir.rule on feedback (own events only)")
print("=" * 72)
J138A, EJ138A = _new_job_with_event("T138A", 55, lead_tech=crew_leader)
_add_confirmed_crew(J138A, crew_only, is_chief=False)
J138B, EJ138B = _new_job_with_event("T138B", 57, lead_tech=crew_leader)
fb_A = env["commercial.event.feedback"].with_user(sales).create({
    "event_job_id": EJ138A.id, "channel": "phone",
    "feedback_text": "P3M7FIX T138 — on A (crew should see)",
})
fb_B = env["commercial.event.feedback"].with_user(sales).create({
    "event_job_id": EJ138B.id, "channel": "phone",
    "feedback_text": "P3M7FIX T138 — on B (crew should NOT see)",
})
visible_ids = env["commercial.event.feedback"].with_user(crew_only).search([]).ids
ok = fb_A.id in visible_ids and fb_B.id not in visible_ids
print("  crew sees feedback on own event A?", fb_A.id in visible_ids)
print("  crew sees feedback on event B (not assigned)?",
      fb_B.id in visible_ids, "(want False)")
print("T138:", "PASS" if ok else "FAIL")
results["T138"] = ok


# ============================================================
print()
print("=" * 72)
print("T139 - Migration: client_feedback Text → feedback record")
print("=" * 72)
# Simulate pre-upgrade state: create an event_job, write
# client_feedback Text, then call the migration script directly.
J139, EJ139 = _new_job_with_event("T139", 60, lead_tech=crew_leader)
EJ139.sudo().write({
    "client_feedback": "P3M7FIX T139 legacy feedback — venue was tight",
})
# Run the migration body
from odoo.modules.module import get_module_path
import importlib.util
mig_path = get_module_path("neon_jobs") + "/migrations/17.0.2.5.0/post-migrate.py"
spec = importlib.util.spec_from_file_location("p3m7_migrate", mig_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.migrate(env.cr, "17.0.2.5.0")
EJ139.invalidate_recordset()
migrated = env["commercial.event.feedback"].sudo().search([
    ("event_job_id", "=", EJ139.id),
    ("channel", "=", "written"),
])
ok = (
    len(migrated) == 1
    and "venue was tight" in (migrated[0].feedback_text or "")
    and migrated[0].captured_by  # whoever manager fallback resolved to
    and "P3M7 migrated" in (migrated[0].feedback_text or "")
)
# Idempotency: re-run shouldn't create another
mod.migrate(env.cr, "17.0.2.5.0")
migrated_after = env["commercial.event.feedback"].sudo().search([
    ("event_job_id", "=", EJ139.id),
    ("channel", "=", "written"),
])
ok = ok and len(migrated_after) == 1
print("  migrated feedback count:", len(migrated))
print("  feedback contains original text?",
      "venue was tight" in (migrated[0].feedback_text or "") if migrated else False)
print("  carries migration tag?",
      "P3M7 migrated" in (migrated[0].feedback_text or "") if migrated else False)
print("  idempotent (re-run keeps count at 1):", len(migrated_after) == 1)
print("T139:", "PASS" if ok else "FAIL")
results["T139"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T127", "T128", "T129", "T130", "T131", "T132", "T133",
         "T134", "T135", "T136", "T137", "T138", "T139"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
