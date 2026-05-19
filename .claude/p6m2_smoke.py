"""P6.M2 smoke -- quote model + state machine + payment terms.

T600  quote create stamps QUO-USD- sequence
T601  quote create with ZWG currency stamps QUO-ZIG- sequence
T602  quote create defaults currency_id to USD
T603  quote create defaults expires_at to today+30
T604  quote create defaults state='draft'
T605  quote currency_id change after create -> UserError
T606  quote unsupported currency -> ValidationError
T607  quote partner_id related field populated from event_job
T608  quote.line create success
T609  quote.line quantity > 0 sql constraint
T610  quote.line duration_days >= 1 sql constraint
T611  quote.line unit_rate >= 0 sql constraint
T612  quote.line line_subtotal = qty * rate * days
T613  quote.line line_total_taxed applies tax via account.tax.compute_all
T614  quote.line line_margin = subtotal - cost
T615  quote.line equipment_line_id on non-equipment type -> ValidationError
T616  quote amount_untaxed = sum of line subtotals
T617  quote amount_total = sum of taxed totals
T618  quote margin_pct = margin_total / amount_untaxed * 100
T619  action_submit_for_approval from draft (with lines + term) -> auto-approved
T620  action_submit_for_approval without lines -> UserError
T621  action_submit_for_approval without payment_term -> UserError
T622  action_submit_for_approval from non-draft state -> UserError
T623  action_approve from pending_approval with approver group -> success
T624  action_approve from non-pending state -> UserError
T625  action_approve without approver group -> AccessError
T626  action_reject with reason + approver group -> success
T627  action_reject without reason in context -> UserError
T628  action_reject without approver group -> AccessError
T629  action_send from approved by salesperson -> success
T630  action_accept from sent -> success
T631  action_cancel from any non-terminal with reason -> success
T632  action_cancel from terminal -> UserError
T633  action_cancel without reason -> UserError
T634  _cron_expire_quotes transitions sent + expired_at < today
T635  payment_term name auto-compute populates from inputs
T636  ir.rule: sales sees own quotes only (not other salesperson's)
T637  ir.rule: bookkeeper sees all quotes (cross-salesperson)
T638  CSV: no perm_unlink on quote for any of the three roles
"""
from datetime import date, datetime, timedelta

from odoo.exceptions import AccessError, UserError, ValidationError
from psycopg2 import IntegrityError


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

Quote = env["neon.finance.quote"]
QuoteLine = env["neon.finance.quote.line"]
Term = env["neon.finance.payment.term"]

usd = env.ref("base.USD")
zwg = env.ref("neon_finance.currency_zwg")

# Required test users -- created by p2m7_5_smoke.py (persistent).
sales_user = env["res.users"].search(
    [("login", "=", "p2m75_sales")], limit=1)
mgr_user = env["res.users"].search(
    [("login", "=", "p2m75_mgr")], limit=1)
book_user = env["res.users"].search(
    [("login", "=", "p2m75_book")], limit=1)
approver_user = env["res.users"].search(
    [("login", "=", "p2m75_approver")], limit=1)
other_user = env["res.users"].search(
    [("login", "=", "p2m75_other")], limit=1)
assert all([sales_user, mgr_user, book_user, approver_user, other_user]), (
    "Need p2m75_* seed users (p2m7_5_smoke.py).")

# Minimal commercial.job + commercial.event.job fixture chain.
partner = env["res.partner"].create({
    "name": "P6M2 Smoke Client", "is_company": True,
})
venue = env["res.partner"].create({
    "name": "P6M2 Smoke Venue", "is_company": True,
})
job = env["commercial.job"].create({
    "partner_id": partner.id,
    "venue_id": venue.id,
    "event_date": date.today() + timedelta(days=30),
    "currency_id": usd.id,
})
event_job = env["commercial.event.job"].create({
    "commercial_job_id": job.id,
})

# A second salesperson + event_job for the record-rule scope tests
# (T636) -- without this we can't prove a sales rep *can't* see a
# colleague's quote.
other_sales = env["res.users"].create({
    "login": "p6m2_smoke_sales2",
    "name": "P6M2 Smoke Sales 2",
    "groups_id": [(6, 0, [
        env.ref("base.group_user").id,
        env.ref("neon_jobs.group_neon_jobs_user").id,
        env.ref("neon_finance.group_neon_finance_sales").id,
    ])],
})

term = Term.create({
    "partner_id": partner.id,
    "deposit_pct": 50.0,
    "deposit_due_days": 0,
    "final_due_days": 30,
    "late_policy": "reminder",
})


# ============================================================
print()
print("=" * 72)
print("T600 - quote create stamps QUO-USD- sequence")
print("=" * 72)
err, q_t600 = _try(lambda: Quote.create({
    "event_job_id": event_job.id,
    "currency_id": usd.id,
    "salesperson_id": sales_user.id,
}))
ok = err is None and bool(q_t600) and q_t600.name.startswith("QUO-USD-")
print("  err:", type(err).__name__ if err else None,
      "name:", q_t600.name if q_t600 else None)
print("T600:", "PASS" if ok else "FAIL")
results["T600"] = ok


# ============================================================
print()
print("=" * 72)
print("T601 - quote create with ZWG currency stamps QUO-ZIG- sequence")
print("=" * 72)
err, q_t601 = _try(lambda: Quote.create({
    "event_job_id": event_job.id,
    "currency_id": zwg.id,
    "salesperson_id": sales_user.id,
}))
ok = err is None and bool(q_t601) and q_t601.name.startswith("QUO-ZIG-")
print("  name:", q_t601.name if q_t601 else None)
print("T601:", "PASS" if ok else "FAIL")
results["T601"] = ok


# ============================================================
print()
print("=" * 72)
print("T602 - quote create defaults currency_id to USD")
print("=" * 72)
err, q_t602 = _try(lambda: Quote.create({
    "event_job_id": event_job.id,
    "salesperson_id": sales_user.id,
}))
ok = err is None and bool(q_t602) and q_t602.currency_id == usd
print("  currency:", q_t602.currency_id.name if q_t602 else None)
print("T602:", "PASS" if ok else "FAIL")
results["T602"] = ok


# ============================================================
print()
print("=" * 72)
print("T603 - quote create defaults expires_at to today+30")
print("=" * 72)
expected = date.today() + timedelta(days=30)
ok = q_t602.expires_at == expected
print("  expires_at:", q_t602.expires_at, "expected:", expected)
print("T603:", "PASS" if ok else "FAIL")
results["T603"] = ok


# ============================================================
print()
print("=" * 72)
print("T604 - quote create defaults state='draft'")
print("=" * 72)
ok = q_t602.state == "draft"
print("  state:", q_t602.state)
print("T604:", "PASS" if ok else "FAIL")
results["T604"] = ok


# ============================================================
print()
print("=" * 72)
print("T605 - quote currency_id change after create -> UserError")
print("=" * 72)
err, _ = _try(lambda: q_t602.write({"currency_id": zwg.id}))
ok = isinstance(err, UserError)
print("  err:", type(err).__name__ if err else None)
print("T605:", "PASS" if ok else "FAIL")
results["T605"] = ok


# ============================================================
print()
print("=" * 72)
print("T606 - quote unsupported currency -> ValidationError")
print("=" * 72)
# Find ANY currency that isn't USD or ZWG. active_test=False so we
# match inactive currencies too (EUR + others ship inactive in
# default Odoo and we don't want to depend on a particular one being
# enabled in any given DB).
unsupported = env["res.currency"].with_context(active_test=False).search(
    [("name", "not in", ("USD", "ZWG"))], limit=1)
err, _ = _try(lambda: Quote.create({
    "event_job_id": event_job.id,
    "currency_id": unsupported.id,
    "salesperson_id": sales_user.id,
}))
ok = isinstance(err, ValidationError)
print("  unsupported currency tested:", unsupported.name,
      " err:", type(err).__name__ if err else None)
print("T606:", "PASS" if ok else "FAIL")
results["T606"] = ok


# ============================================================
print()
print("=" * 72)
print("T607 - quote.partner_id related from event_job chain")
print("=" * 72)
# event_job.partner_id is itself related through commercial_job_id.
# This verifies the chained-related works end to end.
ok = q_t602.partner_id == partner
print("  quote.partner_id:", q_t602.partner_id.name,
      "expected:", partner.name)
print("T607:", "PASS" if ok else "FAIL")
results["T607"] = ok


# ============================================================
print()
print("=" * 72)
print("T608 - quote.line create success")
print("=" * 72)
err, line_t608 = _try(lambda: QuoteLine.create({
    "quote_id": q_t602.id,
    "line_type": "equipment",
    "name": "Sound rig",
    "quantity": 2.0,
    "unit_rate": 50.0,
    "duration_days": 3,
}))
ok = err is None and bool(line_t608)
print("  line_id:", line_t608.id if line_t608 else None)
print("T608:", "PASS" if ok else "FAIL")
results["T608"] = ok


# ============================================================
print()
print("=" * 72)
print("T609 - quote.line quantity > 0 sql constraint")
print("=" * 72)
err, _ = _try(lambda: QuoteLine.create({
    "quote_id": q_t602.id, "line_type": "other",
    "name": "bad qty", "quantity": 0.0,
    "unit_rate": 10.0, "duration_days": 1,
}))
ok = isinstance(err, IntegrityError)
print("  err:", type(err).__name__ if err else None)
print("T609:", "PASS" if ok else "FAIL")
results["T609"] = ok


# ============================================================
print()
print("=" * 72)
print("T610 - quote.line duration_days >= 1 sql constraint")
print("=" * 72)
err, _ = _try(lambda: QuoteLine.create({
    "quote_id": q_t602.id, "line_type": "other",
    "name": "bad days", "quantity": 1.0,
    "unit_rate": 10.0, "duration_days": 0,
}))
ok = isinstance(err, IntegrityError)
print("  err:", type(err).__name__ if err else None)
print("T610:", "PASS" if ok else "FAIL")
results["T610"] = ok


# ============================================================
print()
print("=" * 72)
print("T611 - quote.line unit_rate >= 0 sql constraint")
print("=" * 72)
err, _ = _try(lambda: QuoteLine.create({
    "quote_id": q_t602.id, "line_type": "other",
    "name": "bad rate", "quantity": 1.0,
    "unit_rate": -1.0, "duration_days": 1,
}))
ok = isinstance(err, IntegrityError)
print("  err:", type(err).__name__ if err else None)
print("T611:", "PASS" if ok else "FAIL")
results["T611"] = ok


# ============================================================
print()
print("=" * 72)
print("T612 - quote.line line_subtotal = qty * rate * days")
print("=" * 72)
# line_t608: qty=2, rate=50, days=3 -> 300
ok = line_t608.line_subtotal == 300.0
print("  subtotal:", line_t608.line_subtotal, "expected: 300.0")
print("T612:", "PASS" if ok else "FAIL")
results["T612"] = ok


# ============================================================
print()
print("=" * 72)
print("T613 - quote.line line_total_taxed applies tax")
print("=" * 72)
# Default tax is tax_vat_15_5_sale (15.5%). 300 * 1.155 = 346.5
ok = abs(line_t608.line_total_taxed - 346.5) < 0.01
print("  taxed:", line_t608.line_total_taxed, "expected ~346.5")
print("T613:", "PASS" if ok else "FAIL")
results["T613"] = ok


# ============================================================
print()
print("=" * 72)
print("T614 - quote.line line_margin = subtotal - cost (cost=0 -> margin=subtotal)")
print("=" * 72)
ok = line_t608.line_margin == 300.0
print("  margin:", line_t608.line_margin, "expected: 300.0")
print("T614:", "PASS" if ok else "FAIL")
results["T614"] = ok


# ============================================================
print()
print("=" * 72)
print("T615 - equipment_line_id on non-equipment line_type -> ValidationError")
print("=" * 72)
# Reuse a stub equipment line. Find an existing one or create one on
# the fixture event_job. Either path gives us a valid ID to attach.
ej_line = env["commercial.event.job.equipment.line"].search([], limit=1)
if not ej_line:
    # Build a minimal product + line so the constraint test always
    # has something to point at. Workshop_item flag is required by
    # the line model's product domain.
    product = env["product.template"].search(
        [("is_workshop_item", "=", True)], limit=1)
    if not product:
        product = env["product.template"].create({
            "name": "P6M2 Smoke Product",
            "is_workshop_item": True,
        })
    ej_line = env["commercial.event.job.equipment.line"].create({
        "event_job_id": event_job.id,
        "product_template_id": product.id,
        "quantity_planned": 1,
    })
err, _ = _try(lambda: QuoteLine.create({
    "quote_id": q_t602.id, "line_type": "consumable",
    "name": "mismatched", "quantity": 1.0,
    "unit_rate": 1.0, "duration_days": 1,
    "equipment_line_id": ej_line.id,
}))
ok = isinstance(err, ValidationError)
print("  err:", type(err).__name__ if err else None)
print("T615:", "PASS" if ok else "FAIL")
results["T615"] = ok


# ============================================================
print()
print("=" * 72)
print("T616 - quote amount_untaxed = sum of line subtotals")
print("=" * 72)
# Add a second line so the sum is non-trivial.
line_b = QuoteLine.create({
    "quote_id": q_t602.id, "line_type": "crew",
    "name": "Lighting tech", "quantity": 1.0,
    "unit_rate": 80.0, "duration_days": 2,
    "tax_id": False,  # explicit no tax for cleaner arithmetic on T617
})
q_t602.invalidate_recordset()
ok = q_t602.amount_untaxed == 300.0 + 160.0  # 460
print("  amount_untaxed:", q_t602.amount_untaxed, "expected: 460.0")
print("T616:", "PASS" if ok else "FAIL")
results["T616"] = ok


# ============================================================
print()
print("=" * 72)
print("T617 - quote amount_total includes tax")
print("=" * 72)
# line_t608 taxed = 346.5, line_b taxed = 160.0 (no tax) -> 506.5
expected_total = 346.5 + 160.0
ok = abs(q_t602.amount_total - expected_total) < 0.01
print("  amount_total:", q_t602.amount_total,
      "expected ~", expected_total)
print("T617:", "PASS" if ok else "FAIL")
results["T617"] = ok


# ============================================================
print()
print("=" * 72)
print("T618 - quote margin_pct = margin_total / amount_untaxed * 100")
print("=" * 72)
# cost=0 -> margin=untaxed -> margin_pct=100.0
ok = abs(q_t602.margin_pct - 100.0) < 0.01
print("  margin_pct:", q_t602.margin_pct, "expected: 100.0")
print("T618:", "PASS" if ok else "FAIL")
results["T618"] = ok


# ============================================================
print()
print("=" * 72)
print("T619 - action_submit_for_approval from draft + lines + term -> auto-approved")
print("=" * 72)
q_t619 = Quote.create({
    "event_job_id": event_job.id,
    "currency_id": usd.id,
    "salesperson_id": sales_user.id,
    "payment_term_id": term.id,
})
QuoteLine.create({
    "quote_id": q_t619.id, "line_type": "other",
    "name": "test line", "quantity": 1.0,
    "unit_rate": 100.0, "duration_days": 1,
})
err, _ = _try(lambda: q_t619.with_user(sales_user).action_submit_for_approval())
# M2 placeholder: auto-approve runs inline. End state should be 'approved'.
ok = err is None and q_t619.state == "approved" and q_t619.approved_by_id == sales_user
print("  state:", q_t619.state, "approved_by:", q_t619.approved_by_id.login)
print("T619:", "PASS" if ok else "FAIL")
results["T619"] = ok


# ============================================================
print()
print("=" * 72)
print("T620 - action_submit_for_approval without lines -> UserError")
print("=" * 72)
q_t620 = Quote.create({
    "event_job_id": event_job.id,
    "currency_id": usd.id,
    "salesperson_id": sales_user.id,
    "payment_term_id": term.id,
})
err, _ = _try(lambda: q_t620.with_user(sales_user).action_submit_for_approval())
ok = isinstance(err, UserError)
print("  err:", type(err).__name__ if err else None)
print("T620:", "PASS" if ok else "FAIL")
results["T620"] = ok


# ============================================================
print()
print("=" * 72)
print("T621 - action_submit_for_approval without payment_term -> UserError")
print("=" * 72)
q_t621 = Quote.create({
    "event_job_id": event_job.id,
    "currency_id": usd.id,
    "salesperson_id": sales_user.id,
})
QuoteLine.create({
    "quote_id": q_t621.id, "line_type": "other",
    "name": "x", "quantity": 1.0,
    "unit_rate": 1.0, "duration_days": 1,
})
err, _ = _try(lambda: q_t621.with_user(sales_user).action_submit_for_approval())
ok = isinstance(err, UserError)
print("  err:", type(err).__name__ if err else None)
print("T621:", "PASS" if ok else "FAIL")
results["T621"] = ok


# ============================================================
print()
print("=" * 72)
print("T622 - action_submit_for_approval from non-draft state -> UserError")
print("=" * 72)
# q_t619 is now 'approved' (post T619 auto-approval).
err, _ = _try(lambda: q_t619.action_submit_for_approval())
ok = isinstance(err, UserError)
print("  err:", type(err).__name__ if err else None, " state:", q_t619.state)
print("T622:", "PASS" if ok else "FAIL")
results["T622"] = ok


# ============================================================
print()
print("=" * 72)
print("T623 - action_approve from pending_approval with approver -> success")
print("=" * 72)
# Set up a quote in pending_approval state without triggering auto-
# approve. Bypass the action by writing state directly.
q_t623 = Quote.create({
    "event_job_id": event_job.id,
    "currency_id": usd.id,
    "salesperson_id": sales_user.id,
    "payment_term_id": term.id,
})
QuoteLine.create({
    "quote_id": q_t623.id, "line_type": "other",
    "name": "x", "quantity": 1.0,
    "unit_rate": 1.0, "duration_days": 1,
})
q_t623.state = "pending_approval"
err, _ = _try(lambda: q_t623.with_user(approver_user).action_approve())
ok = err is None and q_t623.state == "approved"
print("  state:", q_t623.state, "approved_by:", q_t623.approved_by_id.login)
print("T623:", "PASS" if ok else "FAIL")
results["T623"] = ok


# ============================================================
print()
print("=" * 72)
print("T624 - action_approve from non-pending state -> UserError")
print("=" * 72)
err, _ = _try(lambda: q_t623.with_user(approver_user).action_approve())
ok = isinstance(err, UserError)
print("  err:", type(err).__name__ if err else None)
print("T624:", "PASS" if ok else "FAIL")
results["T624"] = ok


# ============================================================
print()
print("=" * 72)
print("T625 - action_approve without approver group -> AccessError")
print("=" * 72)
q_t625 = Quote.create({
    "event_job_id": event_job.id,
    "currency_id": usd.id,
    "salesperson_id": sales_user.id,
    "payment_term_id": term.id,
})
q_t625.state = "pending_approval"
err, _ = _try(lambda: q_t625.with_user(book_user).action_approve())
ok = isinstance(err, AccessError)
print("  err:", type(err).__name__ if err else None)
print("T625:", "PASS" if ok else "FAIL")
results["T625"] = ok


# ============================================================
print()
print("=" * 72)
print("T626 - action_reject with reason + approver group -> success")
print("=" * 72)
err, _ = _try(lambda: q_t625.with_user(approver_user).with_context(
    rejection_reason="Out of budget").action_reject())
ok = (err is None and q_t625.state == "rejected"
      and q_t625.rejection_reason == "Out of budget")
print("  state:", q_t625.state, "reason:", q_t625.rejection_reason)
print("T626:", "PASS" if ok else "FAIL")
results["T626"] = ok


# ============================================================
print()
print("=" * 72)
print("T627 - action_reject without reason in context -> UserError")
print("=" * 72)
q_t627 = Quote.create({
    "event_job_id": event_job.id,
    "currency_id": usd.id,
    "salesperson_id": sales_user.id,
    "payment_term_id": term.id,
})
q_t627.state = "pending_approval"
err, _ = _try(lambda: q_t627.with_user(approver_user).action_reject())
ok = isinstance(err, UserError)
print("  err:", type(err).__name__ if err else None)
print("T627:", "PASS" if ok else "FAIL")
results["T627"] = ok


# ============================================================
print()
print("=" * 72)
print("T628 - action_reject without approver group -> AccessError")
print("=" * 72)
err, _ = _try(lambda: q_t627.with_user(book_user).with_context(
    rejection_reason="x").action_reject())
ok = isinstance(err, AccessError)
print("  err:", type(err).__name__ if err else None)
print("T628:", "PASS" if ok else "FAIL")
results["T628"] = ok


# ============================================================
print()
print("=" * 72)
print("T629 - action_send from approved by salesperson -> success")
print("=" * 72)
# q_t623 is 'approved' from T623.
err, _ = _try(lambda: q_t623.with_user(sales_user).action_send())
ok = err is None and q_t623.state == "sent" and bool(q_t623.sent_at)
print("  state:", q_t623.state, "sent_at:", q_t623.sent_at)
print("T629:", "PASS" if ok else "FAIL")
results["T629"] = ok


# ============================================================
print()
print("=" * 72)
print("T630 - action_accept from sent -> success")
print("=" * 72)
err, _ = _try(lambda: q_t623.with_user(sales_user).action_accept())
ok = err is None and q_t623.state == "accepted" and bool(q_t623.accepted_at)
print("  state:", q_t623.state, "accepted_at:", q_t623.accepted_at)
print("T630:", "PASS" if ok else "FAIL")
results["T630"] = ok


# ============================================================
print()
print("=" * 72)
print("T631 - action_cancel from any non-terminal with reason -> success")
print("=" * 72)
q_t631 = Quote.create({
    "event_job_id": event_job.id,
    "currency_id": usd.id,
    "salesperson_id": sales_user.id,
    "payment_term_id": term.id,
})
err, _ = _try(lambda: q_t631.with_user(sales_user).with_context(
    cancelled_reason="Client withdrew").action_cancel())
ok = (err is None and q_t631.state == "cancelled"
      and q_t631.cancelled_reason == "Client withdrew")
print("  state:", q_t631.state, "reason:", q_t631.cancelled_reason)
print("T631:", "PASS" if ok else "FAIL")
results["T631"] = ok


# ============================================================
print()
print("=" * 72)
print("T632 - action_cancel from terminal -> UserError")
print("=" * 72)
err, _ = _try(lambda: q_t631.with_user(sales_user).with_context(
    cancelled_reason="again").action_cancel())
ok = isinstance(err, UserError)
print("  err:", type(err).__name__ if err else None)
print("T632:", "PASS" if ok else "FAIL")
results["T632"] = ok


# ============================================================
print()
print("=" * 72)
print("T633 - action_cancel without reason -> UserError")
print("=" * 72)
q_t633 = Quote.create({
    "event_job_id": event_job.id,
    "currency_id": usd.id,
    "salesperson_id": sales_user.id,
    "payment_term_id": term.id,
})
err, _ = _try(lambda: q_t633.with_user(sales_user).action_cancel())
ok = isinstance(err, UserError)
print("  err:", type(err).__name__ if err else None)
print("T633:", "PASS" if ok else "FAIL")
results["T633"] = ok


# ============================================================
print()
print("=" * 72)
print("T634 - _cron_expire_quotes transitions sent + expired_at < today")
print("=" * 72)
q_t634 = Quote.create({
    "event_job_id": event_job.id,
    "currency_id": usd.id,
    "salesperson_id": sales_user.id,
    "payment_term_id": term.id,
    "expires_at": date.today() - timedelta(days=1),
})
q_t634.state = "sent"  # bypass the workflow for the cron test
fresh_q = Quote.create({
    "event_job_id": event_job.id,
    "currency_id": usd.id,
    "salesperson_id": sales_user.id,
    "expires_at": date.today() + timedelta(days=5),
})
fresh_q.state = "sent"  # also sent, but not expired -- should remain
expired_count = Quote._cron_expire_quotes()
ok = (q_t634.state == "expired"
      and fresh_q.state == "sent"
      and expired_count >= 1)
print("  expired q state:", q_t634.state,
      " fresh q state:", fresh_q.state,
      " cron return:", expired_count)
print("T634:", "PASS" if ok else "FAIL")
results["T634"] = ok


# ============================================================
print()
print("=" * 72)
print("T635 - payment_term name auto-compute")
print("=" * 72)
t_t635 = Term.create({
    "deposit_pct": 30.0,
    "deposit_due_days": 7,
    "final_due_days": 14,
    "late_policy": "account_hold",
})
ok = ("30%" in t_t635.name and "14d" in t_t635.name
      and "account_hold" in t_t635.name)
print("  name:", t_t635.name)
print("T635:", "PASS" if ok else "FAIL")
results["T635"] = ok


# ============================================================
print()
print("=" * 72)
print("T636 - ir.rule: sales sees own quotes only")
print("=" * 72)
# Create one quote owned by sales_user and one owned by other_sales.
# Quoting as sales_user should yield only the first.
q_self = Quote.create({
    "event_job_id": event_job.id,
    "currency_id": usd.id,
    "salesperson_id": sales_user.id,
})
q_others = Quote.create({
    "event_job_id": event_job.id,
    "currency_id": usd.id,
    "salesperson_id": other_sales.id,
})
visible = Quote.with_user(sales_user).search([
    ("id", "in", [q_self.id, q_others.id])])
ok = q_self in visible and q_others not in visible
print("  visible ids:", visible.ids,
      " q_self:", q_self.id, " q_others:", q_others.id)
print("T636:", "PASS" if ok else "FAIL")
results["T636"] = ok


# ============================================================
print()
print("=" * 72)
print("T637 - ir.rule: bookkeeper sees all quotes")
print("=" * 72)
visible_book = Quote.with_user(book_user).search([
    ("id", "in", [q_self.id, q_others.id])])
ok = q_self in visible_book and q_others in visible_book
print("  visible ids:", visible_book.ids)
print("T637:", "PASS" if ok else "FAIL")
results["T637"] = ok


# ============================================================
print()
print("=" * 72)
print("T638 - CSV: no perm_unlink on quote for any of the three roles")
print("=" * 72)
access = env["ir.model.access"].search([
    ("model_id.model", "=", "neon.finance.quote"),
])
groups_no_unlink = {a.group_id.name: not a.perm_unlink for a in access}
ok = (len(access) >= 3
      and all(groups_no_unlink.values()))
print("  groups perm_unlink=False:", groups_no_unlink)
print("T638:", "PASS" if ok else "FAIL")
results["T638"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in range(600, 639)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
