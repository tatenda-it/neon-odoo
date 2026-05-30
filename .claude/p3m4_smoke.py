"""P3.M4 smoke — Event Readiness Score (6 weighted dimensions,
proportional rescale, hard gate at prep → ready_for_dispatch with
manager / crew_leader override).

T90  Crew dimension with full confirmed crew → score >= 90.
T91  Crew dimension with no crew → score == 0 (not None).
T92  Schedule/Venue: future+venue+room=100, future+venue=75, past=0.
T93  Risk component new_venue: first-ever booking = 0; second = 100.
T94  Risk component new_client: first job = 0; second = 100.
T95  Proportional rescale: when Equipment + Checklist are N/A, the
     aggregate uses only the available dimensions' weights.
T96  Score >= 70 allows action_move_to_ready_for_dispatch.
T97  Score < 70 blocks non-override user with a UserError citing the
     score and threshold.
T98  Manager override path moves to ready_for_dispatch + chatter.
T99  Crew leader override path moves to ready_for_dispatch + chatter.
T100 readiness_state thresholds: 95=ready, 75=watchlist, 55=at_risk,
     30=not_ready.
T101 action_recompute_readiness picks up a finance delta.
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
      " lead=", crew_leader.login, " crew=", crew_only.login)

client = env["res.partner"].search(
    [("is_company", "=", True), ("is_venue", "=", False)], limit=1)
venue = env["res.partner"].search(
    [("is_venue", "=", True), ("name", "not like", "TBD%")], limit=1)
# Reserve a second client / venue for the "new client / new venue"
# tests — must NOT have any pre-existing commercial.jobs against
# them, so we create fresh records keyed by a marker.
fresh_client = env["res.partner"].create({
    "name": "P3M4 fresh client " + str(fields.Datetime.now()),
    "is_company": True,
})
fresh_venue = env["res.partner"].create({
    "name": "P3M4 fresh venue " + str(fields.Datetime.now()),
    "is_company": True,
    "is_venue": True,
})

# Find a room on the standard venue for T92's "+room" branch
room = env["venue.room"].search([("venue_id", "=", venue.id)], limit=1)
if not room:
    room = env["venue.room"].create({
        "name": "P3M4 Main Hall", "venue_id": venue.id,
    })

# Clean prior P3M4 fixtures
prior_jobs = env["commercial.job"].sudo().search(
    [("equipment_summary", "like", "P3M4FIX")])
env["commercial.event.job"].sudo().search(
    [("commercial_job_id", "in", prior_jobs.ids)]).unlink()
prior_jobs.unlink()
env.cr.commit()


def _new_event_job(label, day_offset=60, lead_tech=None,
                   _client=None, _venue=None, _room=None,
                   quoted_value=10000.0, equipment="P3M4FIX standard"):
    J = env["commercial.job"].create({
        "partner_id": (_client or client).id,
        "venue_id": (_venue or venue).id,
        "venue_room_id": _room.id if _room else False,
        "event_date": fields.Date.add(fields.Date.today(), days=day_offset),
        "currency_id": env.company.currency_id.id,
        "quoted_value": quoted_value,
        "equipment_summary": "P3M4FIX " + label + " " + equipment,
    })
    J.write({"state": "active", "soft_hold_until": False})
    EJ = J.event_job_ids[:1]
    if lead_tech:
        EJ.lead_tech_id = lead_tech.id
    return J, EJ


def _add_crew(J, user, role="tech", state="confirmed", is_chief=False):
    return env["commercial.job.crew"].sudo().create({
        "job_id": J.id, "user_id": user.id, "role": role,
        "state": state, "is_crew_chief": is_chief,
    })


results = {}

# ============================================================
print()
print("=" * 72)
print("T90 - Crew dimension: 3 confirmed + chief → score >= 90")
print("=" * 72)
J90, EJ90 = _new_event_job("T90", 60, lead_tech=crew_leader,
                           _room=room)
# Add 3 crew — 1 chief, all confirmed
_add_crew(J90, manager, role="lead_tech", state="confirmed", is_chief=True)
_add_crew(J90, crew_only, role="tech", state="confirmed")
_add_crew(J90, other_crew, role="tech", state="confirmed")
EJ90.invalidate_recordset()
EJ90.action_recompute_readiness()
EJ90.invalidate_recordset()
crew_score = EJ90.readiness_dimension_crew
print("  crew_total_count:    ", EJ90.crew_total_count, "(want 3)")
print("  crew_confirmed:      ", EJ90.crew_confirmed_count, "(want 3)")
print("  crew_chief_id:       ", EJ90.crew_chief_id.login if EJ90.crew_chief_id else None)
print("  readiness_dimension_crew:", crew_score, "(want >= 90)")
ok = EJ90.crew_total_count == 3 and crew_score >= 90.0
print("T90:", "PASS" if ok else "FAIL")
results["T90"] = ok


# ============================================================
print()
print("=" * 72)
print("T91 - Crew dimension: 0 crew → score == 0 (not None)")
print("=" * 72)
J91, EJ91 = _new_event_job("T91", 65, lead_tech=crew_leader, _room=room)
# No crew. dimension_crew should be 0, NOT excluded
result_crew = EJ91._compute_dim_crew()
EJ91.action_recompute_readiness()
EJ91.invalidate_recordset()
ok = (
    result_crew["score"] == 0.0
    and result_crew["score"] is not None
    and EJ91.readiness_dimension_crew == 0.0
)
print("  _compute_dim_crew score:", result_crew["score"], "(want 0.0, not None)")
print("  field readiness_dimension_crew:", EJ91.readiness_dimension_crew, "(want 0.0)")
print("T91:", "PASS" if ok else "FAIL")
results["T91"] = ok


# ============================================================
print()
print("=" * 72)
print("T92 - Schedule/Venue: future+venue+room=100, future+venue=75, past=0")
print("=" * 72)
# Case A: future + venue + room
J92a, EJ92a = _new_event_job("T92a", 30, lead_tech=crew_leader, _room=room)
sv_a = EJ92a._compute_dim_schedule_venue()
# Case B: future + venue, no room
J92b, EJ92b = _new_event_job("T92b", 30, lead_tech=crew_leader, _room=None)
sv_b = EJ92b._compute_dim_schedule_venue()
# Case C: past event_date — bypass write transition matrix (completed→...)
# by writing past date directly on a fresh job using sudo + bypass.
# Manager has authority to manually shift event_date.
J92c, EJ92c = _new_event_job("T92c", 30, lead_tech=crew_leader, _room=room)
J92c.with_user(manager).write({"event_date": fields.Date.subtract(
    fields.Date.today(), days=5)})
EJ92c.invalidate_recordset()
sv_c = EJ92c._compute_dim_schedule_venue()

print("  future + venue + room:", sv_a["score"], "(want 100.0)")
print("  future + venue, no room:", sv_b["score"], "(want 75.0)")
print("  past event_date:", sv_c["score"], "(want 0.0)")
ok = sv_a["score"] == 100.0 and sv_b["score"] == 75.0 and sv_c["score"] == 0.0
print("T92:", "PASS" if ok else "FAIL")
results["T92"] = ok


# ============================================================
print()
print("=" * 72)
print("T93 - Risk new_venue: first booking=0, subsequent=100")
print("=" * 72)
# Use fresh_venue with no prior jobs
J93a, EJ93a = _new_event_job("T93a", 40, lead_tech=crew_leader,
                             _venue=fresh_venue)
score_a, bk_a = EJ93a._risk_new_venue()
# Now create a second job at the same fresh_venue
J93b, EJ93b = _new_event_job("T93b", 50, lead_tech=crew_leader,
                             _venue=fresh_venue)
score_b, bk_b = EJ93b._risk_new_venue()
print("  first booking new_venue score:", score_a, "(want 0.0)")
print("  second booking new_venue score:", score_b, "(want 100.0)")
ok = score_a == 0.0 and score_b == 100.0
print("T93:", "PASS" if ok else "FAIL")
results["T93"] = ok


# ============================================================
print()
print("=" * 72)
print("T94 - Risk new_client: first job=0, subsequent=100")
print("=" * 72)
J94a, EJ94a = _new_event_job("T94a", 45, lead_tech=crew_leader,
                             _client=fresh_client)
score_ca, _bk = EJ94a._risk_new_client()
J94b, EJ94b = _new_event_job("T94b", 55, lead_tech=crew_leader,
                             _client=fresh_client)
score_cb, _bk = EJ94b._risk_new_client()
print("  first job for client new_client:", score_ca, "(want 0.0)")
print("  second job for client new_client:", score_cb, "(want 100.0)")
ok = score_ca == 0.0 and score_cb == 100.0
print("T94:", "PASS" if ok else "FAIL")
results["T94"] = ok


# ============================================================
print()
print("=" * 72)
print("T95 - Proportional rescale: Equipment N/A excluded (Checklist active post-P3.M5)")
print("=" * 72)
# Fresh event_job: empty equipment_summary → Equipment N/A.
# Pre-P3.M5 Checklist was also N/A and dropped out; post-P3.M5 the
# Checklist dimension activates with the 9 auto-created instances
# (all at 0% completion in a fresh fixture, so its score is 0 but
# it DOES contribute weight, shrinking the rescale).
J95, EJ95 = _new_event_job("T95", 60, lead_tech=crew_leader,
                           _venue=venue, _room=room, equipment="")
# Force equipment_summary to truly empty (the helper sets a string)
EJ95.commercial_job_id.equipment_summary = ""
EJ95.equipment_summary = ""
EJ95.action_recompute_readiness()
EJ95.invalidate_recordset()
available = EJ95.readiness_dimensions_available
print("  readiness_dimensions_available:", available)
ok_avail = (
    "Equipment" not in available
    and "Checklist" in available  # P3.M5 activates this dimension
)
# Sanity: rebuild aggregate from the visible dim values
dims = {
    "Finance": (EJ95.readiness_dimension_finance, 0.20),
    "Crew": (EJ95.readiness_dimension_crew, 0.20),
    "Schedule/Venue": (EJ95.readiness_dimension_schedule_venue, 0.15),
    "Checklist": (EJ95.readiness_dimension_checklist, 0.10),
    "Risk": (EJ95.readiness_dimension_risk, 0.10),
}
# Only count dims that are in available
avail_list = [s.strip() for s in (available or "").split(",")]
weighted = 0.0
total_w = 0.0
for label, (v, w) in dims.items():
    if label in avail_list:
        weighted += v * w
        total_w += w
expected_agg = round(weighted * (1.0 / total_w), 1) if total_w else 0.0
print("  Finance dim:", EJ95.readiness_dimension_finance)
print("  Crew dim:", EJ95.readiness_dimension_crew)
print("  Schedule/Venue dim:", EJ95.readiness_dimension_schedule_venue)
print("  Risk dim:", EJ95.readiness_dimension_risk)
print("  Equipment dim:", EJ95.readiness_dimension_equipment, "(want 0; N/A → 0 for form)")
print("  Checklist dim:", EJ95.readiness_dimension_checklist, "(want 0 — 9 fresh checklists at 0% completion)")
print("  readiness_score:", EJ95.readiness_score, "(want approx", expected_agg, ")")
ok_score = abs(EJ95.readiness_score - expected_agg) < 0.2
ok = ok_avail and ok_score
print("T95:", "PASS" if ok else "FAIL")
results["T95"] = ok


# ============================================================
print()
print("=" * 72)
print("T96 - score >= 70 → action_move_to_ready_for_dispatch succeeds")
print("=" * 72)
# Build an event_job with all dimensions confirming high → score >= 70.
# Approach: lots of confirmed crew, room locked, finance fully paid,
# established client + venue (reuse standard client/venue with prior
# jobs from earlier tests).
J96, EJ96 = _new_event_job("T96", 60, lead_tech=crew_leader,
                           _client=client, _venue=venue, _room=room,
                           quoted_value=10000.0)
J96.deposit_received = 10000.0
J96.finance_status = "deposit_pending"
J96.finance_status = "deposit_received"
J96.finance_status = "fully_paid"
# Add equipment summary so Equipment contributes 50
EJ96.commercial_job_id.equipment_summary = "P3M4FIX T96 with kit"
EJ96.equipment_summary = "P3M4FIX T96 with kit"
_add_crew(J96, manager, role="lead_tech", state="confirmed", is_chief=True)
_add_crew(J96, crew_only, role="tech", state="confirmed")
_add_crew(J96, other_crew, role="tech", state="confirmed")
EJ96.invalidate_recordset()
EJ96.action_recompute_readiness()
EJ96.invalidate_recordset()
score96 = EJ96.readiness_score
print("  readiness_score:", score96, "(need >= 70)")
EJ96.with_user(crew_leader).action_move_to_planning()
EJ96.with_user(crew_leader).action_move_to_prep()
EJ96.invalidate_recordset()
EJ96.with_user(crew_leader).action_move_to_ready_for_dispatch()
EJ96.invalidate_recordset()
ok = score96 >= 70.0 and EJ96.state == "ready_for_dispatch"
print("  state after transition:", EJ96.state, "(want ready_for_dispatch)")
print("T96:", "PASS" if ok else "FAIL")
results["T96"] = ok


# ============================================================
print()
print("=" * 72)
print("T97 - score < 70 raises UserError for non-override user")
print("=" * 72)
# Fresh event_job with sparse data — score will be low.
J97, EJ97 = _new_event_job("T97", 60, lead_tech=crew_leader,
                           _client=fresh_client, _venue=fresh_venue,
                           quoted_value=5000.0, equipment="")
EJ97.commercial_job_id.equipment_summary = ""
EJ97.equipment_summary = ""
EJ97.action_recompute_readiness()
EJ97.invalidate_recordset()
score97 = EJ97.readiness_score
print("  readiness_score:", score97, "(want < 70)")
# Walk to prep state via crew_leader
EJ97.with_user(crew_leader).action_move_to_planning()
EJ97.with_user(crew_leader).action_move_to_prep()
EJ97.invalidate_recordset()
raised = False
msg = ""
# Crew_leader has authority but score gate should still block them
try:
    EJ97.with_user(crew_leader).action_move_to_ready_for_dispatch()
except UserError as e:
    raised = True
    msg = str(e)
EJ97.invalidate_recordset()
ok = (
    score97 < 70.0
    and raised
    and "%.1f" % score97 in msg
    and "70" in msg
    and EJ97.state == "prep"
)
print("  raised UserError?", raised)
print("  msg cites score?", "%.1f" % score97 in msg)
print("  msg cites '70' threshold?", "70" in msg)
print("  state still prep?", EJ97.state)
print("T97:", "PASS" if ok else "FAIL")
results["T97"] = ok


# ============================================================
print()
print("=" * 72)
print("T98 - Manager override succeeds + chatter audit")
print("=" * 72)
# Reuse EJ97 — still in prep with score < 70
override_reason_mgr = "Client emergency, accepting risk"
EJ97.with_user(manager).action_move_to_ready_for_dispatch_with_override(
    override_reason_mgr
)
EJ97.invalidate_recordset()
chatter_hits = EJ97.message_ids.filtered(
    lambda m: "Readiness Override" in (m.body or "")
    and manager.name in (m.body or "")
    and override_reason_mgr in (m.body or "")
)
ok = EJ97.state == "ready_for_dispatch" and bool(chatter_hits)
print("  state:", EJ97.state, "(want ready_for_dispatch)")
print("  chatter override entry present?", bool(chatter_hits))
print("T98:", "PASS" if ok else "FAIL")
results["T98"] = ok


# ============================================================
print()
print("=" * 72)
print("T99 - Crew leader override succeeds + chatter audit")
print("=" * 72)
# Fresh low-score event_job for the crew_leader path
J99, EJ99 = _new_event_job("T99", 70, lead_tech=crew_leader,
                           _client=fresh_client, _venue=fresh_venue,
                           quoted_value=5000.0, equipment="")
EJ99.commercial_job_id.equipment_summary = ""
EJ99.equipment_summary = ""
EJ99.action_recompute_readiness()
EJ99.with_user(crew_leader).action_move_to_planning()
EJ99.with_user(crew_leader).action_move_to_prep()
EJ99.invalidate_recordset()
override_reason_lead = "Lead Tech accepting low score for late-add"
EJ99.with_user(crew_leader).action_move_to_ready_for_dispatch_with_override(
    override_reason_lead
)
EJ99.invalidate_recordset()
chatter_hits = EJ99.message_ids.filtered(
    lambda m: "Readiness Override" in (m.body or "")
    and crew_leader.name in (m.body or "")
    and override_reason_lead in (m.body or "")
)
ok = EJ99.state == "ready_for_dispatch" and bool(chatter_hits)
print("  state:", EJ99.state)
print("  chatter override entry present?", bool(chatter_hits))
print("T99:", "PASS" if ok else "FAIL")
results["T99"] = ok


# ============================================================
print()
print("=" * 72)
print("T100 - readiness_state thresholds")
print("=" * 72)
# Set readiness_score directly via the model attribute (we're testing
# the state derivation, not the compute path). Since readiness_state
# is computed off the same compute, we exercise it via _populate_readiness
# with a forced score input.
# Simpler: synthesize fixtures whose dimensions yield known aggregates.
# Instead of forcing, let's just call _populate_readiness then check
# the formula: aggregate >= 90 → ready, etc. We'll call a tiny inline
# function with mocked scores via monkey-patching is overkill; we
# can instead check the boundary derivation directly.

# Reuse EJ96 (which scored well) to confirm 'ready' for >= 90 if score
# qualifies, else 'watchlist'. Plus a synthetic check via the threshold
# table available on the module.
from odoo.addons.neon_jobs.models import commercial_event_job as cej_mod

def _state_for(score):
    st = "not_ready"
    for threshold, name in cej_mod._READINESS_STATE_THRESHOLDS:
        if score >= threshold:
            st = name
            break
    return st

ok = (
    _state_for(95.0) == "ready"
    and _state_for(75.0) == "watchlist"
    and _state_for(55.0) == "at_risk"
    and _state_for(30.0) == "not_ready"
)
print("  score 95 → state:", _state_for(95.0), "(want ready)")
print("  score 75 → state:", _state_for(75.0), "(want watchlist)")
print("  score 55 → state:", _state_for(55.0), "(want at_risk)")
print("  score 30 → state:", _state_for(30.0), "(want not_ready)")
print("T100:", "PASS" if ok else "FAIL")
results["T100"] = ok


# ============================================================
print()
print("=" * 72)
print("T101 - Recompute picks up a finance delta")
print("=" * 72)
J101, EJ101 = _new_event_job("T101", 60, lead_tech=crew_leader,
                             _client=client, _venue=venue, _room=room,
                             quoted_value=10000.0)
J101.deposit_received = 0.0
_add_crew(J101, manager, role="lead_tech", state="confirmed", is_chief=True)
EJ101.action_recompute_readiness()
EJ101.invalidate_recordset()
score_before = EJ101.readiness_score
fin_before = EJ101.readiness_dimension_finance
# Bump deposit and recompute
J101.deposit_received = 10000.0
EJ101.action_recompute_readiness()
EJ101.invalidate_recordset()
score_after = EJ101.readiness_score
fin_after = EJ101.readiness_dimension_finance
ok = fin_after > fin_before and score_after >= score_before
print("  finance dim before:", fin_before, " after:", fin_after, "(want after > before)")
print("  aggregate before: ", score_before, " after:", score_after, "(want after >= before)")
print("T101:", "PASS" if ok else "FAIL")
results["T101"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T90", "T91", "T92", "T93", "T94", "T95",
         "T96", "T97", "T98", "T99", "T100", "T101"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
