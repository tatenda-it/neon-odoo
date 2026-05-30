"""P3.M6 smoke — Scope Change Tracking.

T113 Lead Tech (crew_leader group) can log a scope change.
T114 Crew Chief on the event can log a scope change (crew tier + chief flag).
T115 Regular crew (NOT crew_chief) cannot log scope changes → UserError.
T116 Sales review flow: lead logs → sales reviews with billing_action.
T117 Sales cannot finalise (manager-only) → UserError.
T118 Manager finalises a reviewed scope_change.
T119 Cancellation is manager-only; sales blocked, manager allowed.
T120 Smart button + scope_change_count compute on event_job.
T121 ir_rule for crew read-own: crew sees own events' scope changes,
     not other events'.
T122 Default billing_action is 'pending_decision'.
T123 Required-field validation: description, event_job_id.
T124 Sequence: SCC-NNNNNN auto-numbered.
T125 Crew Chief sees can_log_scope_change=True; action returns prefilled form.
T126 Regular crew (not chief) sees can_log_scope_change=False.
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

# Clean prior P3M6 fixtures
prior_jobs = env["commercial.job"].sudo().search(
    [("equipment_summary", "like", "P3M6FIX")])
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
        "equipment_summary": "P3M6FIX " + label,
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


results = {}

# ============================================================
print()
print("=" * 72)
print("T113 - Lead Tech (crew_leader) can log a scope change")
print("=" * 72)
J113, EJ113 = _new_job_with_event("T113", 60, lead_tech=crew_leader)
sc = env["commercial.scope.change"].with_user(crew_leader).create({
    "event_job_id": EJ113.id,
    "description": "Added second monitor mix for the band",
    "scope_change_type": "addition",
})
sc.invalidate_recordset()
ok = (
    sc.state == "logged"
    and sc.billing_action == "pending_decision"
    and sc.logged_by == crew_leader
    and sc.name.startswith("SCC-")
)
print("  state:", sc.state, "(want logged)")
print("  billing_action:", sc.billing_action, "(want pending_decision)")
print("  logged_by:", sc.logged_by.login)
print("  name:", sc.name)
print("T113:", "PASS" if ok else "FAIL")
results["T113"] = ok


# ============================================================
print()
print("=" * 72)
print("T114 - Crew Chief on the event can log a scope change")
print("=" * 72)
J114, EJ114 = _new_job_with_event("T114", 65, lead_tech=crew_leader)
_set_crew_chief(J114, crew_only)
EJ114.invalidate_recordset()
# Verify the event sees crew_only as crew_chief before we test
print("  crew_chief on event:", EJ114.crew_chief_id.login)
try:
    sc114 = env["commercial.scope.change"].with_user(crew_only).create({
        "event_job_id": EJ114.id,
        "description": "Client requested extra cocktail-hour PA at venue",
        "scope_change_type": "addition",
    })
    sc114.invalidate_recordset()
    ok = (
        sc114.state == "logged"
        and sc114.logged_by == crew_only
        and sc114.billing_action == "pending_decision"
    )
    print("  state:", sc114.state, " logged_by:", sc114.logged_by.login)
except (UserError, AccessError) as e:
    ok = False
    print("  raised unexpectedly:", str(e)[:200])
print("T114:", "PASS" if ok else "FAIL")
results["T114"] = ok


# ============================================================
print()
print("=" * 72)
print("T115 - Regular crew (NOT chief) cannot log scope changes")
print("=" * 72)
J115, EJ115 = _new_job_with_event("T115", 70, lead_tech=crew_leader)
_set_crew_chief(J115, crew_only)  # crew_only is chief on this job
_add_confirmed_crew(J115, other_crew, is_chief=False)  # other_crew is crew, NOT chief
EJ115.invalidate_recordset()
raised = False
err_msg = ""
try:
    env["commercial.scope.change"].with_user(other_crew).create({
        "event_job_id": EJ115.id,
        "description": "Should be blocked",
    })
except (UserError, AccessError) as e:
    raised = True
    err_msg = str(e)
existing = env["commercial.scope.change"].sudo().search(
    [("event_job_id", "=", EJ115.id),
     ("description", "=", "Should be blocked")])
ok = raised and not existing
print("  raised?", raised, " (msg:", err_msg[:120], ")")
print("  no record created?", not bool(existing))
print("T115:", "PASS" if ok else "FAIL")
results["T115"] = ok


# ============================================================
print()
print("=" * 72)
print("T116 - Sales review flow: lead logs → sales reviews")
print("=" * 72)
J116, EJ116 = _new_job_with_event("T116", 75, lead_tech=crew_leader)
sc116 = env["commercial.scope.change"].with_user(crew_leader).create({
    "event_job_id": EJ116.id,
    "description": "Client added 50 extra guests on the morning of",
    "scope_change_type": "modification",
    "estimated_value": 350.0,
})
# Sales reviews
sc116.with_user(sales).action_mark_reviewed(
    billing_action="chargeable",
    billing_notes="Will append to final invoice — per Robin approval call",
)
sc116.invalidate_recordset()
ok = (
    sc116.state == "reviewed"
    and sc116.billing_action == "chargeable"
    and sc116.reviewed_by == sales
    and sc116.reviewed_at
    and "Chargeable" in (sc116.message_ids[0].body or "")
)
print("  state:", sc116.state, "(want reviewed)")
print("  billing_action:", sc116.billing_action, "(want chargeable)")
print("  reviewed_by:", sc116.reviewed_by.login, "  reviewed_at set?",
      bool(sc116.reviewed_at))
print("  chatter mentions Chargeable?",
      "Chargeable" in (sc116.message_ids[0].body or ""))
print("T116:", "PASS" if ok else "FAIL")
results["T116"] = ok


# ============================================================
print()
print("=" * 72)
print("T117 - Sales cannot finalise (manager only)")
print("=" * 72)
raised = False
err_msg = ""
try:
    sc116.with_user(sales).action_finalise()
except UserError as e:
    raised = True
    err_msg = str(e)
sc116.invalidate_recordset()
ok = raised and sc116.state == "reviewed"
print("  raised?", raised, " (msg:", err_msg[:120], ")")
print("  state still reviewed?", sc116.state == "reviewed")
print("T117:", "PASS" if ok else "FAIL")
results["T117"] = ok


# ============================================================
print()
print("=" * 72)
print("T118 - Manager finalises a reviewed scope_change")
print("=" * 72)
sc116.with_user(manager).action_finalise()
sc116.invalidate_recordset()
ok = bool(
    sc116.state == "finalised"
    and sc116.finalised_by == manager
    and sc116.finalised_at
)
print("  state:", sc116.state, "(want finalised)")
print("  finalised_by:", sc116.finalised_by.login,
      "  finalised_at set?", bool(sc116.finalised_at))
print("T118:", "PASS" if ok else "FAIL")
results["T118"] = ok


# ============================================================
print()
print("=" * 72)
print("T119 - Cancellation is manager-only")
print("=" * 72)
J119, EJ119 = _new_job_with_event("T119", 80, lead_tech=crew_leader)
sc119 = env["commercial.scope.change"].with_user(crew_leader).create({
    "event_job_id": EJ119.id,
    "description": "Logged in error — test for cancellation",
})
# Sales blocked
sales_blocked = False
try:
    sc119.with_user(sales).action_cancel(reason="not allowed")
except UserError:
    sales_blocked = True
sc119.invalidate_recordset()
state_after_sales = sc119.state
# Manager succeeds
sc119.with_user(manager).action_cancel(reason="logged in error")
sc119.invalidate_recordset()
ok = (
    sales_blocked
    and state_after_sales == "logged"
    and sc119.state == "cancelled"
    and "logged in error" in (sc119.message_ids[0].body or "").lower()
)
print("  sales blocked?", sales_blocked, "  state after sales attempt:",
      state_after_sales)
print("  manager succeeded?", sc119.state == "cancelled")
print("  reason captured in chatter?",
      "logged in error" in (sc119.message_ids[0].body or "").lower())
print("T119:", "PASS" if ok else "FAIL")
results["T119"] = ok


# ============================================================
print()
print("=" * 72)
print("T120 - Smart button + scope_change_count on event_job")
print("=" * 72)
J120, EJ120 = _new_job_with_event("T120", 85, lead_tech=crew_leader)
for i in range(3):
    env["commercial.scope.change"].with_user(crew_leader).create({
        "event_job_id": EJ120.id,
        "description": "P3M6FIX T120 item %d" % (i + 1),
    })
EJ120.invalidate_recordset()
EJ120._compute_scope_change_count()
count = EJ120.scope_change_count
action = EJ120.action_open_scope_changes()
ok = (
    count == 3
    and action.get("type") == "ir.actions.act_window"
    and action.get("res_model") == "commercial.scope.change"
    and ("event_job_id", "=", EJ120.id) in action.get("domain", [])
)
print("  scope_change_count:", count, "(want 3)")
print("  action type:", action.get("type"))
print("  action domain:", action.get("domain"))
print("T120:", "PASS" if ok else "FAIL")
results["T120"] = ok


# ============================================================
print()
print("=" * 72)
print("T121 - ir_rule: crew reads own events' scope changes only")
print("=" * 72)
# J119 has no crew assignments; build event A with crew_only on it,
# event B WITHOUT crew_only. Crew should see A's scope_changes only.
J121A, EJ121A = _new_job_with_event("T121A", 90, lead_tech=crew_leader)
_add_confirmed_crew(J121A, crew_only, is_chief=False)
J121B, EJ121B = _new_job_with_event("T121B", 92, lead_tech=crew_leader)
# Sales logs one on each (sales has create authority via the user group)
sc_A = env["commercial.scope.change"].with_user(sales).create({
    "event_job_id": EJ121A.id, "description": "P3M6FIX T121 on A",
})
sc_B = env["commercial.scope.change"].with_user(sales).create({
    "event_job_id": EJ121B.id, "description": "P3M6FIX T121 on B",
})
# Crew searches — should see A, not B
visible_ids = env["commercial.scope.change"].with_user(crew_only).search([]).ids
sees_A = sc_A.id in visible_ids
sees_B = sc_B.id in visible_ids
ok = sees_A and not sees_B
print("  crew sees scope_change on own event A?", sees_A)
print("  crew sees scope_change on other event B?", sees_B, "(want False)")
print("T121:", "PASS" if ok else "FAIL")
results["T121"] = ok


# ============================================================
print()
print("=" * 72)
print("T122 - Default billing_action is 'pending_decision'")
print("=" * 72)
J122, EJ122 = _new_job_with_event("T122", 95, lead_tech=crew_leader)
sc122 = env["commercial.scope.change"].with_user(crew_leader).create({
    "event_job_id": EJ122.id,
    "description": "Default-billing-action test",
    # No billing_action provided
})
sc122.invalidate_recordset()
ok = sc122.billing_action == "pending_decision"
print("  billing_action:", sc122.billing_action, "(want pending_decision)")
print("T122:", "PASS" if ok else "FAIL")
results["T122"] = ok


# ============================================================
print()
print("=" * 72)
print("T123 - Required-field validation")
print("=" * 72)
J123, EJ123 = _new_job_with_event("T123", 100, lead_tech=crew_leader)
env.cr.commit()  # commit fixture so we can rollback the failed creates
# Missing description — wrap in savepoint so the NOT NULL violation
# from postgres doesn't abort the outer transaction (which would break
# every subsequent test).
raised_desc = False
try:
    with env.cr.savepoint():
        env["commercial.scope.change"].with_user(crew_leader).create({
            "event_job_id": EJ123.id,
            # description omitted
        })
except Exception:
    raised_desc = True
# Missing event_job_id
raised_ej = False
try:
    with env.cr.savepoint():
        env["commercial.scope.change"].with_user(crew_leader).create({
            "description": "no event_job",
        })
except Exception:
    raised_ej = True
ok = raised_desc and raised_ej
print("  missing description raised?", raised_desc)
print("  missing event_job_id raised?", raised_ej)
print("T123:", "PASS" if ok else "FAIL")
results["T123"] = ok


# ============================================================
print()
print("=" * 72)
print("T124 - Sequence: SCC-NNNNNN auto-numbered")
print("=" * 72)
J124, EJ124 = _new_job_with_event("T124", 105, lead_tech=crew_leader)
names = []
for i in range(3):
    sc = env["commercial.scope.change"].with_user(crew_leader).create({
        "event_job_id": EJ124.id,
        "description": "P3M6FIX T124 seq item %d" % (i + 1),
    })
    names.append(sc.name)
# Names follow SCC-NNNNNN pattern, monotonically increasing.
def _num(n):
    return int(n.split("-")[1])
ok = (
    all(n.startswith("SCC-") for n in names)
    and len(set(names)) == 3
    and _num(names[1]) == _num(names[0]) + 1
    and _num(names[2]) == _num(names[1]) + 1
)
print("  names:", names)
print("T124:", "PASS" if ok else "FAIL")
results["T124"] = ok


# ============================================================
print()
print("=" * 72)
print("T125 - Crew Chief sees Log Scope Change button + prefilled action")
print("=" * 72)
J125, EJ125 = _new_job_with_event("T125", 110, lead_tech=crew_leader)
_set_crew_chief(J125, crew_only)
EJ125.invalidate_recordset()
ej_as_chief = EJ125.with_user(crew_only)
ej_as_chief.invalidate_recordset()
chief_can_log = ej_as_chief.can_log_scope_change
action = ej_as_chief.action_log_scope_change()
ctx = action.get("context", {}) or {}
ok = bool(
    chief_can_log
    and action.get("type") == "ir.actions.act_window"
    and action.get("res_model") == "commercial.scope.change"
    and action.get("view_mode") == "form"
    and ctx.get("default_event_job_id") == EJ125.id
)
print("  can_log_scope_change for crew_chief:", chief_can_log, "(want True)")
print("  action type:", action.get("type"))
print("  action view_mode:", action.get("view_mode"))
print("  prefilled default_event_job_id:", ctx.get("default_event_job_id"),
      "(want", EJ125.id, ")")
print("T125:", "PASS" if ok else "FAIL")
results["T125"] = ok


# ============================================================
print()
print("=" * 72)
print("T126 - Regular crew (not chief) sees button hidden")
print("=" * 72)
J126, EJ126 = _new_job_with_event("T126", 115, lead_tech=crew_leader)
_set_crew_chief(J126, crew_only)  # crew_only IS chief
_add_confirmed_crew(J126, other_crew, is_chief=False)  # other_crew NOT chief
EJ126.invalidate_recordset()
# Also sanity-check: lead_tech, sales, manager all see True
sales_can = EJ126.with_user(sales).can_log_scope_change
lead_can = EJ126.with_user(crew_leader).can_log_scope_change
mgr_can = EJ126.with_user(manager).can_log_scope_change
chief_can = EJ126.with_user(crew_only).can_log_scope_change
other_can = EJ126.with_user(other_crew).can_log_scope_change
# Defensive: action_log_scope_change should also raise UserError for
# the non-chief crew
raised_other = False
try:
    EJ126.with_user(other_crew).action_log_scope_change()
except UserError:
    raised_other = True
ok = bool(
    other_can is False
    and raised_other
    and sales_can and lead_can and mgr_can and chief_can
)
print("  can_log for sales:", sales_can, "(want True)")
print("  can_log for crew_leader:", lead_can, "(want True)")
print("  can_log for manager:", mgr_can, "(want True)")
print("  can_log for crew_chief:", chief_can, "(want True)")
print("  can_log for regular crew:", other_can, "(want False)")
print("  action raises UserError for regular crew:", raised_other)
print("T126:", "PASS" if ok else "FAIL")
results["T126"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T113", "T114", "T115", "T116", "T117", "T118", "T119",
         "T120", "T121", "T122", "T123", "T124", "T125", "T126"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
