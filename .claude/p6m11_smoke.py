"""P6.M11 smoke -- workshop write-off integration via incident.

Hook mechanism (T2300-T2305):
T2300  action_resolve_writeoff auto-creates cost.line
T2301  other resolution paths (recovered, claim, cancel) do NOT create
T2302  cost.line.cost_type = 'write_off'
T2303  cost.line.amount = incident.estimated_loss_value
T2304  source_movement_id populated from incident.source_checkin_movement_id
T2305  UserError when source_event_job_id absent

is_client_caused (T2310-T2314):
T2310  is_client_caused=True persists
T2311  client-caused -> event_job.pending_cost_recovery=True
T2312  is_client_caused=False keeps pending_cost_recovery=False
T2313  backwards-compatible call (no is_client_caused kwarg)
T2314  is_client_caused tracked via mail.thread

Cost recovery wizard (T2320-T2326):
T2320  approver can open wizard
T2321  sales rep AccessError on action_open_cost_recovery_wizard
T2322  default amount = cost.line.amount x 1.10 (USD-to-USD case)
T2323  default currency = event_job's quote currency
T2324  confirm creates account.move out_invoice
T2325  invoice.ref = "RECOV-<incident.name>"
T2326  pending_cost_recovery=False after invoice creation

Notification dispatch (T2330-T2332):
T2330  mail.activity TODO dispatched to bookkeeper + approver on auto-cost.line
T2331  self-suppression for resolver in approver group
T2332  skip_finance_notification context suppresses dispatch

ACL + invariants (T2333-T2335):
T2333  manager can resolve writeoff
T2334  non-manager AccessError on action_resolve_writeoff
T2335  cost.line perm_unlink=0 (M5 invariant survives M11)

Currency handling (T2340-T2341):
T2340  USD-incident cost.line in USD
T2341  ZWG-quoted event recovery invoice in ZWG (conversion via neon rate)

Audit + idempotency (T2342-T2344):
T2342  source_movement_id resolves back to incident's check-in movement
T2343  chatter posts on event_job + incident on cost.line creation
T2344  idempotency: re-resolving same incident doesn't create duplicate
"""
import re
from datetime import date, timedelta

from odoo.exceptions import AccessError, UserError


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Incident = env["neon.equipment.incident"]
Movement = env["neon.equipment.movement"]
Unit = env["neon.equipment.unit"]
Cost = env["neon.finance.cost.line"]
EventJob = env["commercial.event.job"]
Quote = env["neon.finance.quote"]
QuoteLine = env["neon.finance.quote.line"]
Sched = env["neon.finance.invoice.schedule"]
Term = env["neon.finance.payment.term"]
Wizard = env["neon.finance.cost.recovery.wizard"]
Move = env["account.move"]
Rate = env["neon.finance.conversion.rate"]

usd = env.ref("base.USD")
zwg = env.ref("neon_finance.currency_zwg")

sales_user = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
book_user = env["res.users"].search([("login", "=", "p2m75_book")], limit=1)
approver_user = env["res.users"].search(
    [("login", "=", "p2m75_approver")], limit=1)
mgr_user = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
lead_user = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
assert all([sales_user, book_user, approver_user, mgr_user, lead_user])

approver_group = env.ref("neon_finance.group_neon_finance_approver")
book_group = env.ref("neon_finance.group_neon_finance_bookkeeper")
mgr_group = env.ref("neon_jobs.group_neon_jobs_manager")

venue = env["res.partner"].create({
    "name": "P6M11 Venue", "is_company": True,
})


def _new_event_job(currency=usd, sp=None, partner=None):
    """Build an event_job with an accepted quote so currency lookup
    in the wizard finds something."""
    sp = sp or sales_user
    p = partner or env["res.partner"].create({
        "name": "P6M11 Client " + currency.name,
        "is_company": True,
    })
    term = Term.create({
        "partner_id": p.id, "deposit_pct": 50.0,
        "deposit_due_days": 0, "final_due_days": 30,
        "late_policy": "reminder",
    })
    j = env["commercial.job"].create({
        "partner_id": p.id, "venue_id": venue.id,
        "event_date": date.today() + timedelta(days=30),
        "currency_id": currency.id,
    })
    ej = EventJob.create({
        "commercial_job_id": j.id,
        "lead_tech_id": lead_user.id,
    })
    # Accepted quote so wizard's quote-currency lookup succeeds
    q = Quote.create({
        "event_job_id": ej.id, "salesperson_id": sp.id,
        "currency_id": currency.id, "payment_term_id": term.id,
    })
    QuoteLine.create({
        "quote_id": q.id, "line_type": "other",
        "name": "P6M11", "quantity": 1, "duration_days": 1,
        "unit_rate": 1000.0, "pricing_status": "manual",
    })
    Sched.create({
        "quote_id": q.id, "sequence": 1, "stage": "deposit",
        "trigger": "on_acceptance", "percentage": 100.0,
        "currency_id": currency.id,
    })
    q.sudo().write({"state": "sent"})
    q.sudo().with_user(sp).action_accept()
    return ej


_unit_counter = [0]
_workshop_product = env["product.template"].search(
    [("is_workshop_item", "=", True)], limit=1)
assert _workshop_product, "test prerequisite: at least one workshop product"


def _new_unit():
    """Build an active equipment unit. Stamp serial number to
    satisfy serial-tracked product constraints."""
    _unit_counter[0] += 1
    vals = {
        "name": "P6M11 unit " + str(_unit_counter[0]),
        "product_template_id": _workshop_product.id,
        "serial_number": "P6M11-SN-%d" % _unit_counter[0],
        "state": "draft",
    }
    u = Unit.create(vals)
    u._do_transition("active")
    return u


def _new_incident(event_job, loss_value=400.0, with_movement=True):
    """Build an open incident attached to event_job."""
    unit = _new_unit()
    movement = False
    if with_movement:
        movement = Movement.create({
            "unit_id": unit.id, "event_job_id": event_job.id,
            "movement_type": "checkin",
            "condition_at_event": "missing",
            "actor_id": lead_user.id,
        })
    inc = Incident.create({
        "unit_id": unit.id,
        "incident_type": "accident",
        "source_event_job_id": event_job.id,
        "source_checkin_movement_id": movement.id if movement else False,
        "description": "P6M11 accident",
        "estimated_loss_value": loss_value,
        "currency_id": usd.id,
    })
    # Walk to under_investigation so writeoff transition is allowed
    inc.action_investigate()
    return inc


# ============================================================
print()
print("=" * 72)
print("T2300 - action_resolve_writeoff auto-creates cost.line")
print("=" * 72)
ej_t2300 = _new_event_job()
inc_t2300 = _new_incident(ej_t2300, loss_value=400.0)
before = Cost.search_count([("event_job_id", "=", ej_t2300.id)])
inc_t2300.with_user(mgr_user).action_resolve_writeoff(reason="test")
after = Cost.search_count([("event_job_id", "=", ej_t2300.id)])
ok = after - before == 1
print("  before:", before, "after:", after)
print("T2300:", "PASS" if ok else "FAIL")
results["T2300"] = ok


# ============================================================
print()
print("=" * 72)
print("T2301 - other resolution paths do NOT create cost.line")
print("=" * 72)
ej_t2301 = _new_event_job()
inc_t2301 = _new_incident(ej_t2301, loss_value=200.0)
before = Cost.search_count([("event_job_id", "=", ej_t2301.id)])
inc_t2301.with_user(mgr_user).action_resolve_recovered()
after = Cost.search_count([("event_job_id", "=", ej_t2301.id)])
ok = after == before
print("  before:", before, "after:", after)
print("T2301:", "PASS" if ok else "FAIL")
results["T2301"] = ok


# ============================================================
print()
print("=" * 72)
print("T2302 - cost.line.cost_type = 'write_off'")
print("=" * 72)
cl_t2300 = Cost.search([("event_job_id", "=", ej_t2300.id),
                        ("cost_type", "=", "write_off")], limit=1)
ok = bool(cl_t2300) and cl_t2300.cost_type == "write_off"
print("  cost_type:", cl_t2300.cost_type if cl_t2300 else None)
print("T2302:", "PASS" if ok else "FAIL")
results["T2302"] = ok


# ============================================================
print()
print("=" * 72)
print("T2303 - cost.line.amount = incident.estimated_loss_value")
print("=" * 72)
ok = cl_t2300 and abs(cl_t2300.amount - 400.0) < 0.01
print("  amount:", cl_t2300.amount if cl_t2300 else None)
print("T2303:", "PASS" if ok else "FAIL")
results["T2303"] = ok


# ============================================================
print()
print("=" * 72)
print("T2304 - source_movement_id populated")
print("=" * 72)
ok = cl_t2300 and bool(cl_t2300.source_movement_id)
print("  source_movement_id:",
      cl_t2300.source_movement_id.id if cl_t2300 and cl_t2300.source_movement_id else None)
print("T2304:", "PASS" if ok else "FAIL")
results["T2304"] = ok


# ============================================================
print()
print("=" * 72)
print("T2305 - graceful skip when source_event_job_id absent")
print("=" * 72)
unit_t2305 = _new_unit()
inc_t2305 = Incident.create({
    "unit_id": unit_t2305.id,
    "incident_type": "loss",
    # NO source_event_job_id
    "description": "P6M11 no event",
    "estimated_loss_value": 100.0,
    "currency_id": usd.id,
})
inc_t2305.action_investigate()
costs_before = Cost.search_count([])
# Should NOT raise; should skip cost.line creation and log.
err, _ = _try(lambda: inc_t2305.with_user(mgr_user).action_resolve_writeoff())
costs_after = Cost.search_count([])
inc_t2305.invalidate_recordset()
ok = (err is None
      and inc_t2305.state == "resolved_writeoff"
      and costs_after == costs_before)
print("  err:", err, "state:", inc_t2305.state,
      "costs delta:", costs_after - costs_before)
print("T2305:", "PASS" if ok else "FAIL")
results["T2305"] = ok


# ============================================================
print()
print("=" * 72)
print("T2310 - is_client_caused=True persists")
print("=" * 72)
ej_t2310 = _new_event_job()
inc_t2310 = _new_incident(ej_t2310)
inc_t2310.with_user(mgr_user).action_resolve_writeoff(
    is_client_caused=True)
inc_t2310.invalidate_recordset()
ok = inc_t2310.is_client_caused is True
print("  is_client_caused:", inc_t2310.is_client_caused)
print("T2310:", "PASS" if ok else "FAIL")
results["T2310"] = ok


# ============================================================
print()
print("=" * 72)
print("T2311 - client-caused -> event_job.pending_cost_recovery=True")
print("=" * 72)
ej_t2310.invalidate_recordset()
ok = ej_t2310.pending_cost_recovery is True
print("  pending_cost_recovery:", ej_t2310.pending_cost_recovery)
print("T2311:", "PASS" if ok else "FAIL")
results["T2311"] = ok


# ============================================================
print()
print("=" * 72)
print("T2312 - non-client-caused keeps pending_cost_recovery=False")
print("=" * 72)
ej_t2300.invalidate_recordset()
# T2300 incident was resolved WITHOUT is_client_caused kwarg
ok = ej_t2300.pending_cost_recovery is False
print("  pending_cost_recovery:", ej_t2300.pending_cost_recovery)
print("T2312:", "PASS" if ok else "FAIL")
results["T2312"] = ok


# ============================================================
print()
print("=" * 72)
print("T2313 - backwards-compatible call (no is_client_caused kwarg)")
print("=" * 72)
# T2300's call was action_resolve_writeoff(reason='test') with no
# is_client_caused. If it worked + created cost.line (T2300 passed),
# backwards compat is proven.
ok = results.get("T2300") is True
print("  T2300 confirmed:", ok)
print("T2313:", "PASS" if ok else "FAIL")
results["T2313"] = ok


# ============================================================
print()
print("=" * 72)
print("T2314 - is_client_caused tracked via mail.thread")
print("=" * 72)
# tracking=True on the field means change is logged in chatter
# Field-level tracking metadata: tracking=True on the field def.
field_meta = inc_t2310._fields.get("is_client_caused")
ok = bool(field_meta) and bool(field_meta.tracking)
print("  field tracking:", field_meta.tracking if field_meta else None)
print("T2314:", "PASS" if ok else "FAIL")
results["T2314"] = ok


# ============================================================
print()
print("=" * 72)
print("T2320 - approver can open wizard")
print("=" * 72)
descr = ej_t2310.with_user(approver_user).action_open_cost_recovery_wizard()
ok = (descr.get("type") == "ir.actions.act_window"
      and descr.get("res_model") == "neon.finance.cost.recovery.wizard")
print("  descriptor:", descr.get("type"), descr.get("res_model"))
print("T2320:", "PASS" if ok else "FAIL")
results["T2320"] = ok


# ============================================================
print()
print("=" * 72)
print("T2321 - sales rep AccessError on wizard")
print("=" * 72)
err, _ = _try(lambda: ej_t2310.with_user(
    sales_user).action_open_cost_recovery_wizard())
ok = isinstance(err, AccessError)
print("  err:", type(err).__name__ if err else "None")
print("T2321:", "PASS" if ok else "FAIL")
results["T2321"] = ok


# ============================================================
print()
print("=" * 72)
print("T2322 - default amount = cost.line.amount x 1.10")
print("=" * 72)
wiz_t2322 = Wizard.with_user(approver_user).with_context(
    default_event_job_id=ej_t2310.id).create({})
# T2310 incident: 400 USD; event_job currency is USD too;
# handling 10% -> amount = 400 * 1.10 = 440
ok = abs(wiz_t2322.amount - 440.0) < 0.01
print("  amount:", wiz_t2322.amount)
print("T2322:", "PASS" if ok else "FAIL")
results["T2322"] = ok


# ============================================================
print()
print("=" * 72)
print("T2323 - default currency = event_job's quote currency")
print("=" * 72)
ok = wiz_t2322.currency_id.id == usd.id
print("  wizard currency:", wiz_t2322.currency_id.name)
print("T2323:", "PASS" if ok else "FAIL")
results["T2323"] = ok


# ============================================================
print()
print("=" * 72)
print("T2324 - confirm creates account.move out_invoice")
print("=" * 72)
moves_before = Move.search_count([("ref", "like", "RECOV-")])
wiz_t2322.action_create_recovery_invoice()
moves_after = Move.search_count([("ref", "like", "RECOV-")])
ok = moves_after - moves_before == 1
print("  moves created:", moves_after - moves_before)
print("T2324:", "PASS" if ok else "FAIL")
results["T2324"] = ok


# ============================================================
print()
print("=" * 72)
print("T2325 - invoice.ref = 'RECOV-<incident.name>'")
print("=" * 72)
move_t2324 = Move.search([
    ("ref", "like", "RECOV-"),
    ("partner_id", "=", ej_t2310.partner_id.id),
], order="id desc", limit=1)
expected_ref = "RECOV-" + inc_t2310.name
ok = move_t2324 and move_t2324.ref == expected_ref
print("  invoice.ref:", move_t2324.ref if move_t2324 else None,
      "expected:", expected_ref)
print("T2325:", "PASS" if ok else "FAIL")
results["T2325"] = ok


# ============================================================
print()
print("=" * 72)
print("T2326 - pending_cost_recovery=False after invoice creation")
print("=" * 72)
ej_t2310.invalidate_recordset()
ok = ej_t2310.pending_cost_recovery is False
print("  pending_cost_recovery:", ej_t2310.pending_cost_recovery)
print("T2326:", "PASS" if ok else "FAIL")
results["T2326"] = ok


# ============================================================
print()
print("=" * 72)
print("T2330 - mail.activity dispatched to bookkeeper + approver")
print("=" * 72)
# Cost.line auto-create dispatches via M5 _notify_finance_oversight.
# T2300's cost.line should have activities for book + approver
# (manager mgr_user is NOT in those groups -> no self-suppression).
acts = env["mail.activity"].search([
    ("res_model", "=", "neon.finance.cost.line"),
    ("res_id", "=", cl_t2300.id),
])
user_logins = set(acts.mapped("user_id.login"))
ok = "p2m75_book" in user_logins and "p2m75_approver" in user_logins
print("  activity users:", user_logins)
print("T2330:", "PASS" if ok else "FAIL")
results["T2330"] = ok


# ============================================================
print()
print("=" * 72)
print("T2331 - self-suppression for resolver in approver group")
print("=" * 72)
# Have approver_user also carry the manager group so they can resolve
# writeoff. Then resolve as approver -> approver TODO should NOT
# fire on the cost.line.
approver_user.sudo().write({"groups_id": [(4, mgr_group.id)]})
ej_t2331 = _new_event_job()
inc_t2331 = _new_incident(ej_t2331, loss_value=150.0)
inc_t2331.with_user(approver_user).action_resolve_writeoff(
    reason="test self-suppress")
cl_t2331 = Cost.search([("event_job_id", "=", ej_t2331.id),
                        ("cost_type", "=", "write_off")], limit=1)
acts_t2331 = env["mail.activity"].search([
    ("res_model", "=", "neon.finance.cost.line"),
    ("res_id", "=", cl_t2331.id),
])
approver_act = acts_t2331.filtered(
    lambda a: a.user_id.id == approver_user.id)
# Approver was the recorder; should NOT get a TODO
ok = not approver_act
print("  approver activities:", len(approver_act))
print("T2331:", "PASS" if ok else "FAIL")
results["T2331"] = ok


# ============================================================
print()
print("=" * 72)
print("T2332 - skip_finance_notification context suppresses dispatch")
print("=" * 72)
# Direct cost.line create with skip context (separate from the
# incident path which doesn't pass this flag).
ej_t2332 = _new_event_job()
cl_t2332 = Cost.with_context(skip_finance_notification=True).create({
    "event_job_id": ej_t2332.id, "cost_type": "other",
    "name": "P6M11 skip test", "amount": 50.0,
    "currency_id": usd.id, "date_incurred": date.today(),
    "recorded_by_id": lead_user.id,
})
acts_t2332 = env["mail.activity"].search_count([
    ("res_model", "=", "neon.finance.cost.line"),
    ("res_id", "=", cl_t2332.id),
])
ok = acts_t2332 == 0
print("  activities:", acts_t2332)
print("T2332:", "PASS" if ok else "FAIL")
results["T2332"] = ok


# ============================================================
print()
print("=" * 72)
print("T2333 - manager can resolve writeoff")
print("=" * 72)
# T2300 already exercised this (mgr_user). Confirm via the result.
ok = results.get("T2300") is True
print("  mgr can resolve:", ok)
print("T2333:", "PASS" if ok else "FAIL")
results["T2333"] = ok


# ============================================================
print()
print("=" * 72)
print("T2334 - non-manager AccessError on action_resolve_writeoff")
print("=" * 72)
ej_t2334 = _new_event_job()
inc_t2334 = _new_incident(ej_t2334)
err, _ = _try(lambda: inc_t2334.with_user(
    sales_user).action_resolve_writeoff())
ok = isinstance(err, (AccessError, UserError))
print("  err:", type(err).__name__ if err else "None")
print("T2334:", "PASS" if ok else "FAIL")
results["T2334"] = ok


# ============================================================
print()
print("=" * 72)
print("T2335 - cost.line perm_unlink=0 (M5 invariant)")
print("=" * 72)
acl_rows = env["ir.model.access"].search([
    ("model_id.model", "=", "neon.finance.cost.line"),
])
ok = all(r.perm_unlink is False for r in acl_rows)
print("  rows:", len(acl_rows), "all no-unlink:", ok)
print("T2335:", "PASS" if ok else "FAIL")
results["T2335"] = ok


# ============================================================
print()
print("=" * 72)
print("T2340 - USD-incident cost.line in USD")
print("=" * 72)
ok = cl_t2300 and cl_t2300.currency_id.id == usd.id
print("  cost.line currency:", cl_t2300.currency_id.name if cl_t2300 else None)
print("T2340:", "PASS" if ok else "FAIL")
results["T2340"] = ok


# ============================================================
print()
print("=" * 72)
print("T2341 - ZWG event recovery invoice converts via neon rate")
print("=" * 72)
# Ensure a USD<->ZWG conversion rate exists
existing_rate = Rate.search([], order="effective_date desc", limit=1)
if not existing_rate:
    Rate.create({
        "effective_date": date.today() - timedelta(days=1),
        "usd_per_zig": 0.04,
        "zig_per_usd": 25.0,
    })
# Build a ZWG-quoted event with a USD incident
ej_t2341 = _new_event_job(currency=zwg)
inc_t2341 = _new_incident(ej_t2341, loss_value=100.0)  # USD incident
inc_t2341.with_user(mgr_user).action_resolve_writeoff(
    is_client_caused=True)
wiz_t2341 = Wizard.with_user(approver_user).with_context(
    default_event_job_id=ej_t2341.id).create({})
# Expected: 100 USD * conversion + 10% handling = N ZWG
# We just verify the currency is ZWG and the amount is converted
# (not equal to 110 USD).
ok = (wiz_t2341.currency_id.id == zwg.id
      and wiz_t2341.amount > 110.0)  # ZWG amount must be larger than USD
print("  wizard currency:", wiz_t2341.currency_id.name,
      "amount:", wiz_t2341.amount)
print("T2341:", "PASS" if ok else "FAIL")
results["T2341"] = ok


# ============================================================
print()
print("=" * 72)
print("T2342 - source_movement_id resolves back to incident's check-in")
print("=" * 72)
ok = (cl_t2300.source_movement_id
      and cl_t2300.source_movement_id.id
      == inc_t2300.source_checkin_movement_id.id)
print("  cost.source_movement:",
      cl_t2300.source_movement_id.id if cl_t2300.source_movement_id else None,
      "incident.source_checkin:",
      inc_t2300.source_checkin_movement_id.id
      if inc_t2300.source_checkin_movement_id else None)
print("T2342:", "PASS" if ok else "FAIL")
results["T2342"] = ok


# ============================================================
print()
print("=" * 72)
print("T2343 - chatter posts on event_job + incident")
print("=" * 72)
ej_msgs = ej_t2300.message_ids.filtered(
    lambda m: "Write-off cost recorded from incident" in (m.body or ""))
inc_msgs = inc_t2300.message_ids.filtered(
    lambda m: "Cost line" in (m.body or "")
              and "created" in (m.body or ""))
ok = bool(ej_msgs) and bool(inc_msgs)
print("  event_job msgs:", len(ej_msgs), "incident msgs:", len(inc_msgs))
print("T2343:", "PASS" if ok else "FAIL")
results["T2343"] = ok


# ============================================================
print()
print("=" * 72)
print("T2344 - idempotency: re-resolve doesn't duplicate cost.line")
print("=" * 72)
# inc_t2300 is already resolved_writeoff; can't re-resolve via the
# state machine. But the _neon_finance_create_writeoff_cost_line
# helper checks for existing cost.line and skips. Call the helper
# directly to simulate a re-trigger.
before = Cost.search_count([
    ("event_job_id", "=", ej_t2300.id),
    ("cost_type", "=", "write_off"),
])
inc_t2300.sudo()._neon_finance_create_writeoff_cost_line(
    is_client_caused=False)
after = Cost.search_count([
    ("event_job_id", "=", ej_t2300.id),
    ("cost_type", "=", "write_off"),
])
ok = before == after
print("  before:", before, "after:", after)
print("T2344:", "PASS" if ok else "FAIL")
results["T2344"] = ok


# ============================================================
# ============================================================
# Phase F walkthrough Y (Robin 20 May 2026): sales tier sees
# event_jobs they own a quote on. Reverses M11 polish-item-Y
# narrower-scope decision.
# ============================================================
print()
print("=" * 72)
print("T2350 - Y: sales tier reads event_job via own quote chain")
print("=" * 72)
# sales_user already exists as a fixture from upstream M11 tests.
# Verify they can read the event_job linked to their own quote.
# Use the most recently created quote in this smoke run for the
# linkage (any quote created in M11 setup will do).
EventJob = env["commercial.event.job"]
own_job_ids = EventJob.with_user(sales_user).search([]).ids
# We don't pin a specific count -- just assert sales_user sees
# something (the M11 fixture creates quotes for sales_user as
# salesperson, so at least one event_job should be visible via
# the new rule).
ok = len(own_job_ids) >= 1
print("  event_jobs visible to sales_user:", len(own_job_ids))
print("T2350:", "PASS" if ok else "FAIL")
results["T2350"] = ok


# ============================================================
print()
print("=" * 72)
print("T2351 - Y: sales tier read is SCOPED (cannot see other reps' event_jobs)")
print("=" * 72)
# Get the full set of event_jobs via superuser and the scoped set
# via sales_user. The diff must be non-empty -- there must exist at
# least one event_job that sales_user cannot see (one whose linked
# quotes have a different salesperson). If every event_job has at
# least one quote owned by sales_user the scope is degenerate; skip
# with a note rather than fail.
all_job_ids = set(EventJob.sudo().search([]).ids)
sales_visible = set(EventJob.with_user(sales_user).search([]).ids)
not_visible = all_job_ids - sales_visible
ok = len(not_visible) >= 1
print("  total event_jobs:", len(all_job_ids),
      "; visible to sales:", len(sales_visible),
      "; hidden from sales:", len(not_visible))
print("T2351:", "PASS" if ok else "FAIL")
results["T2351"] = ok


print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in (
    2300, 2301, 2302, 2303, 2304, 2305,
    2310, 2311, 2312, 2313, 2314,
    2320, 2321, 2322, 2323, 2324, 2325, 2326,
    2330, 2331, 2332,
    2333, 2334, 2335,
    2340, 2341,
    2342, 2343, 2344,
    2350, 2351,
)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
