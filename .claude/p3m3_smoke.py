"""P3.M3 smoke — Event Job state machine (12 states, tiered authority).

T78 draft → planning by sales user (with lead_tech set).
T79 planning → prep blocked for sales.
T80 planning → prep allowed for crew_leader.
T81 draft → planning blocked when lead_tech_id is empty.
T82 prep → ready_for_dispatch with readiness=0 logs warning + allows
    (P3.M4 placeholder, not yet a hard block).
T83 ready_for_dispatch → dispatched: blocked without crew_chief,
    allowed once crew_chief + lead_tech set.
T84 dispatched → in_progress: crew_chief user (not in crew_leader
    group) can trigger.
T85 cancel: manager-only.
T86 direct state write blocked; via action method works.
T87 closed gate: blocked without gear_reconciled +
    finance_handoff_complete, allowed with both.
T88 chatter audit entry posted on each transition.
T84b crew_chief transition via the EXACT browser-style invocation
    pattern: env[model].browse(id).with_user(user).action_*().
    Mirrors what the web client does on button click. Differs from
    T84 only in record-loading path (browse vs. fixture handle).
T89 lead_tech_id auto-defaults to the current crew_leader user
    (17.0.2.1.1 — dynamic group lookup, not hardcoded id).
"""
from odoo import fields
from odoo.exceptions import UserError

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

# Clean prior P3M3 fixtures
prior_jobs = env["commercial.job"].sudo().search(
    [("equipment_summary", "like", "P3M3FIX")])
env["commercial.event.job"].sudo().search(
    [("commercial_job_id", "in", prior_jobs.ids)]).unlink()
prior_jobs.unlink()
env.cr.commit()


def _new_event_job(label, day_offset=60, lead_tech=None):
    J = env["commercial.job"].create({
        "partner_id": client.id, "venue_id": venue.id,
        "event_date": fields.Date.add(fields.Date.today(), days=day_offset),
        "currency_id": env.company.currency_id.id,
        "equipment_summary": "P3M3FIX " + label,
    })
    J.write({"state": "active", "soft_hold_until": False})
    EJ = J.event_job_ids[:1]
    if lead_tech:
        EJ.lead_tech_id = lead_tech.id
    return J, EJ


results = {}

# ============================================================
print()
print("=" * 72)
print("T78 - draft → planning by sales user")
print("=" * 72)
J78, EJ78 = _new_event_job("T78", 60, lead_tech=crew_leader)
EJ78.with_user(sales).action_move_to_planning()
EJ78.invalidate_recordset()
ok = EJ78.state == "planning"
chatter_hits = EJ78.message_ids.filtered(
    lambda m: "draft" in (m.body or "") and "planning" in (m.body or ""))
print("  state after action:", EJ78.state, "(want planning)")
print("  chatter entry present?", bool(chatter_hits))
ok = ok and bool(chatter_hits)
print("T78:", "PASS" if ok else "FAIL")
results["T78"] = ok


# ============================================================
print()
print("=" * 72)
print("T79 - planning → prep blocked for sales")
print("=" * 72)
raised = False
try:
    EJ78.with_user(sales).action_move_to_prep()
except UserError as e:
    raised = True
    msg = str(e)
EJ78.invalidate_recordset()
ok = raised and EJ78.state == "planning"
print("  UserError raised?", raised)
print("  state unchanged? ", EJ78.state, "(want planning)")
print("T79:", "PASS" if ok else "FAIL")
results["T79"] = ok


# ============================================================
print()
print("=" * 72)
print("T80 - planning → prep allowed for crew_leader")
print("=" * 72)
EJ78.with_user(crew_leader).action_move_to_prep()
EJ78.invalidate_recordset()
ok = EJ78.state == "prep"
print("  state:", EJ78.state, "(want prep)")
print("T80:", "PASS" if ok else "FAIL")
results["T80"] = ok


# ============================================================
print()
print("=" * 72)
print("T81 - draft → planning blocked when lead_tech_id empty")
print("=" * 72)
J81, EJ81 = _new_event_job("T81", 70, lead_tech=None)
# 17.0.2.1.1 — lead_tech_id auto-defaults to the current crew_leader.
# T81 verifies the "no Lead Tech" gate, so explicitly clear it.
EJ81.lead_tech_id = False
raised = False
try:
    EJ81.with_user(crew_leader).action_move_to_planning()
except UserError as e:
    raised = True
    msg = str(e)
EJ81.invalidate_recordset()
ok = raised and "Lead Tech" in (msg if raised else "") and EJ81.state == "draft"
print("  UserError raised?", raised)
print("  message contains 'Lead Tech'?",
      "Lead Tech" in (msg if raised else ""))
print("  state remains draft?", EJ81.state == "draft")
print("T81:", "PASS" if ok else "FAIL")
results["T81"] = ok


# ============================================================
print()
print("=" * 72)
print("T82 - prep → ready_for_dispatch hard gate + override (P3.M4)")
print("=" * 72)
# EJ78 is in prep with a low readiness_score (sparse fixture data).
# Post-P3.M4, the regular action raises; the override path with a
# written reason succeeds and logs to chatter. This replaces the
# pre-P3.M4 placeholder "warning logged" behavior.
EJ78.invalidate_recordset()
raised_low = False
try:
    EJ78.with_user(crew_leader).action_move_to_ready_for_dispatch()
except UserError:
    raised_low = True
# Use crew_leader override so the rest of the suite continues to
# reach ready_for_dispatch and beyond.
EJ78.with_user(crew_leader).action_move_to_ready_for_dispatch_with_override(
    "P3M3 T82 — accept low score for regression test"
)
EJ78.invalidate_recordset()
override_msgs = EJ78.message_ids.filtered(
    lambda m: "Readiness Override" in (m.body or ""))
ok = (
    raised_low
    and EJ78.state == "ready_for_dispatch"
    and bool(override_msgs)
)
print("  regular action raised on low score?", raised_low)
print("  state after override:", EJ78.state, "(want ready_for_dispatch)")
print("  override chatter entry?", bool(override_msgs))
print("T82:", "PASS" if ok else "FAIL")
results["T82"] = ok


# ============================================================
print()
print("=" * 72)
print("T83 - ready_for_dispatch → dispatched: crew_chief gate")
print("=" * 72)
# EJ78 is in ready_for_dispatch. No crew_chief yet — block.
raised_no_chief = False
try:
    EJ78.with_user(crew_leader).action_move_to_dispatched()
except UserError as e:
    raised_no_chief = True
    msg = str(e)
# Now mark crew_only as crew_chief on the commercial_job
env["commercial.job.crew"].sudo().search([
    ("job_id", "=", J78.id),
]).unlink()
env["commercial.job.crew"].create({
    "job_id": J78.id, "user_id": crew_only.id,
    "role": "tech", "is_crew_chief": True, "state": "confirmed",
})
EJ78.invalidate_recordset()
# Now should succeed
EJ78.with_user(crew_leader).action_move_to_dispatched()
EJ78.invalidate_recordset()
ok = raised_no_chief and "Crew Chief" in (msg if raised_no_chief else "") and EJ78.state == "dispatched"
print("  no-chief UserError raised?", raised_no_chief)
print("  with chief, state:        ", EJ78.state, "(want dispatched)")
print("T83:", "PASS" if ok else "FAIL")
results["T83"] = ok


# ============================================================
print()
print("=" * 72)
print("T84 - dispatched → in_progress by crew_chief (not in any neon group)")
print("=" * 72)
# crew_only IS the crew_chief on EJ78. But crew_only is in
# neon_jobs_crew, NOT crew_leader/manager. They should still be able
# to move via the crew_chief_path.
EJ78.with_user(crew_only).with_context(
    m11_skip_gate_evaluation=True).action_move_to_in_progress()
EJ78.invalidate_recordset()
ok = EJ78.state == "in_progress"
print("  state after crew_chief action:", EJ78.state, "(want in_progress)")
print("T84:", "PASS" if ok else "FAIL")
results["T84"] = ok


# ============================================================
print()
print("=" * 72)
print("T84b - crew_chief transition via the EXACT browser-style call")
print("=" * 72)
# Build a fresh fixture (NEW DB rows, separate from EJ78's walk) to
# rule out any cross-test state contamination. Then mimic the browser
# RPC pattern: browse the record by id, with_user the crew_chief,
# call the public action method.
J84b, EJ84b = _new_event_job("T84b", 100, lead_tech=crew_leader)
EJ84b.with_user(crew_leader).action_move_to_planning()
EJ84b.with_user(crew_leader).action_move_to_prep()
# P3.M4 hard gate: sparse fixture won't reach 70. Use override.
EJ84b.with_user(crew_leader).action_move_to_ready_for_dispatch_with_override(
    "P3M3 T84b regression — sparse fixture"
)
env["commercial.job.crew"].create({
    "job_id": J84b.id, "user_id": crew_only.id,
    "role": "tech", "is_crew_chief": True, "state": "confirmed",
})
EJ84b.invalidate_recordset()
EJ84b.with_user(crew_leader).action_move_to_dispatched()
env.cr.commit()

# Now the browser-style invocation: forget the fixture handle, browse
# fresh, then with_user(crew_chief), then call.
evt_id = EJ84b.id
del EJ84b
fresh_recordset = env["commercial.event.job"].browse(evt_id).with_user(crew_only)
ok_84b = True
try:
    fresh_recordset.with_context(
        m11_skip_gate_evaluation=True).action_move_to_in_progress()
except Exception as e:
    print("  EXCEPTION:", type(e).__name__, "—", str(e)[:240])
    ok_84b = False
# Read-back via sudo (so even if state were stuck the read works)
final_state = env["commercial.event.job"].browse(evt_id).sudo().state
ok_84b = ok_84b and final_state == "in_progress"
print("  state after browser-style invocation:", final_state,
      "(want in_progress)")
print("T84b:", "PASS" if ok_84b else "FAIL")
results["T84b"] = ok_84b


# ============================================================
print()
print("=" * 72)
print("T85 - cancel: manager-only")
print("=" * 72)
J85, EJ85 = _new_event_job("T85", 80, lead_tech=crew_leader)
raised_sales = False
try:
    EJ85.with_user(sales).action_cancel_event_job()
except UserError:
    raised_sales = True
EJ85.invalidate_recordset()
state_after_sales = EJ85.state
# Manager succeeds
EJ85.with_user(manager).action_cancel_event_job()
EJ85.invalidate_recordset()
ok = raised_sales and state_after_sales == "draft" and EJ85.state == "cancelled"
print("  sales UserError raised?      ", raised_sales)
print("  state after sales attempt:   ", state_after_sales)
print("  state after manager cancel:  ", EJ85.state, "(want cancelled)")
print("T85:", "PASS" if ok else "FAIL")
results["T85"] = ok


# ============================================================
print()
print("=" * 72)
print("T86 - Direct state write blocked; via action method works")
print("=" * 72)
J86, EJ86 = _new_event_job("T86", 85, lead_tech=crew_leader)
raised_direct = False
try:
    EJ86.write({"state": "in_progress"})
except UserError:
    raised_direct = True
EJ86.invalidate_recordset()
state_after_direct = EJ86.state
# Via action method (manager has the right role for the chain)
EJ86.with_user(manager).action_move_to_planning()
EJ86.invalidate_recordset()
ok = raised_direct and state_after_direct == "draft" and EJ86.state == "planning"
print("  direct write blocked?       ", raised_direct)
print("  state after direct attempt: ", state_after_direct)
print("  via action method state:    ", EJ86.state, "(want planning)")
print("T86:", "PASS" if ok else "FAIL")
results["T86"] = ok


# ============================================================
print()
print("=" * 72)
print("T87 - closeout requirements check")
print("=" * 72)
# Set up a record at state=completed. Walk through transitions to
# reach completed, then test the closeout gate.
J87, EJ87 = _new_event_job("T87", 90, lead_tech=crew_leader)
EJ87.with_user(crew_leader).action_move_to_planning()
EJ87.with_user(crew_leader).action_move_to_prep()
# P3.M4 hard gate: sparse fixture won't reach 70. Use override.
EJ87.with_user(crew_leader).action_move_to_ready_for_dispatch_with_override(
    "P3M3 T87 regression — sparse fixture"
)
# Need crew_chief for dispatch
env["commercial.job.crew"].create({
    "job_id": J87.id, "user_id": crew_only.id,
    "role": "tech", "is_crew_chief": True, "state": "confirmed",
})
EJ87.invalidate_recordset()
EJ87.with_user(crew_leader).action_move_to_dispatched()
EJ87.with_user(crew_leader).with_context(
    m11_skip_gate_evaluation=True).action_move_to_in_progress()
EJ87.with_user(crew_leader).action_move_to_strike()
EJ87.with_user(crew_leader).action_move_to_returned()
EJ87.with_user(crew_leader).action_move_to_completed()
EJ87.invalidate_recordset()
assert EJ87.state == "completed", "fixture chain failed: %s" % EJ87.state

# Now try to close without the Booleans
raised = False
try:
    EJ87.with_user(manager).action_move_to_closed()
except UserError as e:
    raised = True
    msg = str(e)
gate_blocked = raised and "Gear Reconciled" in (msg if raised else "")

# Set gear via P3.M7 override action (gear_reconciled and
# finance_handoff_complete became readonly compute fields in
# 17.0.2.5.0 — auto OR override semantics). finance auto is True
# vacuously (no scope_changes on this fixture), so no override
# needed there; just gear.
EJ87.with_user(manager).action_override_gear_reconciled(
    reason="P3M3FIX T87 — close gate test, no actual checklists")
EJ87.invalidate_recordset()
EJ87.with_user(manager).action_move_to_closed()
EJ87.invalidate_recordset()
ok = (
    gate_blocked
    and EJ87.state == "closed"
    and bool(EJ87.closeout_completed_at)
)
print("  initial close raised UserError? ", raised)
print("  msg contains 'Gear Reconciled'? ",
      "Gear Reconciled" in (msg if raised else ""))
print("  after setting Booleans, state:  ", EJ87.state)
print("  closeout_completed_at set?      ", bool(EJ87.closeout_completed_at))
print("T87:", "PASS" if ok else "FAIL")
results["T87"] = ok


# ============================================================
print()
print("=" * 72)
print("T88 - Chatter audit entry on each transition")
print("=" * 72)
J88, EJ88 = _new_event_job("T88", 95, lead_tech=crew_leader)
EJ88.with_user(crew_leader).action_move_to_planning()
EJ88.with_user(crew_leader).action_move_to_prep()
EJ88.invalidate_recordset()
hits_to_planning = EJ88.message_ids.filtered(
    lambda m: "draft" in (m.body or "") and "planning" in (m.body or ""))
hits_to_prep = EJ88.message_ids.filtered(
    lambda m: ">" in (m.body or "") and "prep" in (m.body or ""))
ok = bool(hits_to_planning) and bool(hits_to_prep)
print("  draft→planning chatter hit?", bool(hits_to_planning))
print("  planning→prep chatter hit? ", bool(hits_to_prep))
print("T88:", "PASS" if ok else "FAIL")
results["T88"] = ok


# ============================================================
print()
print("=" * 72)
print("T89 - lead_tech_id auto-defaults to current crew_leader user")
print("=" * 72)
crew_leader_group = env.ref("neon_jobs.group_neon_jobs_crew_leader")
# Snapshot original members; we restore after the swap to keep the
# DB stable for subsequent smokes.
original_members = crew_leader_group.users
expected_default = original_members.sorted("id")[:1]
J89a = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.add(fields.Date.today(), days=100),
    "currency_id": env.company.currency_id.id,
    "equipment_summary": "P3M3FIX T89-a",
})
J89a.write({"state": "active", "soft_hold_until": False})
EJ89a = J89a.event_job_ids[:1]
case_a = EJ89a.lead_tech_id == expected_default
print("  case A — expected default user:", expected_default.login if expected_default else None)
print("  case A — auto-set lead_tech_id:", EJ89a.lead_tech_id.login or "(none)")

# Swap: drop p2m75_lead from the group, add p2m75_sales temporarily
# so we have a new "crew_leader" to pick up. Sales user is a User
# tier in our role model — adding crew_leader on top is a deliberate
# test-only contortion to validate the dynamic lookup picks the new
# person.
crew_leader_group.users = sales  # Command.set via assignment is fine here
J89b = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.add(fields.Date.today(), days=105),
    "currency_id": env.company.currency_id.id,
    "equipment_summary": "P3M3FIX T89-b",
})
J89b.write({"state": "active", "soft_hold_until": False})
EJ89b = J89b.event_job_ids[:1]
case_b = EJ89b.lead_tech_id == sales
print("  case B — after group reassign to sales,")
print("           new event_job lead_tech_id:", EJ89b.lead_tech_id.login or "(none)")

# Restore the original membership so the rest of the DB / smokes stay sane.
crew_leader_group.users = original_members
ok = case_a and case_b
print("T89:", "PASS" if ok else "FAIL")
results["T89"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T78", "T79", "T80", "T81", "T82", "T83", "T84", "T84b",
         "T85", "T86", "T87", "T88", "T89"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
