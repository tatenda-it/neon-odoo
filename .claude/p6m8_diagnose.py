from datetime import date, timedelta

usd = env.ref("base.USD")
sales_user = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
partner = env["res.partner"].create({
    "name": "diag client", "is_company": True,
})
venue = env["res.partner"].create({
    "name": "diag venue", "is_company": True,
})
Term = env["neon.finance.payment.term"]
term = Term.create({
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
    "quote_id": q.id, "line_type": "other",
    "name": "diag", "quantity": 1, "duration_days": 1,
    "unit_rate": 1000.0, "pricing_status": "manual",
})
env["neon.finance.invoice.schedule"].create({
    "quote_id": q.id, "sequence": 1, "stage": "deposit",
    "trigger": "on_acceptance", "percentage": 50.0,
    "currency_id": usd.id,
})
env["neon.finance.invoice.schedule"].create({
    "quote_id": q.id, "sequence": 2, "stage": "final",
    "trigger": "on_acceptance", "percentage": 50.0,
    "currency_id": usd.id,
})
q.sudo().write({"state": "sent"})
q.sudo().with_user(sales_user).action_accept()
q.invalidate_recordset()
inv = q.invoice_schedule_ids.mapped("invoice_id")[0]
sched = q.invoice_schedule_ids[0]
print("inv id:", inv.id, "ref:", inv.ref, "origin:", inv.invoice_origin)
print("sched name:", sched.name, "state:", sched.state)
print("siblings:", q.invoice_schedule_ids.mapped(lambda s: (s.sequence, s.stage, s.percentage)))
rendered, _ = env["ir.actions.report"]._render_qweb_html(
    "account.report_invoice", inv.ids)
html = rendered.decode("utf-8") if isinstance(rendered, bytes) else rendered
# Look for stage text
import re
m = re.search(r"Stage", html)
if m:
    snippet = html[max(0, m.start()-30):m.end()+300]
    print("Stage context:")
    print(snippet)
else:
    print("(no 'Stage' anywhere in html)")
# Check if the sched search would find it
found = env['neon.finance.invoice.schedule'].sudo().search(
    [('name', '=', inv.ref)], limit=1)
print("sched lookup via inv.ref:", found.id if found else "(not found)")
env.cr.rollback()
