"""P2.M8 smoke — Rapid Ops Override (trusted-client fast path).

T52 is_rapid_ops_eligible compute matrix.
T53 has_active_master_contract recomputes on master state changes.
T54 _evaluate_capacity_gate(bypass_soft_checks=True) — soft warnings
    auto-pass; hard rejects still block.
T55 action_rapid_activate as Sales on eligible partner — succeeds.
T56 action_rapid_activate as Sales on non-eligible partner — blocked.
T57 action_rapid_activate as Manager on non-eligible partner — succeeds.
T58 action_rapid_activate blocked on HARD reject even for eligible.
T59 can_rapid_activate computed correctness by role + state.
T60 Audit trail — gate_check_log has bypassed markers, chatter posted.
T61 is_rapid_ops_eligible_manual manager-only writeable.
T63 Banner copy: trusted-client text AND manager-override text both
    present in form arch (17.0.1.9.2 polish).
"""
import json

from odoo import fields
from odoo.exceptions import AccessError, UserError

print("=" * 72)
print("SETUP")
print("=" * 72)

sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
crew_only = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
print("Users: sales=", sales.login, " mgr=", manager.login,
      " crew=", crew_only.login)

# Fixture partners
Partner = env["res.partner"]
# clean prior smoke partners + their jobs (otherwise leftover active
# jobs at the shared test venue trip the date_venue HARD check on
# subsequent runs, which can't be bypassed and traps the aggregate
# at warning).
prior = Partner.search([("name", "like", "P2M8 ")])
env["commercial.job"].sudo().search([
    ("partner_id", "in", prior.ids),
]).unlink()
prior.write({"is_rapid_ops_eligible_manual": False})
env["commercial.job.master"].sudo().search([
    ("partner_id", "in", prior.ids),
]).unlink()
env.cr.commit()

p_manual = Partner.create({
    "name": "P2M8 Manual Trusted", "is_company": True,
})
p_master = Partner.create({
    "name": "P2M8 Master Trusted", "is_company": True,
})
p_neither = Partner.create({
    "name": "P2M8 Neither", "is_company": True,
})
p_both = Partner.create({
    "name": "P2M8 Both", "is_company": True,
})
env.cr.commit()

# manager elevates flag so the write guard fires the manager path
p_manual.with_user(manager).write({"is_rapid_ops_eligible_manual": True})
p_both.with_user(manager).write({"is_rapid_ops_eligible_manual": True})

master_for_both = env["commercial.job.master"].create({
    "title": "P2M8 Master Both", "partner_id": p_both.id, "state": "active",
})
master_for_master = env["commercial.job.master"].create({
    "title": "P2M8 Master Trusted", "partner_id": p_master.id, "state": "draft",
})
master_for_master.with_user(manager).write({"state": "active"})
env.cr.commit()

# Refresh from DB so stored computes settle
p_manual.invalidate_recordset()
p_master.invalidate_recordset()
p_neither.invalidate_recordset()
p_both.invalidate_recordset()

venue = Partner.search(
    [("is_venue", "=", True), ("name", "not like", "TBD%")], limit=1)
print("Fixture venue:", venue.name)

results = {}


# ============================================================
print()
print("=" * 72)
print("T52 - is_rapid_ops_eligible compute matrix")
print("=" * 72)
ok_manual = p_manual.is_rapid_ops_eligible is True
ok_master = p_master.is_rapid_ops_eligible is True
ok_neither = p_neither.is_rapid_ops_eligible is False
ok_both = p_both.is_rapid_ops_eligible is True
ok = ok_manual and ok_master and ok_neither and ok_both
print("  manual-only:  ", p_manual.is_rapid_ops_eligible, "(want True)")
print("  master-only:  ", p_master.is_rapid_ops_eligible, "(want True)")
print("  neither:      ", p_neither.is_rapid_ops_eligible, "(want False)")
print("  both:         ", p_both.is_rapid_ops_eligible, "(want True)")
print("T52:", "PASS" if ok else "FAIL")
results["T52"] = ok


# ============================================================
print()
print("=" * 72)
print("T53 - has_active_master_contract recomputes on master state")
print("=" * 72)
p_draft = Partner.create({"name": "P2M8 Draft Master Client", "is_company": True})
m = env["commercial.job.master"].create({
    "title": "P2M8 Draft master", "partner_id": p_draft.id, "state": "draft",
})
env.cr.commit()
p_draft.invalidate_recordset()
step1 = not p_draft.has_active_master_contract  # draft → not active
m.with_user(manager).write({"state": "active"})
p_draft.invalidate_recordset()
step2 = p_draft.has_active_master_contract  # active → eligible
m.with_user(manager).write({"state": "completed"})
p_draft.invalidate_recordset()
step3 = not p_draft.has_active_master_contract  # completed → not eligible
ok = step1 and step2 and step3
print("  draft → has_active?    ", p_draft.has_active_master_contract,
      "(want False at this step:", step1, ")")
print("  active → has_active?   step2 result:", step2, "(want True)")
print("  completed → has_active? step3 result:", step3, "(want False)")
print("T53:", "PASS" if ok else "FAIL")
results["T53"] = ok


# ============================================================
print()
print("=" * 72)
print("T54 - _evaluate_capacity_gate(bypass_soft_checks=True)")
print("=" * 72)
base_date = fields.Date.add(fields.Date.today(), days=120)
# Job with sub-hire required → soft warning expected, bypass→pass
J_soft = env["commercial.job"].create({
    "partner_id": p_neither.id, "venue_id": venue.id,
    "event_date": base_date, "sub_hire_required": True,
})
r_no_bypass = J_soft._evaluate_capacity_gate()
r_bypass = J_soft._evaluate_capacity_gate(bypass_soft_checks=True)
soft = next(c for c in r_bypass["checks"] if c["name"] == "sub_hire")
case_a = (
    r_no_bypass["aggregate"] == "warning"
    and r_bypass["aggregate"] == "pass"
    and soft["result"] == "pass"
    and soft.get("bypassed") is True
    and "RAPID_OPS_BYPASS" in soft["message"]
)
print("  no-bypass aggregate:  ", r_no_bypass["aggregate"], "(want warning)")
print("  bypass aggregate:     ", r_bypass["aggregate"], "(want pass)")
print("  sub_hire bypassed:    ", soft.get("bypassed"), "(want True)")
print("  sub_hire msg prefix:  ",
      soft["message"].split(":", 1)[0], "(want RAPID_OPS_BYPASS)")

# Build hard-reject scenario: another active job at same venue+room same date
room = env["venue.room"].search([("venue_id", "=", venue.id)], limit=1)
if not room:
    room = env["venue.room"].create({
        "venue_id": venue.id, "name": "P2M8 Test Room",
    })
hard_date = fields.Date.add(fields.Date.today(), days=130)
J_blocker = env["commercial.job"].create({
    "partner_id": p_neither.id, "venue_id": venue.id, "venue_room_id": room.id,
    "event_date": hard_date,
})
J_blocker.write({"state": "active", "soft_hold_until": False})
J_hard = env["commercial.job"].create({
    "partner_id": p_neither.id, "venue_id": venue.id, "venue_room_id": room.id,
    "event_date": hard_date,
})
r_hard = J_hard._evaluate_capacity_gate(bypass_soft_checks=True)
dv = next(c for c in r_hard["checks"] if c["name"] == "date_venue")
case_b = r_hard["aggregate"] == "reject" and dv["result"] == "reject"
print("  hard reject aggregate:", r_hard["aggregate"], "(want reject)")
print("  date_venue under bypass:", dv["result"], "(want reject)")
ok = case_a and case_b
print("T54:", "PASS" if ok else "FAIL")
results["T54"] = ok


# ============================================================
print()
print("=" * 72)
print("T55 - Sales rapid-activates eligible partner")
print("=" * 72)
J55 = env["commercial.job"].create({
    "partner_id": p_manual.id, "venue_id": venue.id,
    "event_date": fields.Date.add(fields.Date.today(), days=140),
    "sub_hire_required": True,  # soft warning
})
try:
    J55.with_user(sales).action_rapid_activate()
    J55.invalidate_recordset()
    success = J55.state == "active" and J55.gate_result == "pass"
except (UserError, AccessError) as e:
    print("  unexpected error:", str(e)[:120])
    success = False
chatter = J55.message_ids.filtered(
    lambda m: "Rapid Ops Activation" in (m.body or ""))
ok = success and bool(chatter)
print("  state:", J55.state, " gate_result:", J55.gate_result)
print("  chatter posted?", bool(chatter))
print("T55:", "PASS" if ok else "FAIL")
results["T55"] = ok


# ============================================================
print()
print("=" * 72)
print("T56 - Sales blocked on non-eligible partner")
print("=" * 72)
J56 = env["commercial.job"].create({
    "partner_id": p_neither.id, "venue_id": venue.id,
    "event_date": fields.Date.add(fields.Date.today(), days=150),
})
raised = False
try:
    J56.with_user(sales).action_rapid_activate()
except UserError as e:
    raised = True
    msg = str(e)
J56.invalidate_recordset()
ok = raised and J56.state == "pending" and "not Rapid Ops eligible" in msg
print("  raised UserError?", raised)
print("  message contains expected phrase?",
      "not Rapid Ops eligible" in (msg if raised else ""))
print("  state remains pending?", J56.state == "pending")
print("T56:", "PASS" if ok else "FAIL")
results["T56"] = ok


# ============================================================
print()
print("=" * 72)
print("T57 - Manager rapid-activates non-eligible partner")
print("=" * 72)
J57 = env["commercial.job"].create({
    "partner_id": p_neither.id, "venue_id": venue.id,
    "event_date": fields.Date.add(fields.Date.today(), days=160),
    "logistics_flag": True,  # soft warning
})
try:
    J57.with_user(manager).action_rapid_activate()
    J57.invalidate_recordset()
    activated = J57.state == "active" and J57.gate_result == "pass"
except (UserError, AccessError) as e:
    print("  unexpected error:", str(e)[:120])
    activated = False
chatter = J57.message_ids.filtered(
    lambda m: "non-eligible partner" in (m.body or "")
    and "manager authorization" in (m.body or ""))
ok = activated and bool(chatter)
print("  state:", J57.state, " gate_result:", J57.gate_result)
print("  manager-override chatter posted?", bool(chatter))
print("T57:", "PASS" if ok else "FAIL")
results["T57"] = ok


# ============================================================
print()
print("=" * 72)
print("T58 - HARD reject blocks Rapid Activate even for eligible partner")
print("=" * 72)
blocker_date = fields.Date.add(fields.Date.today(), days=170)
J_block = env["commercial.job"].create({
    "partner_id": p_neither.id, "venue_id": venue.id, "venue_room_id": room.id,
    "event_date": blocker_date,
})
J_block.write({"state": "active", "soft_hold_until": False})
J58 = env["commercial.job"].create({
    "partner_id": p_manual.id,  # ELIGIBLE
    "venue_id": venue.id, "venue_room_id": room.id,
    "event_date": blocker_date,
})
raised = False
try:
    J58.with_user(sales).action_rapid_activate()
except UserError as e:
    raised = True
    msg = str(e)
J58.invalidate_recordset()
ok = raised and J58.state == "pending" and "Capacity Gate rejected" in msg
print("  raised UserError?", raised)
print("  state remains pending?", J58.state == "pending")
print("T58:", "PASS" if ok else "FAIL")
results["T58"] = ok


# ============================================================
print()
print("=" * 72)
print("T59 - can_rapid_activate computed correctness")
print("=" * 72)
# pending + eligible → True for Sales
J59a = env["commercial.job"].create({
    "partner_id": p_manual.id, "venue_id": venue.id,
    "event_date": fields.Date.add(fields.Date.today(), days=200),
})
v1 = J59a.with_user(sales).can_rapid_activate
# pending + non-eligible → False for Sales, True for Manager
J59b = env["commercial.job"].create({
    "partner_id": p_neither.id, "venue_id": venue.id,
    "event_date": fields.Date.add(fields.Date.today(), days=210),
})
v2_sales = J59b.with_user(sales).can_rapid_activate
v2_mgr = J59b.with_user(manager).can_rapid_activate
# active → False for everyone
J59c = env["commercial.job"].create({
    "partner_id": p_manual.id, "venue_id": venue.id,
    "event_date": fields.Date.add(fields.Date.today(), days=220),
})
J59c.write({"state": "active", "soft_hold_until": False})
v3_sales = J59c.with_user(sales).can_rapid_activate
v3_mgr = J59c.with_user(manager).can_rapid_activate
ok = v1 and (not v2_sales) and v2_mgr and (not v3_sales) and (not v3_mgr)
print("  pending eligible / sales:    ", v1, "(want True)")
print("  pending non-eligible / sales:", v2_sales, "(want False)")
print("  pending non-eligible / mgr:  ", v2_mgr, "(want True)")
print("  active / sales:              ", v3_sales, "(want False)")
print("  active / mgr:                ", v3_mgr, "(want False)")
print("T59:", "PASS" if ok else "FAIL")
results["T59"] = ok


# ============================================================
print()
print("=" * 72)
print("T60 - Audit trail (log markers + chatter timestamp)")
print("=" * 72)
J55.invalidate_recordset()
log_payload = json.loads(J55.gate_check_log or "{}")
bypassed_log = [
    c for c in log_payload.get("checks", []) if c.get("bypassed")
]
chatter_entries = J55.message_ids.filtered(
    lambda m: "Rapid Ops Activation" in (m.body or ""))
ok = (
    bool(bypassed_log)
    and all("RAPID_OPS_BYPASS" in c["message"] for c in bypassed_log)
    and bool(chatter_entries)
    and bool(chatter_entries[:1].date)
)
print("  log has bypassed checks?", bool(bypassed_log),
      " count:", len(bypassed_log))
print("  all bypassed checks carry marker?",
      all("RAPID_OPS_BYPASS" in c["message"] for c in bypassed_log))
print("  chatter entry present?  ", bool(chatter_entries))
print("T60:", "PASS" if ok else "FAIL")
results["T60"] = ok


# ============================================================
print()
print("=" * 72)
print("T61 - is_rapid_ops_eligible_manual manager-only writeable")
print("=" * 72)
p_guard = Partner.create({"name": "P2M8 Guard Test", "is_company": True})
env.cr.commit()
# Manager succeeds
ok_mgr = True
try:
    p_guard.with_user(manager).write({"is_rapid_ops_eligible_manual": True})
except (UserError, AccessError) as e:
    ok_mgr = False
    print("  unexpected manager error:", str(e)[:120])
# Sales is blocked by the write guard
ok_sales_blocked = False
try:
    p_guard.with_user(sales).write({"is_rapid_ops_eligible_manual": False})
except (UserError, AccessError) as e:
    ok_sales_blocked = True
    print("  sales blocked as expected:", type(e).__name__)
ok = ok_mgr and ok_sales_blocked
print("  manager write succeeded?", ok_mgr)
print("  sales write blocked?    ", ok_sales_blocked)
print("T61:", "PASS" if ok else "FAIL")
results["T61"] = ok


# ============================================================
print()
print("=" * 72)
print("T63 - Banner copy: both eligibility variants present in form arch")
print("=" * 72)
form_view = env.ref("neon_jobs.commercial_job_view_form")
arch = form_view.arch
# Normalise whitespace so substring checks survive arch-stored newlines.
flat = " ".join(arch.split())
has_trusted = (
    "Rapid Activate available" in flat
    and "trusted fast path" in flat
)
has_override = (
    "Manager override available" in flat
    and "not on the trusted fast path" in flat
    and "rapid-activate as manager" in flat
)
trusted_guard = 'invisible="state != \'pending\' or not can_rapid_activate or not partner_is_rapid_ops_eligible"'
override_guard = 'invisible="state != \'pending\' or not can_rapid_activate or partner_is_rapid_ops_eligible"'
has_trusted_guard = trusted_guard in flat
has_override_guard = override_guard in flat
ok = has_trusted and has_override and has_trusted_guard and has_override_guard
print("  trusted-client copy present?       ", has_trusted)
print("  manager-override copy present?     ", has_override)
print("  trusted guard expression present?  ", has_trusted_guard)
print("  override guard expression present? ", has_override_guard)
print("T63:", "PASS" if ok else "FAIL")
results["T63"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T52", "T53", "T54", "T55", "T56", "T57", "T58", "T59", "T60",
         "T61", "T63"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
