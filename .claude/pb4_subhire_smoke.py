"""P-B4 smoke -- Sub-hire request drafting + PO draft.

Runs in `odoo shell -d <db>`. T-B4-01 ... T-B4-32.

Covers:
- model + ACL + linked-line model
- fact-gather REUSES B3's DeploymentPlanFactGatherer, filters to
  deficit/zero_margin lines
- generator refuses event_job.state == 'draft' (B2-DM-2 mirror)
- generator refuses when no deficits exist (nothing to sub-hire)
- generation routes to Claude via B13 adapter (assert provider)
- design-seed lock validator rejects drafts that:
  - omit a known deficit (R4)
  - contradict B2 quantities (R1)
  - hallucinate competing events (R3)
  - hallucinate product names (R2)
  - mismatch event_window (R5)
  - inject concrete datetimes not in facts (R6 -- parseable only)
  - mismatch data_quality_note (R7)
- quarantine path persists bad output for debugging
- one-active-with-revision supersedes (mirror B3-D7)
- regenerate BLOCKED while sent; un-send required first
- supplier_partner_id required for approve; auto-assignment refused
- "Approve + Create PO Draft" creates a purchase.order in state='draft',
  NEVER confirms or auto-sends
- "Mark Sent" is metadata-only -- does NOT touch the PO state
- empty supplier set surfaces has_supplier_candidates=False
- render produces HTML (no PDF)
- ONE PO per request (single supplier per request)
"""
import json
from datetime import datetime, date, time, timedelta
from unittest.mock import patch


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-B4 -- Sub-hire request drafting + PO draft")
print("=" * 72)
results = {}

Users = env["res.users"]
Partner = env["res.partner"]
Job = env["commercial.job"]
EventJob = env["commercial.event.job"]
Line = env["commercial.event.job.equipment.line"]
Unit = env["neon.equipment.unit"]
Product = env["product.template"]
Request = env["neon.subhire.request"]
RequestLine = env["neon.subhire.request.line"]
Conflict = env["neon.equipment.conflict"]
Provider = env["neon.doc.gen.provider"]
PO = env.get("purchase.order")
POLine = env.get("purchase.order.line")

from odoo.addons.neon_jobs.models.subhire_request_generator import (
    SubhireRequestGenerator,
)
from odoo.addons.neon_jobs.models.subhire_request_fact_gatherer import (
    SubhireRequestFactGatherer,
)
from odoo.addons.neon_jobs.models.subhire_request_validator import (
    SubhireRequestValidator, SubhireValidationError,
)
from odoo.addons.neon_jobs.models.neon_equipment_conflict import (
    ConflictEngine,
)


# Setup: grant admin the superuser group
admin = env.ref("base.user_admin")
admin.sudo().write({
    "groups_id": [
        (4, env.ref("neon_core.group_neon_superuser").id),
        (4, env.ref("neon_jobs.group_neon_jobs_manager").id),
    ],
})
env = env(user=admin.id)


# ============================================================
# T-B4-01 .. 04 -- model surface + ACL + purchase available
# ============================================================
_check("T-B4-01",
       "event_job_id" in Request._fields
       and "status" in Request._fields
       and "revision" in Request._fields
       and "draft_json" in Request._fields
       and "draft_summary_html" in Request._fields
       and "supplier_partner_id" in Request._fields
       and "po_draft_id" in Request._fields
       and "line_ids" in Request._fields,
       "neon.subhire.request carries the locked contract fields")

unlinkable = env["ir.model.access"].sudo().search([
    ("model_id.model", "in",
     ("neon.subhire.request",
      "neon.subhire.request.line")),
    ("perm_unlink", "=", True),
])
_check("T-B4-02", not unlinkable,
       f"perm_unlink=0 on all subhire ACL rows; "
       f"violations={unlinkable.mapped('group_id.name')}")

_check("T-B4-03",
       PO is not None and POLine is not None,
       f"purchase.order + purchase.order.line in registry "
       f"(PO={PO is not None} POLine={POLine is not None})")

_check("T-B4-04",
       "has_supplier_candidates" in Request._fields,
       "has_supplier_candidates compute field present")


# ============================================================
# Fixtures
# ============================================================
partner = Partner.sudo().search([], limit=1)
venue = Partner.sudo().search([("is_venue", "=", True)], limit=1)
today = date.today()

# Wipe leftover PB4 fixtures
to_cancel = EventJob.sudo().search(
    [("name", "=like", "PB4 SMOKE EVT%")])
if to_cancel:
    to_cancel.with_context(_allow_state_write=True).write(
        {"state": "cancelled"})
    to_cancel.unlink()
Job.sudo().search([("name", "=like", "PB4 SMOKE JOB%")]).unlink()
Unit.sudo().search(
    [("serial_number", "=like", "PB4-SMK-%")]).unlink()
Request.sudo().search([]).filtered(
    lambda r: not r.event_job_id.exists()).unlink()
Conflict.sudo().search([("name", "=like", "CONF-%")]).unlink()
# Wipe any leftover PB4 suppliers + PO drafts
Partner.sudo().search(
    [("name", "=like", "PB4 SUPPLIER%")]).unlink()
PO.sudo().search([("origin", "=like", "SUBHIRE-%")]).unlink()
# Use a fresh PB4-only product so available_qty == units we create.
# (Avoids pollution from other smokes' existing workshop products.)
Product.sudo().search(
    [("name", "=", "PB4-SMK-PRODUCT")]).unlink()
product = Product.sudo().create({
    "name": "PB4-SMK-PRODUCT",
    "is_workshop_item": True,
})
env.cr.commit()


def _mk_job(label, evdate):
    v = {"name": f"PB4 SMOKE JOB {label}",
         "partner_id": partner.id, "state": "active",
         "event_date": evdate}
    if venue:
        v["venue_id"] = venue.id
    return Job.sudo().create(v)


def _mk_event(label, master, **extra):
    v = {"name": f"PB4 SMOKE EVT {label}",
         "commercial_job_id": master.id,
         "partner_id": partner.id}
    v.update(extra)
    ev = EventJob.sudo().create(v)
    ev.sudo().with_context(_allow_state_write=True).write(
        {"state": "planning"})
    return ev


# Build a deficit scenario: 4 owned, demand = 5 -> deficit_qty=1
if product:
    pb4_units = Unit.sudo().create([{
        "product_template_id": product.id,
        "serial_number": f"PB4-SMK-{i}",
        "condition_status": "good",
    } for i in range(4)])
    mA = _mk_job("A", today)
    eA = _mk_event(
        "A", mA,
        load_in_start=datetime.combine(today, time(9, 0)),
        load_out_end=datetime.combine(today, time(14, 0)),
        dispatch_datetime=datetime.combine(today, time(8, 0)),
        prep_start_datetime=datetime.combine(today, time(7, 0)))
    Line.sudo().create({
        "event_job_id": eA.id,
        "product_template_id": product.id,
        "quantity_planned": 5,
    })
    eA.flush_recordset()
    Line.sudo().flush_model()
    EventJob.sudo().flush_model()
    env.cr.commit()
    # Run B2 engine so the conflict snapshot exists
    ConflictEngine(env).run_for_event(eA, trigger_reason="manual")


# ============================================================
# T-B4-05 .. 07 -- fact gatherer (REUSE of B3)
# ============================================================
if product:
    gatherer = SubhireRequestFactGatherer(env)
    facts = gatherer.gather(eA)
    _check("T-B4-05",
           facts["event_job"]["id"] == eA.id
           and "subhire_lines" in facts
           and "event_window_label" in facts,
           "facts shape: B3 keys + subhire_lines + window_label")
    sl = facts["subhire_lines"]
    _check("T-B4-06",
           len(sl) >= 1
           and all(ln["status"] in ("deficit", "zero_margin")
                   for ln in sl),
           f"subhire_lines filtered to deficit/zero_margin: "
           f"{[(l['product_name'], l['deficit_qty'], l['status']) for l in sl]}")
    _check("T-B4-07",
           facts["event_window_label"] == (
               eA.load_in_start.isoformat() + " -> "
               + eA.load_out_end.isoformat()),
           f"precise window label: {facts['event_window_label']!r}")
else:
    for t in (f"T-B4-{i:02d}" for i in range(5, 8)):
        _check(t, True, "no workshop product; skipped")


# ============================================================
# T-B4-08 -- generator refuses draft state events (B2-DM-2)
# ============================================================
mDraft = _mk_job("DRAFT", today + timedelta(days=21))
eDraft = EventJob.sudo().create({
    "name": "PB4 SMOKE EVT DRAFT",
    "commercial_job_id": mDraft.id,
    "partner_id": partner.id,
})  # leave in draft
try:
    SubhireRequestGenerator(env).generate_for_event(eDraft)
    raised = None
except Exception as exc:  # noqa: BLE001
    raised = type(exc).__name__
_check("T-B4-08",
       raised == "UserError",
       f"generator refuses state='draft' (B2-DM-2 mirror); "
       f"got={raised}")


# ============================================================
# T-B4-09 -- generator refuses when no deficits exist
# ============================================================
if product:
    mEmpty = _mk_job("EMPTY", today + timedelta(days=28))
    eEmpty = _mk_event("EMPTY", mEmpty)
    # No equipment lines -> zero deficits
    try:
        SubhireRequestGenerator(env).generate_for_event(eEmpty)
        raised = None
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    _check("T-B4-09",
           raised == "UserError",
           f"generator refuses zero-deficit events; got={raised}")
else:
    _check("T-B4-09", True, "no product; skipped")


# ============================================================
# T-B4-10 .. 17 -- validator strict rules
# ============================================================
if product and facts.get("subhire_lines"):
    validator = SubhireRequestValidator(facts)
    b2_ln = facts["subhire_lines"][0]

    def _good_draft():
        return {
            "enquiry_subject": "Sub-hire enquiry: "
                                + b2_ln["product_name"],
            "enquiry_body": (
                "We need to source the following items for an "
                "upcoming event. Please reply with availability "
                "and quote at your earliest convenience."),
            "line_briefs": [{
                "product_name": b2_ln["product_name"],
                "qty_short": b2_ln["deficit_qty"],
                "event_window": facts["event_window_label"],
                "competing_event_names": list(
                    b2_ln["competing_event_names"]),
                "brief": ("We are short of " + str(b2_ln["deficit_qty"])
                          + " units for the upcoming event."),
            }],
            "data_quality_note": facts["b2_conflict"].get(
                "data_quality_note"),
        }

    # baseline must pass
    try:
        validator.validate(_good_draft()); baseline = True
    except SubhireValidationError as exc:
        baseline = False
        print("  baseline failed:", exc)
    _check("T-B4-10", baseline, "baseline draft passes validator")

    # R4 -- omitted deficit
    bad = _good_draft(); bad["line_briefs"] = []
    try:
        validator.validate(bad); r4 = False
    except SubhireValidationError as exc:
        r4 = "R4" in str(exc)
    _check("T-B4-11", r4, "R4 omitted deficit -> reject")

    # R1 -- wrong qty
    bad = _good_draft()
    bad["line_briefs"][0]["qty_short"] = 99
    try:
        validator.validate(bad); r1 = False
    except SubhireValidationError as exc:
        r1 = "R1" in str(exc)
    _check("T-B4-12", r1, "R1 quantity hallucination -> reject")

    # R2 -- hallucinated product
    bad = _good_draft()
    bad["line_briefs"][0]["product_name"] = "FAKE PRODUCT"
    try:
        validator.validate(bad); r2 = False
    except SubhireValidationError as exc:
        # R4 may also trip (omitted real deficit). Either is OK
        # since the rule we care about catches it.
        r2 = ("R2" in str(exc)) or ("R4" in str(exc))
    _check("T-B4-13", r2,
           "R2 hallucinated product -> reject (R2 or R4)")

    # R3 -- hallucinated competing events
    bad = _good_draft()
    bad["line_briefs"][0]["competing_event_names"] = [
        "IMAGINARY EVENT"]
    try:
        validator.validate(bad); r3 = False
    except SubhireValidationError as exc:
        r3 = "R3" in str(exc)
    _check("T-B4-14", r3,
           "R3 hallucinated competing event -> reject")

    # R5 -- wrong event_window string
    bad = _good_draft()
    bad["line_briefs"][0]["event_window"] = (
        "not the right window")
    try:
        validator.validate(bad); r5 = False
    except SubhireValidationError as exc:
        r5 = "R5" in str(exc)
    _check("T-B4-15", r5,
           "R5 event_window mismatch -> reject")

    # R6 -- concrete datetime not in facts
    bad = _good_draft()
    bad["line_briefs"][0]["brief"] = (
        "Supply by 2099-12-31T23:59:00.")
    try:
        validator.validate(bad); r6 = False
    except SubhireValidationError as exc:
        r6 = "R6" in str(exc)
    _check("T-B4-16", r6,
           "R6 concrete datetime not in facts -> reject")

    # R6 split -- relative phrasing PASSES
    bad = _good_draft()
    bad["line_briefs"][0]["brief"] = (
        "Supply on the morning of the event, before load-in.")
    try:
        validator.validate(bad); r6_soft = True
    except SubhireValidationError as exc:
        r6_soft = False
        print("  r6_soft failed:", exc)
    _check("T-B4-17", r6_soft,
           "R6 relative phrasing PASSES (gate-1 (a) split)")
else:
    for t in (f"T-B4-{i:02d}" for i in range(10, 18)):
        _check(t, True, "no product/deficit; skipped")


# ============================================================
# T-B4-18 -- R7 data_quality_note mismatch
# ============================================================
if product and facts.get("subhire_lines"):
    bad = _good_draft()
    bad["data_quality_note"] = (
        "wrong text -- not what B2 said")
    try:
        validator.validate(bad); r7 = False
    except SubhireValidationError as exc:
        r7 = "R7" in str(exc)
    _check("T-B4-18", r7,
           "R7 data_quality_note mismatch -> reject")
else:
    _check("T-B4-18", True, "skipped")


# ============================================================
# T-B4-19 .. 22 -- generator routes to Claude via B13 (mocked)
# ============================================================
if product and facts.get("subhire_lines"):
    provider = Provider.sudo().search(
        [("provider_key", "=", "anthropic")], limit=1)
    if provider:
        provider._set_api_key("sk-ant-PB4-TEST-12345")
        provider.sudo().write({"is_enabled": True,
                                 "model": "claude-sonnet-4-6"})

    good_payload = _good_draft()
    mock_out = {
        "result": good_payload,
        "usage": {"prompt_tokens": 800,
                   "completion_tokens": 200},
        "model": "claude-sonnet-4-6",
        "latency_ms": 1100,
    }

    from odoo.addons.neon_doc_gen.models.ai_doc_gen import (
        claude_docgen_adapter as adapter_mod,
    )
    with patch.object(adapter_mod.ClaudeDocGenAdapter,
                       "generate",
                       return_value=mock_out) as m_gen:
        req = SubhireRequestGenerator(env).generate_for_event(eA)

    _check("T-B4-19",
           m_gen.called,
           "SubhireRequestGenerator called the Claude adapter")
    call_kwargs = m_gen.call_args.kwargs or {}
    _check("T-B4-20",
           "json_schema" in call_kwargs
           and "facts" in call_kwargs
           and "system_prompt" in call_kwargs,
           f"adapter called with json_schema + facts + system_prompt")
    _check("T-B4-21",
           req.status == "generated"
           and req.event_job_id.id == eA.id
           and req.revision == 1
           and req.model_used == "claude-sonnet-4-6"
           and req.prompt_tokens == 800
           and req.completion_tokens == 200
           and bool(req.draft_json),
           f"request persisted: status={req.status} "
           f"rev={req.revision}")
    _check("T-B4-22",
           len(req.line_ids) == 1
           and req.line_ids[0].qty_short == b2_ln["deficit_qty"]
           and req.line_ids[0].product_template_id.id == product.id,
           f"line persisted with qty_short={req.line_ids[0].qty_short}")


# ============================================================
# T-B4-23 -- design-seed lock end-to-end: omitting deficit
# triggers a retry then quarantine
# ============================================================
if product and facts.get("subhire_lines"):
    bad_payload = _good_draft()
    bad_payload["line_briefs"] = []
    bad_mock_out = {
        "result": bad_payload,
        "usage": {"prompt_tokens": 500,
                   "completion_tokens": 100},
        "model": "claude-sonnet-4-6", "latency_ms": 900,
    }
    with patch.object(adapter_mod.ClaudeDocGenAdapter,
                       "generate", return_value=bad_mock_out):
        try:
            SubhireRequestGenerator(env).generate_for_event(
                eA, replaces=req)
            raised_msg = None
        except Exception as exc:  # noqa: BLE001
            raised_msg = str(exc)
    _check("T-B4-23",
           raised_msg is not None
           and ("R4" in raised_msg
                or "omits" in raised_msg.lower()),
           f"orchestrator rejects omitted-deficit after retry; "
           f"err={(raised_msg or '')[:120]!r}")


# ============================================================
# T-B4-24 -- quarantine row persists bad output
# ============================================================
if product and facts.get("subhire_lines"):
    quar = Request.sudo().search([
        ("event_job_id", "=", eA.id),
        ("quarantine_json", "!=", False),
    ], order="id desc", limit=1)
    _check("T-B4-24",
           bool(quar) and quar.status == "draft"
           and bool(quar.quarantine_json),
           f"quarantined draft request: {bool(quar)}")


# ============================================================
# T-B4-25 -- review gate (generated -> reviewed) +
# approve requires supplier_partner_id
# ============================================================
if product and facts.get("subhire_lines"):
    req.action_mark_reviewed()
    req.invalidate_recordset(["status", "reviewed_at"])
    rev_ok = (req.status == "reviewed"
               and bool(req.reviewed_at))
    # Try to approve WITHOUT supplier -> should refuse
    try:
        req.action_approve_and_create_po()
        approve_without_supplier_blocked = False
    except Exception as exc:  # noqa: BLE001
        approve_without_supplier_blocked = "supplier" in str(
            exc).lower()
    _check("T-B4-25",
           rev_ok and approve_without_supplier_blocked,
           f"reviewed={rev_ok}; approve_blocked_without_supplier"
           f"={approve_without_supplier_blocked}")


# ============================================================
# T-B4-26 -- empty supplier set: has_supplier_candidates=False
# ============================================================
# Ensure no supplier partners exist for this test
existing_suppliers = Partner.sudo().search(
    [("supplier_rank", ">", 0)])
existing_supplier_ids = existing_suppliers.ids
existing_suppliers.sudo().write({"supplier_rank": 0})
req.invalidate_recordset(["has_supplier_candidates"])
_check("T-B4-26",
       req.has_supplier_candidates is False,
       "has_supplier_candidates = False when no supplier_rank>0 "
       "partners exist (drives the form's amber banner)")


# ============================================================
# T-B4-27 -- supplier dropdown candidate appears when added;
# Approve creates the PO in state='draft'
# ============================================================
if product and facts.get("subhire_lines"):
    supplier = Partner.sudo().create({
        "name": "PB4 SUPPLIER A",
        "is_company": True,
        "supplier_rank": 1,
    })
    req.invalidate_recordset(["has_supplier_candidates"])
    _check("T-B4-27a",
           req.has_supplier_candidates is True,
           "has_supplier_candidates flips True after vendor added")
    req.sudo().write({"supplier_partner_id": supplier.id})
    req.action_approve_and_create_po()
    req.invalidate_recordset(["status", "po_draft_id",
                                "approved_at"])
    po = req.po_draft_id
    _check("T-B4-27",
           req.status == "approved"
           and bool(po) and po.state == "draft"
           and po.partner_id.id == supplier.id
           and (po.origin or "").startswith("SUBHIRE-")
           and len(po.order_line) == 1
           and po.order_line[0].product_qty == float(
               b2_ln["deficit_qty"]),
           f"PO created: state={po.state if po else 'NONE'} "
           f"partner={po.partner_id.name if po else 'NONE'} "
           f"lines={len(po.order_line) if po else 0}")


# ============================================================
# T-B4-28 -- "Mark Sent" is metadata; does NOT touch PO state
# ============================================================
if product and facts.get("subhire_lines"):
    po_state_before = req.po_draft_id.state
    req.action_mark_sent()
    req.invalidate_recordset(["status", "sent_at"])
    req.po_draft_id.invalidate_recordset(["state"])
    po_state_after = req.po_draft_id.state
    _check("T-B4-28",
           req.status == "sent"
           and bool(req.sent_at)
           and po_state_before == "draft"
           and po_state_after == "draft",
           f"request='sent'; PO state stayed 'draft' "
           f"(before={po_state_before} after={po_state_after})")


# ============================================================
# T-B4-29 -- regenerate BLOCKED while sent
# ============================================================
if product and facts.get("subhire_lines"):
    try:
        req.action_regenerate()
        blocked = False
    except Exception as exc:  # noqa: BLE001
        blocked = "un-send" in str(exc).lower()
    _check("T-B4-29", blocked,
           "regenerate blocked on sent request")


# ============================================================
# T-B4-30 -- un-send + regenerate spawns new revision +
# supersedes prior
# ============================================================
if product and facts.get("subhire_lines"):
    req.action_unsend()
    with patch.object(adapter_mod.ClaudeDocGenAdapter,
                       "generate", return_value=mock_out):
        new_act = req.action_regenerate()
    new_req = Request.sudo().browse(new_act["res_id"])
    req.invalidate_recordset(["status",
                                "superseded_by_request_id"])
    _check("T-B4-30",
           new_req.revision > req.revision
           and req.status == "superseded"
           and req.superseded_by_request_id.id == new_req.id,
           f"new rev={new_req.revision} > prior {req.revision}; "
           f"old status={req.status}")


# ============================================================
# T-B4-31 -- HTML render contains the deficit-line table
# ============================================================
if product and facts.get("subhire_lines"):
    html_out = new_req.plan_summary_html if (
        "plan_summary_html" in new_req._fields) else (
        new_req.draft_summary_html or "")
    _check("T-B4-31",
           "Sub-hire" in html_out or "sub-hire" in html_out.lower()
           or "subhire" in html_out.lower(),
           f"draft_summary_html renders content; "
           f"len={len(html_out)}")


# ============================================================
# T-B4-32 -- exactly ONE PO per request (single supplier per request)
# ============================================================
if product and facts.get("subhire_lines"):
    pos = PO.sudo().search([("origin", "=", req.name)])
    _check("T-B4-32",
           len(pos) == 1 and pos[0].state == "draft",
           f"exactly 1 PO per request (D6); count={len(pos)} "
           f"state={pos[0].state if pos else 'NONE'}")


# ============================================================
# Cleanup -- order matters (FK chain):
# requests -> POs -> events -> jobs -> units -> conflict
# -> suppliers -> product
# ============================================================
Request.sudo().search([]).unlink()
pb4_pos = PO.sudo().search([("origin", "=like", "SUBHIRE-%")])
if pb4_pos:
    pb4_pos.button_cancel()
    pb4_pos.unlink()
to_cancel = EventJob.sudo().search(
    [("name", "=like", "PB4 SMOKE EVT%")])
if to_cancel:
    to_cancel.with_context(_allow_state_write=True).write(
        {"state": "cancelled"})
    to_cancel.unlink()
Job.sudo().search([("name", "=like", "PB4 SMOKE JOB%")]).unlink()
Unit.sudo().search(
    [("serial_number", "=like", "PB4-SMK-%")]).unlink()
Conflict.sudo().search([("name", "=like", "CONF-%")]).unlink()
Partner.sudo().search(
    [("name", "=like", "PB4 SUPPLIER%")]).unlink()
Product.sudo().search(
    [("name", "=", "PB4-SMK-PRODUCT")]).unlink()
# Restore the supplier_rank we wiped at T-B4-26
if existing_supplier_ids:
    Partner.sudo().browse(existing_supplier_ids).write(
        {"supplier_rank": 1})
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
