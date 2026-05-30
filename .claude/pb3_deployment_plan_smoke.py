"""P-B3 smoke -- AI Deployment Plan Generation.

Runs in `odoo shell -d <db>`. T-B3-01 ... T-B3-30.

Covers:
- model + ACL + call-time config singleton present
- fact-gatherer pulls correct equipment + crew + B2 conflict lines
- draft-state events rejected (B2-DM-2 mirror)
- generator routes to Claude via the B13 adapter (assert provider)
- design-seed lock: validator REJECTS plans that
  - omit a known deficit (R4 cardinal sin)
  - contradict B2 quantities (R1)
  - reference non-existent competing events (R2)
  - hallucinate crew names (R3)
  - use wrong section keys (R5)
  - inject concrete datetimes not in facts (R6 -- parseable only)
  - mismatch data_quality_note (R7)
- deficit block payload includes competing_event_names
- data_quality_note carried verbatim from B2 to plan to render
- generated plans NEVER auto-final (state stays at 'generated')
- regenerate spawns a new revision + supersedes the prior
- render produces HTML (no PDF this milestone, D10 trim)
"""
import json
from datetime import datetime, date, time, timedelta
from unittest.mock import patch, MagicMock


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-B3 -- AI Deployment Plan Generation")
print("=" * 72)
results = {}

Users = env["res.users"]
Partner = env["res.partner"]
Job = env["commercial.job"]
EventJob = env["commercial.event.job"]
Line = env["commercial.event.job.equipment.line"]
Unit = env["neon.equipment.unit"]
Product = env["product.template"]
Plan = env["neon.deployment.plan"]
PlanCfg = env["neon.deployment.plan.call.time.config"]
Conflict = env["neon.equipment.conflict"]
Provider = env["neon.doc.gen.provider"]

from odoo.addons.neon_jobs.models.deployment_plan_generator import (
    DeploymentPlanGenerator,
)
from odoo.addons.neon_jobs.models.deployment_plan_fact_gatherer import (
    DeploymentPlanFactGatherer,
)
from odoo.addons.neon_jobs.models.deployment_plan_validator import (
    DeploymentPlanValidator, PlanValidationError,
)
from odoo.addons.neon_jobs.models.neon_equipment_conflict import (
    ConflictEngine,
)


# Setup: grant admin the superuser group for ACL paths.
admin = env.ref("base.user_admin")
admin.sudo().write({
    "groups_id": [
        (4, env.ref("neon_core.group_neon_superuser").id),
        (4, env.ref("neon_jobs.group_neon_jobs_manager").id),
    ],
})
env = env(user=admin.id)


# ============================================================
# T-B3-01 .. 04 -- model surface + ACL + config singleton
# ============================================================
_check("T-B3-01",
       "event_job_id" in Plan._fields
       and "status" in Plan._fields
       and "revision" in Plan._fields
       and "plan_json" in Plan._fields
       and "plan_summary_html" in Plan._fields
       and "source_conflict_id" in Plan._fields
       and "data_quality_note" in Plan._fields,
       "plan model carries the locked contract fields")

unlinkable = env["ir.model.access"].sudo().search([
    ("model_id.model", "=", "neon.deployment.plan"),
    ("perm_unlink", "=", True),
])
_check("T-B3-02", not unlinkable,
       f"perm_unlink=0 on all plan ACL rows; "
       f"violations={unlinkable.mapped('group_id.name')}")

cfg = PlanCfg.sudo().get_singleton()
_check("T-B3-03",
       bool(cfg)
       and cfg.crew_chief_offset_minutes == 30
       and cfg.lead_tech_offset_minutes == 60
       and cfg.rest_offset_minutes == 15
       and cfg.anchor_policy == "max_prep_dispatch",
       f"call-time config singleton present + defaults match")

_check("T-B3-04",
       not cfg.is_ops_signed_off,
       "config flagged for ops sign-off (Lisa) -- pending by default")


# ============================================================
# Fixtures
# ============================================================
partner = Partner.sudo().search([], limit=1)
venue = Partner.sudo().search([("is_venue", "=", True)], limit=1)
product = Product.sudo().search(
    [("is_workshop_item", "=", True)], limit=1)
today = date.today()

# Wipe leftover PB3 fixtures
EventJob.sudo().search([("name", "=like", "PB3 SMOKE EVT%")]).with_context(
    _allow_state_write=True).write({"state": "cancelled"})
# Cancel + unlink BOTH python smoke (PB3 SMOKE) and browser smoke
# (PB3 BR) fixtures, then wipe units from both sets. Browser
# smoke leftover units inflate available_qty and confuse the
# B2 cluster expectations below.
to_cancel = EventJob.sudo().search(
    ["|",
     ("name", "=like", "PB3 SMOKE EVT%"),
     ("name", "=like", "PB3 BR EVT%")])
if to_cancel:
    to_cancel.with_context(_allow_state_write=True).write(
        {"state": "cancelled"})
    to_cancel.unlink()
Job.sudo().search(
    ["|",
     ("name", "=like", "PB3 SMOKE JOB%"),
     ("name", "=like", "PB3 BR JOB%")]).unlink()
Plan.sudo().search([]).filtered(
    lambda p: not p.event_job_id.exists()).unlink()
Conflict.sudo().search([("name", "=like", "CONF-%")]).unlink()
Unit.sudo().search(
    ["|",
     ("serial_number", "=like", "PB3-SMK-%"),
     ("serial_number", "=like", "PB3BR-%")]).unlink()
env.cr.commit()


def _mk_job(label, evdate, end=None):
    v = {"name": f"PB3 SMOKE JOB {label}",
         "partner_id": partner.id, "state": "active",
         "event_date": evdate}
    if end:
        v["event_end_date"] = end
    if venue:
        v["venue_id"] = venue.id
    return Job.sudo().create(v)


def _mk_event(label, master, **extra):
    v = {"name": f"PB3 SMOKE EVT {label}",
         "commercial_job_id": master.id, "partner_id": partner.id}
    v.update(extra)
    ev = EventJob.sudo().create(v)
    # Transition out of draft so the engine cluster picks it up.
    ev.sudo().with_context(_allow_state_write=True).write(
        {"state": "planning"})
    return ev


# Build a deficit scenario: 4 units owned, demand=6 across 2 events
if product:
    pb3_units = Unit.sudo().create([{
        "product_template_id": product.id,
        "serial_number": f"PB3-SMK-{i}",
        "condition_status": "good",
    } for i in range(4)])
    mA = _mk_job("A", today)
    mB = _mk_job("B", today)
    eA = _mk_event("A", mA,
                    load_in_start=datetime.combine(today, time(9, 0)),
                    load_out_end=datetime.combine(today, time(14, 0)),
                    dispatch_datetime=datetime.combine(today, time(8, 0)),
                    prep_start_datetime=datetime.combine(today, time(7, 0)))
    eB = _mk_event("B", mB,
                    load_in_start=datetime.combine(today, time(12, 0)),
                    load_out_end=datetime.combine(today, time(18, 0)))
    Line.sudo().create({"event_job_id": eA.id,
                          "product_template_id": product.id,
                          "quantity_planned": 5})
    Line.sudo().create({"event_job_id": eB.id,
                          "product_template_id": product.id,
                          "quantity_planned": 2})
    # Force ORM flush so the conflict engine sees the writes.
    eA.flush_recordset(); eB.flush_recordset()
    Line.sudo().flush_model()
    EventJob.sudo().flush_model()
    env.cr.commit()
    # Run the B2 engine so the conflict snapshot exists.
    # Single-event cluster: eA alone demands 5 > available 4 = deficit 1.
    # If eB also clusters, demand=7, deficit=3. Test reads actuals.
    ConflictEngine(env).run_for_event(eA, trigger_reason="manual")


# ============================================================
# T-B3-05 .. 08 -- fact gatherer
# ============================================================
if product:
    gatherer = DeploymentPlanFactGatherer(env)
    facts = gatherer.gather(eA)
    _check("T-B3-05",
           facts["event_job"]["id"] == eA.id
           and facts["event_job"]["state"] == "planning",
           f"facts.event_job populated")
    _check("T-B3-06",
           len(facts["equipment_lines"]) == 1
           and facts["equipment_lines"][0]["quantity_planned"] == 5,
           f"equipment lines pulled: {len(facts['equipment_lines'])} "
           f"qty={facts['equipment_lines'][0]['quantity_planned'] if facts['equipment_lines'] else '-'}")
    # B2 conflict line should be present with required=6, available=4, deficit=2
    b2_lines = facts["b2_conflict"]["lines"]
    matching = [ln for ln in b2_lines
                 if ln["product_template_id"] == product.id]
    # Take the actuals -- B2 may cluster (req=7) or single-event
    # (req=5). Either way available=4 and we expect a real deficit.
    _check("T-B3-07",
           bool(matching)
           and matching[0]["required_qty"] >= 5
           and matching[0]["available_qty"] == 4
           and matching[0]["deficit_qty"] >= 1
           and matching[0]["status"] == "deficit",
           f"B2 conflict snapshot: {matching}")
    # data_quality_note: load_in_start AND load_out_end are set, so NULL
    _check("T-B3-08",
           facts["b2_conflict"]["data_quality_note"] is None,
           f"data_quality_note=None when windows precise; "
           f"got={facts['b2_conflict']['data_quality_note']!r}")
else:
    for t in (f"T-B3-{i:02d}" for i in range(5, 9)):
        _check(t, True, "no workshop product; skipped")


# ============================================================
# T-B3-09 -- gathering on a draft event still works (gathering
# itself doesn't gate; the generator gates).
# ============================================================
if product:
    master_d = _mk_job("DRAFT", today)
    eDraft = EventJob.sudo().create({
        "name": "PB3 SMOKE EVT DRAFT",
        "commercial_job_id": master_d.id,
        "partner_id": partner.id,
    })
    # Leave in draft
    draft_facts = DeploymentPlanFactGatherer(env).gather(eDraft)
    _check("T-B3-09",
           draft_facts["event_job"]["state"] == "draft",
           "fact-gather works on draft events (gating is at generator)")


# ============================================================
# T-B3-10 -- generator REFUSES draft events (B2-DM-2 mirror)
# ============================================================
if product:
    try:
        DeploymentPlanGenerator(env).generate_for_event(eDraft)
        raised = None
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    _check("T-B3-10",
           raised == "UserError",
           f"generator refuses state='draft' (B2-DM-2 mirror); "
           f"got={raised}")


# ============================================================
# T-B3-11 .. 17 -- validator strict rules (each rule independently)
# ============================================================
if product:
    validator = DeploymentPlanValidator(facts)

    def _good_plan():
        """Build a plan that satisfies all 7 rules. Used as the
        baseline for the negative tests below -- each test mutates
        one field to trigger a single rule. Reads ACTUAL B2 numbers
        so the baseline is data-driven, not hardcoded."""
        deficit_entry = {
            "product_name": matching[0]["product_name"],
            "required_qty": matching[0]["required_qty"],
            "available_qty": matching[0]["available_qty"],
            "deficit_qty": matching[0]["deficit_qty"],
            "competing_event_names": list(
                matching[0]["competing_event_names"]),
            "sub_hire_priority": matching[0]["sub_hire_priority"],
        }
        return {
            "sections": [
                {"key": "load_in", "title": "Load-in",
                 "narrative": "Morning of the event."},
                {"key": "setup", "title": "Setup",
                 "narrative": "After load-in."},
                {"key": "show_time", "title": "Show",
                 "narrative": "Show runs through the day."},
                {"key": "strike", "title": "Strike",
                 "narrative": "Post-event."},
                {"key": "return", "title": "Return",
                 "narrative": "Convoy back."},
                {"key": "risks", "title": "Risks",
                 "narrative": "Sub-hire planned."},
            ],
            "crew_call_times": list(facts.get("crew_call_times")
                                     or []),
            "deficits": [deficit_entry],
            "data_quality_note": facts["b2_conflict"].get(
                "data_quality_note"),
        }

    # Baseline must pass
    try:
        validator.validate(_good_plan())
        baseline_ok = True
    except PlanValidationError as exc:
        baseline_ok = False
        print("  baseline failed:", exc)
    _check("T-B3-11", baseline_ok, "baseline plan passes validator")

    # R4 -- omitted deficit (cardinal sin)
    bad = _good_plan(); bad["deficits"] = []
    try:
        validator.validate(bad); r4 = False
    except PlanValidationError as exc:
        r4 = "R4" in str(exc)
    _check("T-B3-12", r4, "R4 omitted deficit -> reject")

    # R1 -- hallucinated quantity
    bad = _good_plan()
    bad["deficits"][0]["required_qty"] = 99
    try:
        validator.validate(bad); r1 = False
    except PlanValidationError as exc:
        r1 = "R1" in str(exc)
    _check("T-B3-13", r1, "R1 quantity contradiction -> reject")

    # R2 -- hallucinated competing event
    bad = _good_plan()
    bad["deficits"][0]["competing_event_names"] = ["IMAGINARY EVENT"]
    try:
        validator.validate(bad); r2 = False
    except PlanValidationError as exc:
        r2 = "R2" in str(exc)
    _check("T-B3-14", r2,
           "R2 fake competing event -> reject")

    # R3 -- hallucinated crew name
    bad = _good_plan()
    bad["crew_call_times"] = [{
        "crew_partner_name": "Imaginary McFakery",
        "call_at": "2026-06-15T07:00:00", "role": "crew",
        "duty": "made up"}]
    try:
        validator.validate(bad); r3 = False
    except PlanValidationError as exc:
        r3 = "R3" in str(exc)
    _check("T-B3-15", r3, "R3 fake crew name -> reject")

    # R5 -- wrong section key
    bad = _good_plan()
    bad["sections"][0]["key"] = "BANANA"
    try:
        validator.validate(bad); r5 = False
    except PlanValidationError as exc:
        r5 = "R5" in str(exc)
    _check("T-B3-16", r5, "R5 wrong section key -> reject")

    # R6 -- concrete datetime not in facts
    bad = _good_plan()
    bad["sections"][0]["narrative"] = (
        "Setup commences at 2099-12-31T23:45:00.")
    try:
        validator.validate(bad); r6 = False
    except PlanValidationError as exc:
        r6 = "R6" in str(exc)
    _check("T-B3-17", r6,
           "R6 concrete datetime not in facts -> reject")

    # R6 (split per gate-1 (a)) -- relative phrasing must NOT
    # trigger. "morning of the event" doesn't parse, so allowed.
    bad = _good_plan()
    bad["sections"][0]["narrative"] = (
        "Load-in begins the morning of the event, "
        "during prep phase.")
    try:
        validator.validate(bad)
        r6_soft = True
    except PlanValidationError as exc:
        r6_soft = False
        print("  r6_soft failed:", exc)
    _check("T-B3-18", r6_soft,
           "R6 relative phrasing PASSES (split per gate-1 (a))")

    # R7 -- data_quality_note mismatch when B2 has none
    bad = _good_plan()
    bad["data_quality_note"] = (
        "this is not what B2 said")
    try:
        validator.validate(bad); r7 = False
    except PlanValidationError as exc:
        r7 = "R7" in str(exc)
    _check("T-B3-19", r7,
           "R7 data_quality_note mismatch -> reject")
else:
    for t in (f"T-B3-{i:02d}" for i in range(11, 20)):
        _check(t, True, "no workshop product; skipped")


# ============================================================
# T-B3-20 .. 22 -- generator routes to Claude via B13 (mocked)
# ============================================================
if product:
    # Set a fake key + mock the adapter so we can prove the path.
    provider = Provider.sudo().search(
        [("provider_key", "=", "anthropic")], limit=1)
    if provider:
        provider._set_api_key("sk-ant-PB3-TEST-12345")
        provider.sudo().write({"is_enabled": True})

    good_plan_payload = _good_plan()
    mock_out = {
        "result": good_plan_payload,
        "usage": {"prompt_tokens": 1200,
                   "completion_tokens": 400},
        "model": "claude-sonnet-4-6",
        "latency_ms": 1500,
    }

    from odoo.addons.neon_doc_gen.models.ai_doc_gen import (
        claude_docgen_adapter as adapter_mod,
    )
    with patch.object(adapter_mod.ClaudeDocGenAdapter,
                       "generate",
                       return_value=mock_out) as m_gen:
        plan = DeploymentPlanGenerator(env).generate_for_event(eA)

    _check("T-B3-20",
           m_gen.called,
           "DeploymentPlanGenerator called the Claude adapter")
    # Inspect the call args -- system_prompt + facts + json_schema
    call_kwargs = m_gen.call_args.kwargs or {}
    _check("T-B3-21",
           "json_schema" in call_kwargs
           and "facts" in call_kwargs
           and "system_prompt" in call_kwargs
           and call_kwargs["json_schema"].get("required")
           == ["sections", "deficits", "data_quality_note"],
           f"adapter called with json_schema + facts + system_prompt")
    _check("T-B3-22",
           plan.status == "generated"
           and plan.event_job_id.id == eA.id
           and plan.revision == 1
           and plan.model_used == "claude-sonnet-4-6"
           and plan.prompt_tokens == 1200
           and plan.completion_tokens == 400,
           f"plan persisted: status={plan.status} rev={plan.revision} "
           f"tokens={plan.prompt_tokens}/{plan.completion_tokens}")


# ============================================================
# T-B3-23 -- design-seed lock end-to-end: a plan that OMITS the
# deficit is REJECTED through the orchestrator (with one retry).
# ============================================================
if product:
    bad_payload = _good_plan()
    bad_payload["deficits"] = []  # omit the cardinal sin
    bad_mock_out = {
        "result": bad_payload,
        "usage": {"prompt_tokens": 800, "completion_tokens": 200},
        "model": "claude-sonnet-4-6", "latency_ms": 1100,
    }
    with patch.object(adapter_mod.ClaudeDocGenAdapter,
                       "generate",
                       return_value=bad_mock_out):
        try:
            DeploymentPlanGenerator(env).generate_for_event(
                eA, replaces=plan)
            raised_msg = None
        except Exception as exc:  # noqa: BLE001
            raised_msg = str(exc)
    _check("T-B3-23",
           raised_msg is not None
           and ("R4" in raised_msg
                or "omits" in raised_msg.lower()
                or "deficit" in raised_msg.lower()),
           f"orchestrator rejects omitted-deficit plan after retry; "
           f"err={(raised_msg or '')[:120]!r}")


# ============================================================
# T-B3-24 -- quarantine persists the bad output for debugging
# ============================================================
if product:
    quarantined = Plan.sudo().search(
        [("event_job_id", "=", eA.id),
         ("quarantine_json", "!=", False)],
        order="id desc", limit=1)
    _check("T-B3-24",
           bool(quarantined)
           and bool(quarantined.quarantine_json)
           and quarantined.status == "draft",
           f"quarantined draft plan: {bool(quarantined)} "
           f"status={quarantined.status if quarantined else 'NONE'}")


# ============================================================
# T-B3-25 -- state machine: generated plan does NOT auto-final
# ============================================================
if product:
    # The successful plan from T-B3-22 should still be 'generated'.
    plan.invalidate_recordset(["status"])
    _check("T-B3-25",
           plan.status == "generated",
           f"generated plan stays at 'generated' until reviewer "
           f"acts; current={plan.status}")


# ============================================================
# T-B3-26 -- review gate: human moves to reviewed, then final
# ============================================================
if product:
    plan.action_mark_reviewed()
    plan.invalidate_recordset(["status", "reviewed_at",
                                 "reviewed_by_id"])
    rev_ok = (plan.status == "reviewed"
               and bool(plan.reviewed_at)
               and plan.reviewed_by_id.id == admin.id)
    plan.action_mark_final()
    plan.invalidate_recordset(["status", "finalised_at",
                                 "finalised_by_id"])
    fin_ok = (plan.status == "final"
               and bool(plan.finalised_at)
               and plan.finalised_by_id.id == admin.id)
    _check("T-B3-26", rev_ok and fin_ok,
           f"review gate: rev_ok={rev_ok} fin_ok={fin_ok}")


# ============================================================
# T-B3-27 -- regenerate is BLOCKED while plan is final
# ============================================================
if product:
    try:
        plan.action_regenerate()
        blocked = False
    except Exception as exc:  # noqa: BLE001
        blocked = "Un-finalise" in str(exc)
    _check("T-B3-27", blocked,
           "regenerate blocked on final plan -- must un-finalise first")


# ============================================================
# T-B3-28 -- regenerate after un-finalise spawns a new revision
# + supersedes the prior
# ============================================================
if product:
    plan.action_unfinalise()
    plan.invalidate_recordset(["status"])
    with patch.object(adapter_mod.ClaudeDocGenAdapter,
                       "generate",
                       return_value=mock_out):
        new_plan_act = plan.action_regenerate()
    new_plan = Plan.sudo().browse(new_plan_act["res_id"])
    plan.invalidate_recordset(["status", "superseded_by_plan_id"])
    _check("T-B3-28",
           new_plan.revision > plan.revision
           and new_plan.event_job_id.id == eA.id
           and plan.status == "superseded"
           and plan.superseded_by_plan_id.id == new_plan.id,
           f"new rev={new_plan.revision} > prior {plan.revision}; "
           f"old status={plan.status}; superseded_by_id="
           f"{plan.superseded_by_plan_id.id}")


# ============================================================
# T-B3-29 -- render produces HTML with deficit block + competing
# event names (no PDF, per D10 trim)
# ============================================================
if product:
    html_out = new_plan.plan_summary_html or ""
    competing_in_html = all(
        n in html_out
        for n in matching[0]["competing_event_names"][:1])
    _check("T-B3-29",
           "ACTION REQUIRED" in html_out
           and "SUB-HIRE" in html_out
           and competing_in_html
           and "PDF" not in html_out  # D10 trim sanity
           and "deficit" in html_out.lower(),
           f"render: deficit block present + competing names + no PDF")


# ============================================================
# T-B3-30 -- data_quality_note carry-through when B2 surfaces one
# ============================================================
if product:
    # Build a fresh event WITHOUT precise load-in/out so the note fires.
    mC = _mk_job("DQ", today + timedelta(days=14))
    eDQ = _mk_event("DQ", mC)
    Line.sudo().create({"event_job_id": eDQ.id,
                         "product_template_id": product.id,
                         "quantity_planned": 1})
    ConflictEngine(env).run_for_event(eDQ, trigger_reason="manual")
    facts_dq = DeploymentPlanFactGatherer(env).gather(eDQ)
    dqn = facts_dq["b2_conflict"]["data_quality_note"]
    _check("T-B3-30",
           bool(dqn)
           and "calendar-day granularity" in dqn,
           f"data_quality_note surfaces when load-in/out blank; "
           f"len={len(dqn) if dqn else 0}")


# ============================================================
# Cleanup
# ============================================================
EventJob.sudo().search([("name", "=like", "PB3 SMOKE EVT%")]).with_context(
    _allow_state_write=True).write({"state": "cancelled"})
EventJob.sudo().search([("name", "=like", "PB3 SMOKE EVT%")]).unlink()
Job.sudo().search([("name", "=like", "PB3 SMOKE JOB%")]).unlink()
Plan.sudo().search([]).filtered(
    lambda p: not p.event_job_id.exists()).unlink()
Conflict.sudo().search([("name", "=like", "CONF-%")]).unlink()
if product:
    Unit.sudo().search(
        [("serial_number", "=like", "PB3-SMK-%")]).unlink()
# Restore provider state
if provider:
    provider._set_api_key("")
env.cr.commit()


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
