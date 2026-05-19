"""P6.M7 smoke -- multi-stage invoicing schedule.

Template + line model:
T1100  template create works
T1101  percentage sum constraint (lines must sum to 100)
T1102  inactive template ignored at materialisation
T1103  most-recent active template chosen when multiple exist

Quote.invoice_schedule_pct_total compute:
T1104  pct_total = 0 when empty
T1105  pct_total reflects partial schedule
T1106  pct_total = 100 when balanced

Schedule materialisation on action_accept:
T1110  accept with NO o2m + NO template -> single 100% on_acceptance row
T1111  accept with NO o2m + active template -> mirrors template
T1112  accept with pre-designed o2m -> preserved (no overwrite)
T1113  accept with NO o2m + inactive template -> falls back to default
T1114  accept materialises with currency inherited from quote

Accept-time pct validation:
T1118  accept with o2m summing to 90 raises UserError
T1119  accept with empty o2m succeeds (fallback path)
T1120  accept with o2m summing to 100 succeeds

Trigger on_acceptance:
T1130  on_acceptance schedule fires invoice immediately on accept
T1131  invoice line stage-charge: price_unit = subtotal*pct/100, qty=1
T1132  multiple on_acceptance schedules all fire on accept

Trigger on_date via cron:
T1140  cron picks up on_date with trigger_date <= today
T1141  cron skips on_date with future trigger_date
T1142  cron skips schedules already in invoiced/paid state
T1143  cron skips trigger='on_acceptance' (out of scope)

Trigger on_event_state via event_job write override:
T1150  event_job.state -> 'ready_for_dispatch' fires matching schedule
T1151  event_job.state -> 'in_progress' fires matching schedule
T1152  event_job.state -> 'completed' fires matching schedule
T1153  unrelated event_job field write does NOT fire
T1154  pre-check optimization: no schedules -> no snapshot taken

Manual trigger:
T1160  action_trigger_now by approver succeeds
T1162  action_trigger_now on already-invoiced raises UserError

Audit-trail (perm_unlink=0 invariant):
T1170  invoice_schedule perm_unlink=0 for all three roles
T1171  template perm_unlink=0 for all three roles
T1172  template_line perm_unlink=0 for all three roles

ACL + ir.rule scoping:
T1180  sales sees only own quote's schedules
T1182  bookkeeper sees all schedules
T1183  approver sees all schedules

Sequence + invoice link:
T1190  schedule.name pattern = SCH-NNNNNN
T1191  invoice created has ref capturing schedule.name
T1192  invoice currency matches quote currency
T1194  schedule.state flips to 'invoiced' post action_create_invoice
T1195  state guard: action_create_invoice on triggered/invoiced is a no-op
"""
import re
from datetime import date, timedelta

from odoo.exceptions import AccessError, UserError, ValidationError


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
Sched = env["neon.finance.invoice.schedule"]
Tpl = env["neon.finance.invoice.schedule.template"]
TplLine = env["neon.finance.invoice.schedule.template.line"]
EventJob = env["commercial.event.job"]
Move = env["account.move"]
Term = env["neon.finance.payment.term"]

usd = env.ref("base.USD")
sales_user = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
book_user = env["res.users"].search([("login", "=", "p2m75_book")], limit=1)
approver_user = env["res.users"].search(
    [("login", "=", "p2m75_approver")], limit=1)
other_user = env["res.users"].search([("login", "=", "p2m75_other")], limit=1)
assert all([sales_user, book_user, approver_user, other_user])

approver_group = env.ref("neon_finance.group_neon_finance_approver")
book_group = env.ref("neon_finance.group_neon_finance_bookkeeper")
sales_group = env.ref("neon_finance.group_neon_finance_sales")

partner = env["res.partner"].create({
    "name": "P6M7 Client", "is_company": True,
})
other_partner = env["res.partner"].create({
    "name": "P6M7 Other Client", "is_company": True,
})
venue = env["res.partner"].create({
    "name": "P6M7 Venue", "is_company": True,
})
term = Term.create({
    "partner_id": partner.id,
    "deposit_pct": 50.0, "deposit_due_days": 0,
    "final_due_days": 30, "late_policy": "reminder",
})


def _new_quote(p=partner, sp=sales_user, accept_ready=True, amount=1000.0,
               sched_lines=None):
    """Build a quote in 'sent' state with one line of `amount`,
    optionally pre-populated with schedule rows. Use accept_ready=False
    to keep it in draft."""
    j = env["commercial.job"].create({
        "partner_id": p.id, "venue_id": venue.id,
        "event_date": date.today() + timedelta(days=30),
        "currency_id": usd.id,
    })
    ej = EventJob.create({"commercial_job_id": j.id})
    q = Quote.create({
        "event_job_id": ej.id,
        "salesperson_id": sp.id,
        "currency_id": usd.id,
        "payment_term_id": term.id,
    })
    QuoteLine.create({
        "quote_id": q.id, "line_type": "other",
        "name": "P6M7 line", "quantity": 1, "duration_days": 1,
        "unit_rate": amount, "pricing_status": "manual",
    })
    if sched_lines:
        for sl in sched_lines:
            Sched.create(dict(sl, quote_id=q.id, currency_id=usd.id))
    if accept_ready:
        # Drive through state machine to 'sent'
        q.sudo().write({"state": "sent"})
    return q, ej


# ============================================================
print()
print("=" * 72)
print("T1100 - template create works")
print("=" * 72)
tpl_t1100 = Tpl.create({
    "name": "T1100 cadence", "partner_id": partner.id,
    "line_ids": [
        (0, 0, {"sequence": 1, "stage": "deposit",
                "trigger": "on_acceptance", "percentage": 50.0}),
        (0, 0, {"sequence": 2, "stage": "final",
                "trigger": "on_date", "trigger_offset_days": 30,
                "percentage": 50.0}),
    ],
})
ok = bool(tpl_t1100 and len(tpl_t1100.line_ids) == 2)
print("  template id:", tpl_t1100.id, "lines:", len(tpl_t1100.line_ids))
print("T1100:", "PASS" if ok else "FAIL")
results["T1100"] = ok


# ============================================================
print()
print("=" * 72)
print("T1101 - percentage sum constraint (90% must raise)")
print("=" * 72)
err, _ = _try(lambda: Tpl.create({
    "name": "T1101 bad", "partner_id": partner.id,
    "line_ids": [
        (0, 0, {"sequence": 1, "stage": "deposit",
                "trigger": "on_acceptance", "percentage": 40.0}),
        (0, 0, {"sequence": 2, "stage": "final",
                "trigger": "on_date", "trigger_offset_days": 30,
                "percentage": 50.0}),
    ],
}))
ok = isinstance(err, (ValidationError, UserError))
print("  err:", type(err).__name__ if err else "None")
print("T1101:", "PASS" if ok else "FAIL")
results["T1101"] = ok


# ============================================================
print()
print("=" * 72)
print("T1102 - inactive template ignored")
print("=" * 72)
tpl_t1102 = Tpl.create({
    "name": "T1102 inactive", "partner_id": other_partner.id, "active": False,
    "line_ids": [
        (0, 0, {"sequence": 1, "stage": "deposit",
                "trigger": "on_acceptance", "percentage": 30.0}),
        (0, 0, {"sequence": 2, "stage": "final",
                "trigger": "on_acceptance", "percentage": 70.0}),
    ],
})
q_t1102, _ = _new_quote(p=other_partner)
q_t1102.sudo().with_user(sales_user).action_accept()
q_t1102.invalidate_recordset()
ok = (len(q_t1102.invoice_schedule_ids) == 1 and
      q_t1102.invoice_schedule_ids.trigger == "on_acceptance" and
      q_t1102.invoice_schedule_ids.percentage == 100.0)
print("  schedules:", len(q_t1102.invoice_schedule_ids),
      "pct:", q_t1102.invoice_schedule_ids.mapped("percentage"))
print("T1102:", "PASS" if ok else "FAIL")
results["T1102"] = ok


# ============================================================
print()
print("=" * 72)
print("T1103 - most-recent active template chosen")
print("=" * 72)
older = Tpl.create({
    "name": "T1103 older", "partner_id": partner.id,
    "line_ids": [
        (0, 0, {"sequence": 1, "stage": "deposit",
                "trigger": "on_acceptance", "percentage": 25.0}),
        (0, 0, {"sequence": 2, "stage": "final",
                "trigger": "on_acceptance", "percentage": 75.0}),
    ],
})
newer = Tpl.create({
    "name": "T1103 newer", "partner_id": partner.id,
    "line_ids": [
        (0, 0, {"sequence": 1, "stage": "deposit",
                "trigger": "on_acceptance", "percentage": 60.0}),
        (0, 0, {"sequence": 2, "stage": "final",
                "trigger": "on_acceptance", "percentage": 40.0}),
    ],
})
q_t1103, _ = _new_quote()
q_t1103.sudo().with_user(sales_user).action_accept()
q_t1103.invalidate_recordset()
deposit = q_t1103.invoice_schedule_ids.filtered(
    lambda s: s.stage == "deposit")
ok = bool(deposit and deposit.percentage == 60.0)
print("  deposit pct:", deposit.percentage if deposit else None)
print("T1103:", "PASS" if ok else "FAIL")
results["T1103"] = ok


# ============================================================
print()
print("=" * 72)
print("T1104 - invoice_schedule_pct_total = 0 when empty")
print("=" * 72)
q_t1104, _ = _new_quote(accept_ready=False)
ok = q_t1104.invoice_schedule_pct_total == 0.0
print("  total:", q_t1104.invoice_schedule_pct_total)
print("T1104:", "PASS" if ok else "FAIL")
results["T1104"] = ok


# ============================================================
print()
print("=" * 72)
print("T1105 - invoice_schedule_pct_total reflects partial")
print("=" * 72)
q_t1105, _ = _new_quote(accept_ready=False, sched_lines=[
    {"sequence": 1, "stage": "deposit",
     "trigger": "on_acceptance", "percentage": 40.0},
])
q_t1105.invalidate_recordset()
ok = q_t1105.invoice_schedule_pct_total == 40.0
print("  total:", q_t1105.invoice_schedule_pct_total)
print("T1105:", "PASS" if ok else "FAIL")
results["T1105"] = ok


# ============================================================
print()
print("=" * 72)
print("T1106 - invoice_schedule_pct_total = 100 when balanced")
print("=" * 72)
q_t1106, _ = _new_quote(accept_ready=False, sched_lines=[
    {"sequence": 1, "stage": "deposit",
     "trigger": "on_acceptance", "percentage": 50.0},
    {"sequence": 2, "stage": "final",
     "trigger": "on_acceptance", "percentage": 50.0},
])
q_t1106.invalidate_recordset()
ok = q_t1106.invoice_schedule_pct_total == 100.0
print("  total:", q_t1106.invoice_schedule_pct_total)
print("T1106:", "PASS" if ok else "FAIL")
results["T1106"] = ok


# ============================================================
print()
print("=" * 72)
print("T1110 - accept no-o2m no-template -> default 100% on_acceptance")
print("=" * 72)
fresh_partner = env["res.partner"].create({
    "name": "T1110 fresh", "is_company": True,
})
fresh_term = Term.create({
    "partner_id": fresh_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
j = env["commercial.job"].create({
    "partner_id": fresh_partner.id, "venue_id": venue.id,
    "event_date": date.today() + timedelta(days=30),
    "currency_id": usd.id,
})
ej_t1110 = EventJob.create({"commercial_job_id": j.id})
q_t1110 = Quote.create({
    "event_job_id": ej_t1110.id, "salesperson_id": sales_user.id,
    "currency_id": usd.id, "payment_term_id": fresh_term.id,
})
QuoteLine.create({
    "quote_id": q_t1110.id, "line_type": "other",
    "name": "x", "quantity": 1, "duration_days": 1,
    "unit_rate": 500.0, "pricing_status": "manual",
})
q_t1110.sudo().write({"state": "sent"})
q_t1110.sudo().with_user(sales_user).action_accept()
q_t1110.invalidate_recordset()
sched = q_t1110.invoice_schedule_ids
ok = (len(sched) == 1 and sched.trigger == "on_acceptance"
      and sched.percentage == 100.0)
print("  count:", len(sched), "trigger:",
      sched.mapped("trigger"), "pct:", sched.mapped("percentage"))
print("T1110:", "PASS" if ok else "FAIL")
results["T1110"] = ok


# ============================================================
print()
print("=" * 72)
print("T1111 - accept w/ active template -> mirrors template")
print("=" * 72)
tpl_partner = env["res.partner"].create({
    "name": "T1111 partner", "is_company": True,
})
Term.create({
    "partner_id": tpl_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
tpl_t1111 = Tpl.create({
    "name": "T1111 tpl", "partner_id": tpl_partner.id,
    "line_ids": [
        (0, 0, {"sequence": 1, "stage": "deposit",
                "trigger": "on_acceptance", "percentage": 30.0}),
        (0, 0, {"sequence": 2, "stage": "progress",
                "trigger": "on_date", "trigger_offset_days": 14,
                "percentage": 40.0}),
        (0, 0, {"sequence": 3, "stage": "final",
                "trigger": "on_event_state",
                "trigger_event_state": "completed",
                "percentage": 30.0}),
    ],
})
q_t1111, _ = _new_quote(p=tpl_partner)
q_t1111.sudo().with_user(sales_user).action_accept()
q_t1111.invalidate_recordset()
ok = (len(q_t1111.invoice_schedule_ids) == 3 and
      sum(q_t1111.invoice_schedule_ids.mapped("percentage")) == 100.0)
print("  schedules:", len(q_t1111.invoice_schedule_ids),
      "sum:", sum(q_t1111.invoice_schedule_ids.mapped("percentage")))
print("T1111:", "PASS" if ok else "FAIL")
results["T1111"] = ok


# ============================================================
print()
print("=" * 72)
print("T1112 - accept w/ pre-designed o2m -> preserved")
print("=" * 72)
q_t1112, _ = _new_quote(p=partner, sched_lines=[
    {"sequence": 1, "stage": "deposit",
     "trigger": "on_acceptance", "percentage": 40.0},
    {"sequence": 2, "stage": "final",
     "trigger": "on_acceptance", "percentage": 60.0},
])
pre_ids = q_t1112.invoice_schedule_ids.ids
q_t1112.sudo().with_user(sales_user).action_accept()
q_t1112.invalidate_recordset()
post_ids = q_t1112.invoice_schedule_ids.ids
ok = set(pre_ids) == set(post_ids) and len(post_ids) == 2
print("  pre:", pre_ids, "post:", post_ids)
print("T1112:", "PASS" if ok else "FAIL")
results["T1112"] = ok


# ============================================================
print()
print("=" * 72)
print("T1113 - inactive template -> default fallback")
print("=" * 72)
inactive_partner = env["res.partner"].create({
    "name": "T1113 partner", "is_company": True,
})
Term.create({
    "partner_id": inactive_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
Tpl.create({
    "name": "T1113 inactive", "partner_id": inactive_partner.id,
    "active": False,
    "line_ids": [
        (0, 0, {"sequence": 1, "stage": "deposit",
                "trigger": "on_acceptance", "percentage": 30.0}),
        (0, 0, {"sequence": 2, "stage": "final",
                "trigger": "on_acceptance", "percentage": 70.0}),
    ],
})
q_t1113, _ = _new_quote(p=inactive_partner)
q_t1113.sudo().with_user(sales_user).action_accept()
q_t1113.invalidate_recordset()
ok = (len(q_t1113.invoice_schedule_ids) == 1 and
      q_t1113.invoice_schedule_ids.percentage == 100.0)
print("  count:", len(q_t1113.invoice_schedule_ids),
      "pct:", q_t1113.invoice_schedule_ids.mapped("percentage"))
print("T1113:", "PASS" if ok else "FAIL")
results["T1113"] = ok


# ============================================================
print()
print("=" * 72)
print("T1114 - schedule currency inherited from quote")
print("=" * 72)
sched_for_curr = q_t1110.invoice_schedule_ids[0]
ok = sched_for_curr.currency_id.id == usd.id
print("  currency:", sched_for_curr.currency_id.name)
print("T1114:", "PASS" if ok else "FAIL")
results["T1114"] = ok


# ============================================================
print()
print("=" * 72)
print("T1118 - accept w/ sum=90 raises UserError")
print("=" * 72)
q_t1118, _ = _new_quote(p=partner, sched_lines=[
    {"sequence": 1, "stage": "deposit",
     "trigger": "on_acceptance", "percentage": 40.0},
    {"sequence": 2, "stage": "final",
     "trigger": "on_acceptance", "percentage": 50.0},
])
err, _ = _try(lambda: q_t1118.sudo().with_user(sales_user).action_accept())
ok = isinstance(err, UserError)
print("  err:", type(err).__name__ if err else "None")
print("T1118:", "PASS" if ok else "FAIL")
results["T1118"] = ok


# ============================================================
print()
print("=" * 72)
print("T1119 - accept w/ empty o2m succeeds (fallback)")
print("=" * 72)
empty_partner = env["res.partner"].create({
    "name": "T1119 fresh", "is_company": True,
})
Term.create({
    "partner_id": empty_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
q_t1119, _ = _new_quote(p=empty_partner)
err, _ = _try(lambda: q_t1119.sudo().with_user(sales_user).action_accept())
ok = err is None and q_t1119.state == "accepted"
print("  state:", q_t1119.state, "err:", err)
print("T1119:", "PASS" if ok else "FAIL")
results["T1119"] = ok


# ============================================================
print()
print("=" * 72)
print("T1120 - accept w/ sum=100 succeeds")
print("=" * 72)
q_t1120, _ = _new_quote(p=partner, sched_lines=[
    {"sequence": 1, "stage": "deposit",
     "trigger": "on_acceptance", "percentage": 50.0},
    {"sequence": 2, "stage": "final",
     "trigger": "on_acceptance", "percentage": 50.0},
])
err, _ = _try(lambda: q_t1120.sudo().with_user(sales_user).action_accept())
q_t1120.invalidate_recordset()
ok = err is None and q_t1120.state == "accepted"
print("  state:", q_t1120.state, "err:", err)
print("T1120:", "PASS" if ok else "FAIL")
results["T1120"] = ok


# ============================================================
print()
print("=" * 72)
print("T1130 - on_acceptance schedule fires invoice on accept")
print("=" * 72)
q_t1130, _ = _new_quote(p=partner, sched_lines=[
    {"sequence": 1, "stage": "deposit",
     "trigger": "on_acceptance", "percentage": 100.0},
])
q_t1130.sudo().with_user(sales_user).action_accept()
q_t1130.invalidate_recordset()
sched_t1130 = q_t1130.invoice_schedule_ids
ok = bool(sched_t1130.invoice_id) and sched_t1130.state in ("invoiced", "paid")
print("  invoice_id:", sched_t1130.invoice_id.id if sched_t1130.invoice_id else None,
      "state:", sched_t1130.state)
print("T1130:", "PASS" if ok else "FAIL")
results["T1130"] = ok


# ============================================================
print()
print("=" * 72)
print("T1131 - invoice line stage-charge semantics")
print("=" * 72)
# T1130 invoice: 100% on quote subtotal of 1000 -> 1000.00 stage charge.
move = sched_t1130.invoice_id
invoice_lines = move.invoice_line_ids
total_price = sum(invoice_lines.mapped("price_unit"))
all_qty_one = all(l.quantity == 1 for l in invoice_lines)
ok = abs(total_price - 1000.0) < 0.01 and all_qty_one
print("  total price_unit:", total_price, "all qty=1:", all_qty_one)
print("T1131:", "PASS" if ok else "FAIL")
results["T1131"] = ok


# ============================================================
print()
print("=" * 72)
print("T1132 - multiple on_acceptance schedules all fire")
print("=" * 72)
multi_partner = env["res.partner"].create({
    "name": "T1132 partner", "is_company": True,
})
Term.create({
    "partner_id": multi_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
q_t1132, _ = _new_quote(p=multi_partner, sched_lines=[
    {"sequence": 1, "stage": "deposit",
     "trigger": "on_acceptance", "percentage": 60.0},
    {"sequence": 2, "stage": "final",
     "trigger": "on_acceptance", "percentage": 40.0},
])
q_t1132.sudo().with_user(sales_user).action_accept()
q_t1132.invalidate_recordset()
fired = q_t1132.invoice_schedule_ids.filtered(
    lambda s: s.state in ("invoiced", "paid"))
ok = len(fired) == 2
print("  fired:", len(fired), "/", len(q_t1132.invoice_schedule_ids))
print("T1132:", "PASS" if ok else "FAIL")
results["T1132"] = ok


# ============================================================
print()
print("=" * 72)
print("T1140 - cron picks up on_date schedules with date<=today")
print("=" * 72)
crondate_partner = env["res.partner"].create({
    "name": "T1140 partner", "is_company": True,
})
Term.create({
    "partner_id": crondate_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
q_t1140, _ = _new_quote(p=crondate_partner, sched_lines=[
    {"sequence": 1, "stage": "final",
     "trigger": "on_date", "trigger_date": date.today() - timedelta(days=1),
     "percentage": 100.0},
])
q_t1140.sudo().with_user(sales_user).action_accept()
q_t1140.invalidate_recordset()
# Before cron: scheduled (because on_date, not on_acceptance)
assert q_t1140.invoice_schedule_ids.state == "scheduled", \
    "expected scheduled, got %s" % q_t1140.invoice_schedule_ids.state
Sched._cron_check_invoice_schedules()
q_t1140.invalidate_recordset()
ok = q_t1140.invoice_schedule_ids.state in ("invoiced", "paid")
print("  state after cron:", q_t1140.invoice_schedule_ids.state)
print("T1140:", "PASS" if ok else "FAIL")
results["T1140"] = ok


# ============================================================
print()
print("=" * 72)
print("T1141 - cron skips future-dated on_date schedules")
print("=" * 72)
future_partner = env["res.partner"].create({
    "name": "T1141 partner", "is_company": True,
})
Term.create({
    "partner_id": future_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
q_t1141, _ = _new_quote(p=future_partner, sched_lines=[
    {"sequence": 1, "stage": "final",
     "trigger": "on_date", "trigger_date": date.today() + timedelta(days=14),
     "percentage": 100.0},
])
q_t1141.sudo().with_user(sales_user).action_accept()
Sched._cron_check_invoice_schedules()
q_t1141.invalidate_recordset()
ok = q_t1141.invoice_schedule_ids.state == "scheduled"
print("  state:", q_t1141.invoice_schedule_ids.state)
print("T1141:", "PASS" if ok else "FAIL")
results["T1141"] = ok


# ============================================================
print()
print("=" * 72)
print("T1142 - cron skips already-invoiced schedules (idempotent)")
print("=" * 72)
# Re-run cron on T1140: should NOT create a second invoice.
move_before = q_t1140.invoice_schedule_ids.invoice_id
Sched._cron_check_invoice_schedules()
q_t1140.invalidate_recordset()
move_after = q_t1140.invoice_schedule_ids.invoice_id
ok = move_before.id == move_after.id
print("  moves equal:", ok)
print("T1142:", "PASS" if ok else "FAIL")
results["T1142"] = ok


# ============================================================
print()
print("=" * 72)
print("T1143 - cron skips trigger=on_acceptance schedules")
print("=" * 72)
oa_partner = env["res.partner"].create({
    "name": "T1143 partner", "is_company": True,
})
Term.create({
    "partner_id": oa_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
q_t1143, _ = _new_quote(p=oa_partner, sched_lines=[
    {"sequence": 1, "stage": "deposit",
     "trigger": "on_acceptance", "percentage": 100.0},
])
# DON'T accept; keep scheduled state and verify cron doesn't fire it.
q_t1143.invoice_schedule_ids.write({"state": "scheduled"})  # safety
state_before = q_t1143.invoice_schedule_ids.state
Sched._cron_check_invoice_schedules()
q_t1143.invalidate_recordset()
ok = q_t1143.invoice_schedule_ids.state == state_before
print("  before:", state_before, "after:", q_t1143.invoice_schedule_ids.state)
print("T1143:", "PASS" if ok else "FAIL")
results["T1143"] = ok


# ============================================================
print()
print("=" * 72)
print("T1150 - event_job.state->ready_for_dispatch fires schedule")
print("=" * 72)
es_partner = env["res.partner"].create({
    "name": "T1150 partner", "is_company": True,
})
Term.create({
    "partner_id": es_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
q_t1150, ej_t1150 = _new_quote(p=es_partner, sched_lines=[
    {"sequence": 1, "stage": "deposit",
     "trigger": "on_event_state",
     "trigger_event_state": "ready_for_dispatch",
     "percentage": 100.0},
])
q_t1150.sudo().with_user(sales_user).action_accept()
# Schedule still scheduled until event_job hits ready_for_dispatch
q_t1150.invalidate_recordset()
assert q_t1150.invoice_schedule_ids.state == "scheduled"
ej_t1150.sudo().with_context(_allow_state_write=True).write(
    {"state": "ready_for_dispatch"})
q_t1150.invalidate_recordset()
ok = q_t1150.invoice_schedule_ids.state in ("invoiced", "paid")
print("  state:", q_t1150.invoice_schedule_ids.state)
print("T1150:", "PASS" if ok else "FAIL")
results["T1150"] = ok


# ============================================================
print()
print("=" * 72)
print("T1151 - event_job.state->in_progress fires schedule")
print("=" * 72)
ip_partner = env["res.partner"].create({
    "name": "T1151 partner", "is_company": True,
})
Term.create({
    "partner_id": ip_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
q_t1151, ej_t1151 = _new_quote(p=ip_partner, sched_lines=[
    {"sequence": 1, "stage": "progress",
     "trigger": "on_event_state",
     "trigger_event_state": "in_progress",
     "percentage": 100.0},
])
q_t1151.sudo().with_user(sales_user).action_accept()
ej_t1151.sudo().with_context(_allow_state_write=True).write(
    {"state": "in_progress"})
q_t1151.invalidate_recordset()
ok = q_t1151.invoice_schedule_ids.state in ("invoiced", "paid")
print("  state:", q_t1151.invoice_schedule_ids.state)
print("T1151:", "PASS" if ok else "FAIL")
results["T1151"] = ok


# ============================================================
print()
print("=" * 72)
print("T1152 - event_job.state->completed fires schedule")
print("=" * 72)
comp_partner = env["res.partner"].create({
    "name": "T1152 partner", "is_company": True,
})
Term.create({
    "partner_id": comp_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
q_t1152, ej_t1152 = _new_quote(p=comp_partner, sched_lines=[
    {"sequence": 1, "stage": "retention",
     "trigger": "on_event_state",
     "trigger_event_state": "completed",
     "percentage": 100.0},
])
q_t1152.sudo().with_user(sales_user).action_accept()
ej_t1152.sudo().with_context(_allow_state_write=True).write(
    {"state": "completed"})
q_t1152.invalidate_recordset()
ok = q_t1152.invoice_schedule_ids.state in ("invoiced", "paid")
print("  state:", q_t1152.invoice_schedule_ids.state)
print("T1152:", "PASS" if ok else "FAIL")
results["T1152"] = ok


# ============================================================
print()
print("=" * 72)
print("T1153 - unrelated event_job field write does NOT fire")
print("=" * 72)
ur_partner = env["res.partner"].create({
    "name": "T1153 partner", "is_company": True,
})
Term.create({
    "partner_id": ur_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
q_t1153, ej_t1153 = _new_quote(p=ur_partner, sched_lines=[
    {"sequence": 1, "stage": "deposit",
     "trigger": "on_event_state",
     "trigger_event_state": "ready_for_dispatch",
     "percentage": 100.0},
])
q_t1153.sudo().with_user(sales_user).action_accept()
ej_t1153.sudo().write({"sub_hire_required": True})
q_t1153.invalidate_recordset()
ok = q_t1153.invoice_schedule_ids.state == "scheduled"
print("  state (should still be scheduled):",
      q_t1153.invoice_schedule_ids.state)
print("T1153:", "PASS" if ok else "FAIL")
results["T1153"] = ok


# ============================================================
print()
print("=" * 72)
print("T1154 - pre-check: event_job state write with no schedules = no crash")
print("=" * 72)
no_sched_j = env["commercial.job"].create({
    "partner_id": partner.id, "venue_id": venue.id,
    "event_date": date.today() + timedelta(days=30),
    "currency_id": usd.id,
})
ej_t1154 = EventJob.create({"commercial_job_id": no_sched_j.id})
err, _ = _try(lambda: ej_t1154.sudo().with_context(
    _allow_state_write=True).write({"state": "ready_for_dispatch"}))
ok = err is None
print("  err:", err)
print("T1154:", "PASS" if ok else "FAIL")
results["T1154"] = ok


# ============================================================
print()
print("=" * 72)
print("T1160 - action_trigger_now by approver succeeds")
print("=" * 72)
mt_partner = env["res.partner"].create({
    "name": "T1160 partner", "is_company": True,
})
Term.create({
    "partner_id": mt_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
q_t1160, _ = _new_quote(p=mt_partner, sched_lines=[
    {"sequence": 1, "stage": "final",
     "trigger": "on_date",
     "trigger_date": date.today() + timedelta(days=14),
     "percentage": 100.0},
])
q_t1160.sudo().with_user(sales_user).action_accept()
sched_t1160 = q_t1160.invoice_schedule_ids
err, _ = _try(lambda: sched_t1160.sudo().with_user(
    approver_user).action_trigger_now())
sched_t1160.invalidate_recordset()
ok = err is None and sched_t1160.state in ("invoiced", "paid")
print("  err:", err, "state:", sched_t1160.state)
print("T1160:", "PASS" if ok else "FAIL")
results["T1160"] = ok


# ============================================================
print()
print("=" * 72)
print("T1162 - action_trigger_now on invoiced raises UserError")
print("=" * 72)
err, _ = _try(lambda: sched_t1160.sudo().with_user(
    approver_user).action_trigger_now())
ok = isinstance(err, UserError)
print("  err:", type(err).__name__ if err else "None")
print("T1162:", "PASS" if ok else "FAIL")
results["T1162"] = ok


# ============================================================
print()
print("=" * 72)
print("T1170 - invoice_schedule perm_unlink=0 for all roles")
print("=" * 72)
acl_rows = env["ir.model.access"].search([
    ("model_id.model", "=", "neon.finance.invoice.schedule"),
])
ok = bool(acl_rows) and all(r.perm_unlink is False for r in acl_rows)
print("  rows:", len(acl_rows), "all no-unlink:", ok)
print("T1170:", "PASS" if ok else "FAIL")
results["T1170"] = ok


# ============================================================
print()
print("=" * 72)
print("T1171 - template perm_unlink=0 for all roles")
print("=" * 72)
acl_rows = env["ir.model.access"].search([
    ("model_id.model", "=", "neon.finance.invoice.schedule.template"),
])
ok = bool(acl_rows) and all(r.perm_unlink is False for r in acl_rows)
print("  rows:", len(acl_rows), "all no-unlink:", ok)
print("T1171:", "PASS" if ok else "FAIL")
results["T1171"] = ok


# ============================================================
print()
print("=" * 72)
print("T1172 - template_line perm_unlink=0 for all roles")
print("=" * 72)
acl_rows = env["ir.model.access"].search([
    ("model_id.model", "=", "neon.finance.invoice.schedule.template.line"),
])
ok = bool(acl_rows) and all(r.perm_unlink is False for r in acl_rows)
print("  rows:", len(acl_rows), "all no-unlink:", ok)
print("T1172:", "PASS" if ok else "FAIL")
results["T1172"] = ok


# ============================================================
print()
print("=" * 72)
print("T1180 - sales sees only own quote's schedules")
print("=" * 72)
# Build a quote owned by other_user (not sales_user)
foreign_partner = env["res.partner"].create({
    "name": "T1180 foreign", "is_company": True,
})
Term.create({
    "partner_id": foreign_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
# Give other_user the sales group for the test
other_user.sudo().write({"groups_id": [(4, sales_group.id)]})
q_foreign, _ = _new_quote(p=foreign_partner, sp=other_user,
                          sched_lines=[
    {"sequence": 1, "stage": "deposit",
     "trigger": "on_acceptance", "percentage": 100.0},
])
visible = Sched.with_user(sales_user).search([])
ok = q_foreign.invoice_schedule_ids[0].id not in visible.ids
print("  foreign sched id:", q_foreign.invoice_schedule_ids[0].id,
      "in visible:", q_foreign.invoice_schedule_ids[0].id in visible.ids)
print("T1180:", "PASS" if ok else "FAIL")
results["T1180"] = ok


# ============================================================
print()
print("=" * 72)
print("T1182 - bookkeeper sees all schedules")
print("=" * 72)
all_count = Sched.sudo().search_count([])
book_count = Sched.with_user(book_user).search_count([])
ok = all_count == book_count and all_count > 0
print("  all:", all_count, "book:", book_count)
print("T1182:", "PASS" if ok else "FAIL")
results["T1182"] = ok


# ============================================================
print()
print("=" * 72)
print("T1183 - approver sees all schedules")
print("=" * 72)
appr_count = Sched.with_user(approver_user).search_count([])
ok = appr_count == all_count
print("  approver:", appr_count, "/ all:", all_count)
print("T1183:", "PASS" if ok else "FAIL")
results["T1183"] = ok


# ============================================================
print()
print("=" * 72)
print("T1190 - schedule.name pattern = SCH-NNNNNN")
print("=" * 72)
name = q_t1130.invoice_schedule_ids[0].name
ok = bool(re.match(r"^SCH-\d{6,}$", name))
print("  name:", name)
print("T1190:", "PASS" if ok else "FAIL")
results["T1190"] = ok


# ============================================================
print()
print("=" * 72)
print("T1191 - invoice ref captures schedule.name")
print("=" * 72)
move = q_t1130.invoice_schedule_ids[0].invoice_id
ok = move and name in (move.ref or "") + " " + (move.invoice_origin or "")
print("  ref:", move.ref, "origin:", move.invoice_origin)
print("T1191:", "PASS" if ok else "FAIL")
results["T1191"] = ok


# ============================================================
print()
print("=" * 72)
print("T1192 - invoice currency matches quote currency")
print("=" * 72)
ok = move.currency_id.id == usd.id
print("  invoice currency:", move.currency_id.name,
      "quote currency:", q_t1130.currency_id.name)
print("T1192:", "PASS" if ok else "FAIL")
results["T1192"] = ok


# ============================================================
print()
print("=" * 72)
print("T1194 - schedule.state = invoiced post action_create_invoice")
print("=" * 72)
ok = q_t1130.invoice_schedule_ids[0].state in ("invoiced", "paid")
print("  state:", q_t1130.invoice_schedule_ids[0].state)
print("T1194:", "PASS" if ok else "FAIL")
results["T1194"] = ok


# ============================================================
print()
print("=" * 72)
print("T1195 - state guard: re-trigger on invoiced is no-op or UserError")
print("=" * 72)
pre_invoice = q_t1130.invoice_schedule_ids[0].invoice_id.id
err, _ = _try(lambda: q_t1130.invoice_schedule_ids[
    0].sudo().action_create_invoice())
q_t1130.invalidate_recordset()
post_invoice = q_t1130.invoice_schedule_ids[0].invoice_id.id
# Either raises OR no-ops (preserved invoice id). Both are acceptable
# safety semantics; assert at least one held.
ok = isinstance(err, UserError) or post_invoice == pre_invoice
print("  err:", type(err).__name__ if err else "None",
      "invoice preserved:", post_invoice == pre_invoice)
print("T1195:", "PASS" if ok else "FAIL")
results["T1195"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = (
    ["T%d" % i for i in (1100, 1101, 1102, 1103,
                          1104, 1105, 1106,
                          1110, 1111, 1112, 1113, 1114,
                          1118, 1119, 1120,
                          1130, 1131, 1132,
                          1140, 1141, 1142, 1143,
                          1150, 1151, 1152, 1153, 1154,
                          1160, 1162,
                          1170, 1171, 1172,
                          1180, 1182, 1183,
                          1190, 1191, 1192, 1194, 1195)]
)
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
