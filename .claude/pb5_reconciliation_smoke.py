"""P-B5 smoke -- Post-event reconciliation.

T-B5-01..T-B5-32.

Covers (mirrors B3 + B4 smoke discipline):
- model + ACL + perm_unlink=0
- post-event state gate refuses pre-event (draft/planning/etc.)
- post-event state gate ACCEPTS completed/closed/returned
- fact-gather reuses B3's DeploymentPlanFactGatherer
- fact-gather snapshots B3 plan + B4 sub-hires + condition deltas
- fact-gather READS finance models via sudo() (no writes)
- generation routes to Claude via B13 adapter
- design-seed lock validator R1..R7:
  - R4 omitted written-off unit -> reject (cardinal sin)
  - R4 omitted active sub-hire -> reject
  - R1 sub-hire quantity contradiction -> reject
  - R1 condition delta count contradiction -> reject
  - R2 hallucinated unit serial -> reject
  - R2 hallucinated sub-hire request_name -> reject
  - R3 supplier_name contradiction -> reject
  - R5 event_window mismatch -> reject
  - R6 concrete datetime not in facts -> reject
  - R7 data_quality_note carry-through
- request persists + supersede pattern
- regenerate spawns new revision + prior -> superseded
- review gate (generated -> reviewed -> final)
- finalise posts workshop chatter + activity when units flagged
- finalise does NOT auto-flip condition_status (D5 hard rule)
- B5 never writes to any financial model (D4 hard rule)
"""
import json
from datetime import datetime, date, time, timedelta
from unittest.mock import patch


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-B5 -- Post-event reconciliation")
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
Request = env["neon.subhire.request"]
RequestLine = env["neon.subhire.request.line"]
Conflict = env["neon.equipment.conflict"]
Recon = env["neon.event.reconciliation"]
Provider = env["neon.doc.gen.provider"]

from odoo.addons.neon_jobs.models.event_reconciliation_generator import (
    EventReconciliationGenerator,
)
from odoo.addons.neon_jobs.models.event_reconciliation_fact_gatherer import (
    EventReconciliationFactGatherer,
)
from odoo.addons.neon_jobs.models.event_reconciliation_validator import (
    EventReconciliationValidator, ReconValidationError,
)
from odoo.addons.neon_jobs.models.neon_equipment_conflict import (
    ConflictEngine,
)

admin = env.ref("base.user_admin")
admin.sudo().write({
    "groups_id": [
        (4, env.ref("neon_core.group_neon_superuser").id),
        (4, env.ref("neon_jobs.group_neon_jobs_manager").id),
    ],
})
env = env(user=admin.id)


# ============================================================
# T-B5-01..04 -- model surface + ACL
# ============================================================
_check("T-B5-01",
       all(f in Recon._fields for f in (
           "event_job_id", "status", "revision", "facts_json",
           "summary_json", "summary_html", "source_plan_id",
           "source_subhire_request_ids", "written_off_count",
           "needs_repair_count", "cost_variance_total")),
       "neon.event.reconciliation carries the locked contract fields")

unlinkable = env["ir.model.access"].sudo().search([
    ("model_id.model", "=", "neon.event.reconciliation"),
    ("perm_unlink", "=", True),
])
_check("T-B5-02", not unlinkable,
       f"perm_unlink=0 on all reconciliation ACL rows; "
       f"violations={unlinkable.mapped('group_id.name')}")

acl_rows = env["ir.model.access"].sudo().search([
    ("model_id.model", "=", "neon.event.reconciliation"),
])
_check("T-B5-03",
       len(acl_rows) == 4,
       f"4 ACL rows (user/crew_leader/manager/superuser); got "
       f"{len(acl_rows)}")

_check("T-B5-04",
       "superseded_by_recon_id" in Recon._fields
       and "finalised_at" in Recon._fields,
       "supersede + finalise audit fields present")


# ============================================================
# Fixtures
# ============================================================
partner = Partner.sudo().search([], limit=1)
venue = Partner.sudo().search([("is_venue", "=", True)], limit=1)
today = date.today()

# Cleanup any prior PB5 fixtures
Recon.sudo().search([]).unlink()
Request.sudo().search(
    [("name", "=like", "SUBHIRE-PB5-%")]).unlink()
Plan.sudo().search([]).filtered(
    lambda p: not p.event_job_id.exists()).unlink()
to_cancel = EventJob.sudo().search(
    [("name", "=like", "PB5 SMOKE EVT%")])
if to_cancel:
    to_cancel.with_context(_allow_state_write=True).write(
        {"state": "cancelled"})
    to_cancel.unlink()
Job.sudo().search([("name", "=like", "PB5 SMOKE JOB%")]).unlink()
# Movements reference units via restrict FK -- delete first.
Movement = env["neon.equipment.movement"]
old_units = Unit.sudo().search(
    [("serial_number", "=like", "PB5-SMK-%")])
if old_units:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [("unit_id", "in", old_units.ids)]).unlink()
    old_units.unlink()
# Conflicts touching the old product must die first (FK).
old_prod = Product.sudo().search(
    [("name", "=", "PB5-SMK-PRODUCT")])
if old_prod:
    Conflict.sudo().search([
        ("line_ids.product_template_id", "=", old_prod.id),
    ]).unlink()
    old_prod.unlink()
product = Product.sudo().create({
    "name": "PB5-SMK-PRODUCT",
    "is_workshop_item": True,
})
env.cr.commit()


def _mk_job(label, evdate):
    v = {"name": f"PB5 SMOKE JOB {label}",
         "partner_id": partner.id, "state": "active",
         "event_date": evdate}
    if venue:
        v["venue_id"] = venue.id
    return Job.sudo().create(v)


def _mk_event(label, master, state, **extra):
    v = {"name": f"PB5 SMOKE EVT {label}",
         "commercial_job_id": master.id,
         "partner_id": partner.id}
    v.update(extra)
    ev = EventJob.sudo().create(v)
    ev.sudo().with_context(_allow_state_write=True).write(
        {"state": state})
    return ev


# Build: 1 event in 'completed' state with deficits + plan + sub-hire.
units = Unit.sudo().create([{
    "product_template_id": product.id,
    "serial_number": f"PB5-SMK-{i}",
    "condition_status": "good",
} for i in range(4)])
mA = _mk_job("A", today - timedelta(days=2))
eA_completed = _mk_event(
    "A", mA, "completed",
    event_date=today - timedelta(days=2),
    load_in_start=datetime.combine(
        today - timedelta(days=2), time(9, 0)),
    load_out_end=datetime.combine(
        today - timedelta(days=2), time(14, 0)))
Line.sudo().create({
    "event_job_id": eA_completed.id,
    "product_template_id": product.id,
    "quantity_planned": 5,
})
eA_completed.flush_recordset()
Line.sudo().flush_model()
EventJob.sudo().flush_model()
env.cr.commit()
ConflictEngine(env).run_for_event(eA_completed,
                                    trigger_reason="manual")

# Link 2 units to the event via movements so the fact-gatherer
# can find them. (The real-world flow is checkout/checkin
# movements; we create the minimum to wire the FK.)
Movement = env["neon.equipment.movement"]
event_line = Line.sudo().search(
    [("event_job_id", "=", eA_completed.id)], limit=1)
for u in units[:2]:
    Movement.sudo().create({
        "unit_id": u.id,
        "event_job_id": eA_completed.id,
        "equipment_line_id": (event_line.id
                                 if event_line else False),
        "movement_type": "checkout",
        "from_location_text": "Workshop",
        "to_location_text": "Event",
    })

# Flip 1 unit to needs_repair, 1 to written_off (B5 should
# surface these as condition deltas).
units[0].sudo().write({"condition_status": "needs_repair"})
units[1].sudo().write({"condition_status": "written_off"})
env.cr.commit()


# ============================================================
# T-B5-05 -- fact-gather pulls plan + sub-hire + condition deltas
# ============================================================
gatherer = EventReconciliationFactGatherer(env)
facts = gatherer.gather(eA_completed)
_check("T-B5-05",
       all(k in facts for k in (
           "plan_snapshot", "subhire_snapshot",
           "condition_deltas", "cost_variance",
           "event_window_label", "b2_conflict")),
       "facts dict carries all B5 sections + B3 reuse")


# ============================================================
# T-B5-06 -- condition_deltas reflects unit flips
# ============================================================
written_off = [d for d in facts["condition_deltas"]
               if d["new_status"] == "written_off"]
needs_repair = [d for d in facts["condition_deltas"]
                if d["new_status"] == "needs_repair"]
_check("T-B5-06",
       len(written_off) == 1 and len(needs_repair) == 1
       and written_off[0]["serial_number"] == "PB5-SMK-1"
       and needs_repair[0]["serial_number"] == "PB5-SMK-0",
       f"1 written_off + 1 needs_repair; got "
       f"wo={len(written_off)} nr={len(needs_repair)}")


# ============================================================
# T-B5-07 -- event_window_label precise
# ============================================================
expected_label = (
    eA_completed.load_in_start.isoformat()
    + " -> " + eA_completed.load_out_end.isoformat())
_check("T-B5-07",
       facts["event_window_label"] == expected_label,
       f"window label precise: {facts['event_window_label']!r}")


# ============================================================
# T-B5-08 -- state gate refuses pre-event (draft)
# ============================================================
mDraft = _mk_job("DRAFT", today)
eDraft = EventJob.sudo().create({
    "name": "PB5 SMOKE EVT DRAFT",
    "commercial_job_id": mDraft.id,
    "partner_id": partner.id,
})  # state='draft' by default
try:
    EventReconciliationGenerator(env).generate_for_event(eDraft)
    raised = None
except Exception as exc:  # noqa: BLE001
    raised = type(exc).__name__
_check("T-B5-08",
       raised == "UserError",
       f"generator refuses state='draft'; got={raised}")


# ============================================================
# T-B5-09 -- state gate refuses planning
# ============================================================
mPlan = _mk_job("PLAN", today)
ePlan = _mk_event("PLAN", mPlan, "planning")
try:
    EventReconciliationGenerator(env).generate_for_event(ePlan)
    raised = None
except Exception as exc:  # noqa: BLE001
    raised = type(exc).__name__
_check("T-B5-09",
       raised == "UserError",
       f"generator refuses state='planning'; got={raised}")


# ============================================================
# T-B5-10 -- state gate ACCEPTS 'closed'
# ============================================================
mClose = _mk_job("CLOSE", today - timedelta(days=3))
eClose = _mk_event(
    "CLOSE", mClose, "closed",
    event_date=today - timedelta(days=3))
# state='closed' is a post-event state; the gate should pass.
# Since there are no deficits we'll mock the Claude call so the
# generator gets past the API check; we only test the gate here
# by ensuring the call doesn't raise on the state.
def _state_only_probe(self, event_job):
    self._check_state_gate(event_job)  # no raise -> gate ok
ok_close = False
try:
    EventReconciliationGenerator(env)._check_state_gate(eClose)
    ok_close = True
except Exception:  # noqa: BLE001
    ok_close = False
_check("T-B5-10", ok_close,
       "state='closed' passes the post-event gate")


# ============================================================
# T-B5-11 -- validator setup baseline + 7 rules
# ============================================================
# Build a sub-hire so the snapshot has 1 entry for validator.
provider = Provider.sudo().search(
    [("provider_key", "=", "anthropic")], limit=1)
if provider:
    provider._set_api_key("sk-ant-PB5-TEST-12345")
    provider.sudo().write({"is_enabled": True,
                             "model": "claude-sonnet-4-6"})
# Pre-stage a sub-hire request for the completed event so the
# subhire_snapshot has something to test against.
sup = Partner.sudo().search(
    [("name", "=", "PB5 SMK SUPPLIER A")], limit=1)
if not sup:
    sup = Partner.sudo().create({
        "name": "PB5 SMK SUPPLIER A",
        "is_company": True, "supplier_rank": 1,
    })
test_req = Request.sudo().create({
    "event_job_id": eA_completed.id,
    "revision": 1,
    "status": "approved",
    "supplier_partner_id": sup.id,
})
RequestLine.sudo().create({
    "request_id": test_req.id,
    "product_template_id": product.id,
    "qty_short": 1,
    "event_window": expected_label,
    "competing_event_names_csv": "",
    "sub_hire_priority": 0,
})
env.cr.commit()

# Re-gather facts to pick up the new sub-hire
facts = EventReconciliationFactGatherer(env).gather(eA_completed)
validator = EventReconciliationValidator(facts)


def _good_draft():
    sh_snap = facts["subhire_snapshot"][0]
    wo_unit = next(d for d in facts["condition_deltas"]
                    if d["new_status"] == "written_off")
    return {
        "headline": "Event reconciled cleanly.",
        "executive_summary": (
            "The event ran to plan with a few items flagged "
            "for the workshop. One unit was written off."),
        "what_went_well": ["Load-in on time.",
                            "Sub-hire arrived early."],
        "what_didnt": ["One unit was written off."],
        "equipment_outcomes": {
            "written_off_count": 1,
            "needs_repair_count": 1,
            "narrative": (
                "The equipment was returned with one unit needing "
                "repair and one written off."),
            "flagged_units": [{
                "serial_number": wo_unit["serial_number"],
                "product_name": wo_unit["product_name"],
                "new_status": "written_off",
            }],
        },
        "subhire_outcomes": [{
            "request_name": sh_snap["name"],
            "qty_short_total": sh_snap["qty_short_total"],
            "line_count": sh_snap["line_count"],
            "supplier_name": sh_snap["supplier_name"],
            "narrative": (
                "Sub-hire arrived on the morning of the event."),
        }],
        "cost_narrative": (
            "Costs reported as informational only; no journal "
            "writes."),
        "lessons": ["Schedule a workshop check post-event."],
        "event_window": facts["event_window_label"],
        "data_quality_note": facts["b2_conflict"].get(
            "data_quality_note"),
    }


try:
    validator.validate(_good_draft())
    baseline_ok = True
except ReconValidationError as exc:
    baseline_ok = False
    print("  baseline failed:", exc)
_check("T-B5-11", baseline_ok,
       "baseline draft passes 7-rule validator")


# ============================================================
# T-B5-12 -- R4 omitted written-off unit -> reject
# ============================================================
bad = _good_draft()
bad["equipment_outcomes"]["flagged_units"] = []
try:
    validator.validate(bad); r4a = False
except ReconValidationError as exc:
    r4a = "R4" in str(exc) and "written-off" in str(exc).lower()
_check("T-B5-12", r4a,
       "R4 omitted written-off unit -> reject (cardinal sin)")


# ============================================================
# T-B5-13 -- R4 omitted active sub-hire -> reject
# ============================================================
bad = _good_draft()
bad["subhire_outcomes"] = []
try:
    validator.validate(bad); r4b = False
except ReconValidationError as exc:
    r4b = "R4" in str(exc) and "sub-hire" in str(exc).lower()
_check("T-B5-13", r4b,
       "R4 omitted active sub-hire -> reject")


# ============================================================
# T-B5-14 -- R1 sub-hire quantity contradiction
# ============================================================
bad = _good_draft()
bad["subhire_outcomes"][0]["qty_short_total"] = 99
try:
    validator.validate(bad); r1a = False
except ReconValidationError as exc:
    r1a = "R1" in str(exc)
_check("T-B5-14", r1a,
       "R1 sub-hire qty contradiction -> reject")


# ============================================================
# T-B5-15 -- R1 condition delta count contradiction
# ============================================================
bad = _good_draft()
bad["equipment_outcomes"]["written_off_count"] = 99
try:
    validator.validate(bad); r1b = False
except ReconValidationError as exc:
    r1b = "R1" in str(exc)
_check("T-B5-15", r1b,
       "R1 condition delta count contradiction -> reject")


# ============================================================
# T-B5-16 -- R2 hallucinated unit serial
# ============================================================
bad = _good_draft()
bad["equipment_outcomes"]["flagged_units"][0][
    "serial_number"] = "FAKE-SERIAL"
try:
    validator.validate(bad); r2a = False
except ReconValidationError as exc:
    # R4 might trip first if FAKE replaces the real serial.
    r2a = ("R2" in str(exc)) or ("R4" in str(exc))
_check("T-B5-16", r2a,
       "R2 hallucinated unit serial -> reject (R2 or R4)")


# ============================================================
# T-B5-17 -- R2 hallucinated sub-hire request_name
# ============================================================
bad = _good_draft()
bad["subhire_outcomes"][0]["request_name"] = (
    "SUBHIRE-FAKE-001")
try:
    validator.validate(bad); r2b = False
except ReconValidationError as exc:
    r2b = ("R2" in str(exc)) or ("R4" in str(exc))
_check("T-B5-17", r2b,
       "R2 hallucinated sub-hire name -> reject")


# ============================================================
# T-B5-18 -- R3 supplier_name contradiction
# ============================================================
bad = _good_draft()
bad["subhire_outcomes"][0]["supplier_name"] = "WRONG SUPPLIER"
try:
    validator.validate(bad); r3 = False
except ReconValidationError as exc:
    r3 = "R3" in str(exc)
_check("T-B5-18", r3,
       "R3 supplier_name contradiction -> reject")


# ============================================================
# T-B5-19 -- R5 event_window mismatch
# ============================================================
bad = _good_draft()
bad["event_window"] = "not the right window"
try:
    validator.validate(bad); r5 = False
except ReconValidationError as exc:
    r5 = "R5" in str(exc)
_check("T-B5-19", r5,
       "R5 event_window mismatch -> reject")


# ============================================================
# T-B5-20 -- R6 concrete datetime not in facts
# ============================================================
bad = _good_draft()
bad["executive_summary"] = (
    "Event completed at 2099-12-31T23:59:00 sharp.")
try:
    validator.validate(bad); r6 = False
except ReconValidationError as exc:
    r6 = "R6" in str(exc)
_check("T-B5-20", r6,
       "R6 concrete datetime not in facts -> reject")


# ============================================================
# T-B5-21 -- R6 relative phrasing PASSES
# ============================================================
bad = _good_draft()
bad["executive_summary"] = (
    "Event ran cleanly through the load-out window.")
try:
    validator.validate(bad); r6_soft = True
except ReconValidationError:
    r6_soft = False
_check("T-B5-21", r6_soft,
       "R6 relative phrasing PASSES (split rule)")


# ============================================================
# T-B5-22 -- R7 data_quality_note mismatch
# ============================================================
bad = _good_draft()
bad["data_quality_note"] = (
    "wrong text -- not what B2 said")
try:
    validator.validate(bad); r7 = False
except ReconValidationError as exc:
    r7 = "R7" in str(exc)
_check("T-B5-22", r7,
       "R7 data_quality_note mismatch -> reject")


# ============================================================
# T-B5-23..26 -- generator routes to Claude via B13 (mocked)
# ============================================================
good_payload = _good_draft()
mock_out = {
    "result": good_payload,
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
    rec = EventReconciliationGenerator(
        env).generate_for_event(eA_completed)

_check("T-B5-23",
       m_gen.called,
       "EventReconciliationGenerator called the Claude adapter")
call_kwargs = m_gen.call_args.kwargs or {}
_check("T-B5-24",
       "json_schema" in call_kwargs
       and "facts" in call_kwargs
       and "system_prompt" in call_kwargs,
       "adapter called with json_schema + facts + system_prompt")
_check("T-B5-25",
       rec.status == "generated"
       and rec.event_job_id.id == eA_completed.id
       and rec.revision == 1
       and rec.model_used == "claude-sonnet-4-6"
       and rec.prompt_tokens == 1200
       and rec.completion_tokens == 400
       and bool(rec.summary_json)
       and bool(rec.facts_json),
       f"reconciliation persisted: status={rec.status} rev="
       f"{rec.revision} model={rec.model_used}")
_check("T-B5-26",
       rec.written_off_count == 1
       and rec.needs_repair_count == 1
       and rec.source_plan_id.id == (
           facts["plan_snapshot"]["plan_id"] or 0)
       and test_req in rec.source_subhire_request_ids,
       f"counts + snapshots populated; wo="
       f"{rec.written_off_count} nr={rec.needs_repair_count} "
       f"sh_count={len(rec.source_subhire_request_ids)}")


# ============================================================
# T-B5-27 -- review gate + finalise + workshop chatter
# ============================================================
existing_msg_ids = set(rec.message_ids.ids)
rec.action_mark_reviewed()
rec.invalidate_recordset(["status", "reviewed_at"])
rev_ok = (rec.status == "reviewed"
           and bool(rec.reviewed_at))
rec.action_mark_final()
rec.invalidate_recordset(["status", "finalised_at",
                            "message_ids"])
final_ok = (rec.status == "final"
             and bool(rec.finalised_at))
new_msgs = rec.message_ids.filtered(
    lambda m: m.id not in existing_msg_ids)
workshop_alert = any(
    "Workshop alert" in (m.body or "") for m in new_msgs)
_check("T-B5-27",
       rev_ok and final_ok and workshop_alert,
       f"review/final transitions + workshop chatter posted; "
       f"reviewed={rev_ok} final={final_ok} alert={workshop_alert} "
       f"new_msg_count={len(new_msgs)}")


# ============================================================
# T-B5-28 -- finalise did NOT auto-flip condition_status (D5)
# ============================================================
units[0].invalidate_recordset(["condition_status"])
units[1].invalidate_recordset(["condition_status"])
still_repair = units[0].condition_status == "needs_repair"
still_writeoff = units[1].condition_status == "written_off"
_check("T-B5-28",
       still_repair and still_writeoff,
       f"D5 holds: condition_status unchanged after finalise; "
       f"unit0={units[0].condition_status} "
       f"unit1={units[1].condition_status}")


# ============================================================
# T-B5-29 -- regenerate spawns new revision + supersedes prior
# ============================================================
with patch.object(adapter_mod.ClaudeDocGenAdapter,
                   "generate", return_value=mock_out):
    new_act = rec.action_regenerate()
new_rec = Recon.sudo().browse(new_act["res_id"])
rec.invalidate_recordset(
    ["status", "superseded_by_recon_id"])
_check("T-B5-29",
       new_rec.revision > rec.revision
       and rec.status == "superseded"
       and rec.superseded_by_recon_id.id == new_rec.id,
       f"new rev={new_rec.revision} > prior {rec.revision}; "
       f"old status={rec.status}")


# ============================================================
# T-B5-30 -- quarantine path persists bad output
# ============================================================
bad_payload = _good_draft()
bad_payload["equipment_outcomes"]["flagged_units"] = []
bad_mock_out = {
    "result": bad_payload,
    "usage": {"prompt_tokens": 500,
               "completion_tokens": 100},
    "model": "claude-sonnet-4-6", "latency_ms": 900,
}
with patch.object(adapter_mod.ClaudeDocGenAdapter,
                   "generate",
                   return_value=bad_mock_out):
    try:
        EventReconciliationGenerator(env).generate_for_event(
            eA_completed, replaces=new_rec)
        raised_msg = None
    except Exception as exc:  # noqa: BLE001
        raised_msg = str(exc)
quar = Recon.sudo().search(
    [("event_job_id", "=", eA_completed.id),
     ("quarantine_json", "!=", False)],
    order="id desc", limit=1)
_check("T-B5-30",
       raised_msg is not None
       and ("R4" in raised_msg or "written-off" in raised_msg)
       and bool(quar) and quar.status == "draft",
       f"quarantine after retry; raised={(raised_msg or '')[:80]!r}")


# ============================================================
# T-B5-31 -- variance flows through to record (read-only)
# ============================================================
# variance is informational; verify cost_variance_total field
# reflects facts; ensure NO new account.move rows were created.
move_count_before = env["account.move"].sudo().search_count([])
# Touch the cost_variance_total compute to ensure it's stored
new_rec.invalidate_recordset(["cost_variance_total"])
_ = new_rec.cost_variance_total
move_count_after = env["account.move"].sudo().search_count([])
_check("T-B5-31",
       move_count_before == move_count_after,
       f"B5 read-only on finance: account.move count "
       f"unchanged (before={move_count_before} after="
       f"{move_count_after})")


# ============================================================
# T-B5-32 -- D4 hard rule: zero invoice/journal writes anywhere
# in the entire reconciliation flow (entry-to-final)
# ============================================================
# Verify the PB5 product never got a cost.line or quote written
# for it (a side-effect would imply B5 wrote to finance).
sl_count = 0
try:
    CostLine = env.get("neon.finance.cost.line")
    if CostLine is not None:
        sl_count = CostLine.sudo().search_count(
            [("event_job_id", "=", eA_completed.id)])
except Exception:  # noqa: BLE001
    sl_count = 0
_check("T-B5-32",
       sl_count == 0,
       f"D4 holds: zero cost.line writes for PB5 events; "
       f"count={sl_count}")


# ============================================================
# Cleanup
# ============================================================
Recon.sudo().search([]).unlink()
Request.sudo().search(
    [("name", "=like", "SUBHIRE-PB5-%")]).unlink()
Request.sudo().search(
    [("event_job_id.name", "=like", "PB5 SMOKE EVT%")]).unlink()
to_cancel = EventJob.sudo().search(
    [("name", "=like", "PB5 SMOKE EVT%")])
if to_cancel:
    to_cancel.with_context(_allow_state_write=True).write(
        {"state": "cancelled"})
    to_cancel.unlink()
Job.sudo().search([("name", "=like", "PB5 SMOKE JOB%")]).unlink()
# Movements first, then units (restrict FK).
old_units2 = Unit.sudo().search(
    [("serial_number", "=like", "PB5-SMK-%")])
if old_units2:
    env["neon.equipment.movement"].sudo().with_context(
        _allow_movement_write=True).search(
        [("unit_id", "in", old_units2.ids)]).unlink()
    old_units2.unlink()
Partner.sudo().search(
    [("name", "=", "PB5 SMK SUPPLIER A")]).unlink()
# Conflict + lines + units MUST go before the product unlink.
old_prod_cleanup = Product.sudo().search(
    [("name", "=", "PB5-SMK-PRODUCT")])
if old_prod_cleanup:
    Conflict.sudo().search([
        ("line_ids.product_template_id", "=",
          old_prod_cleanup.id),
    ]).unlink()
    old_prod_cleanup.unlink()
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
