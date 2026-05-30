from datetime import date, timedelta

usd = env.ref("base.USD")
sales_user = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
book_user = env["res.users"].search([("login", "=", "p2m75_book")], limit=1)

partner = env["res.partner"].create({"name": "diag", "is_company": True})
venue = env["res.partner"].create({"name": "diagv", "is_company": True})
term = env["neon.finance.payment.term"].create({
    "partner_id": partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
j = env["commercial.job"].create({
    "partner_id": partner.id, "venue_id": venue.id,
    "event_date": date.today() + timedelta(days=30),
    "currency_id": usd.id,
})
ej = env["commercial.event.job"].create({"commercial_job_id": j.id})
q = env["neon.finance.quote"].create({
    "event_job_id": ej.id, "salesperson_id": sales_user.id,
    "currency_id": usd.id, "payment_term_id": term.id,
})
env["neon.finance.quote.line"].create({
    "quote_id": q.id, "line_type": "other", "name": "x",
    "quantity": 1, "duration_days": 1,
    "unit_rate": 1000.0, "pricing_status": "manual",
})
env["neon.finance.invoice.schedule"].create({
    "quote_id": q.id, "sequence": 1, "stage": "deposit",
    "trigger": "on_acceptance", "percentage": 100.0,
    "currency_id": usd.id,
})
q.sudo().write({"state": "sent"})
q.sudo().with_user(sales_user).action_accept()
q.invalidate_recordset()
inv = q.invoice_schedule_ids[0].invoice_id
inv.sudo().write({
    "invoice_date": date.today(),
    "invoice_date_due": date.today() + timedelta(days=30),
})
inv.sudo().action_post()
print("invoice posted:", inv.name, "state:", inv.state,
      "residual:", inv.amount_residual)

# First partial 400
w1 = env["account.payment.register"].with_user(book_user).with_context(
    active_model="account.move", active_ids=inv.ids, active_id=inv.id,
).create({"amount": 400.0})
w1._create_payments()
inv.invalidate_recordset()
print("after partial: residual:", inv.amount_residual,
      "payment_state:", inv.payment_state)

# Inspect what the wizard sees on the second call
inv.invalidate_recordset()
rec_lines = inv.line_ids.filtered(
    lambda l: l.account_id.account_type == "asset_receivable")
print("receivable lines:", rec_lines.ids, "residuals:",
      rec_lines.mapped("amount_residual"),
      "reconciled?:", rec_lines.mapped("reconciled"))

# Now try second 600
try:
    w2 = env["account.payment.register"].with_user(book_user).with_context(
        active_model="account.move", active_ids=inv.ids, active_id=inv.id,
    ).create({"amount": 600.0})
    print("wizard2 line_ids:", w2.line_ids.ids,
          "amount:", w2.amount, "currency:", w2.currency_id.name)
    w2._create_payments()
    inv.invalidate_recordset()
    print("after full pay: residual:", inv.amount_residual,
          "payment_state:", inv.payment_state)
except Exception as e:
    print("2nd-pay error:", type(e).__name__, str(e)[:150])

env.cr.rollback()
