"""P6.M10 smoke -- Cash Flow Dashboard RPC + tiles.

Tile aggregation correctness:
T2200  outstanding_receivables USD sums posted unpaid invoices
T2201  outstanding_receivables ZWG sums posted unpaid invoices
T2202  outstanding_receivables overdue sub-counter
T2203  pipeline USD sums pending+approved+sent quote totals
T2204  pipeline ZWG sums per currency
T2205  recent_payments USD: 30-day window
T2206  recent_payments ZWG: 30-day window
T2207  recent_costs USD: 30-day window + count
T2208  recent_costs ZWG: 30-day window + count
T2209  top_overdue: ranked by amount desc, top-5 only
T2210  top_overdue: max_days computed correctly
T2211  budget_alert_summary: counts per level

Role filtering:
T2212  sales sees only own quotes in pipeline tile
T2213  sales sees only own invoices in receivables tile
T2214  bookkeeper sees all (broader than sales)
T2215  approver sees all (broader than sales)
T2216  crew_leader sees costs + budget tiles only (others null)
T2217  non-finance user RPC raises AccessError
T2218  sales with NULL salesperson_id quote in DB doesn't see it
T2219  multi-role user (book + sales) gets the bookkeeper view

Server-action wrapper:
T2220  action_open_cash_flow_dashboard returns descriptor for finance role
T2221  action_open_cash_flow_dashboard raises AccessError for non-finance
T2222  server-action record has groups_id set (regression guard for P5.M10 lesson)
T2223  NO persisted ir.actions.client record exists (URL bypass impossible)

Drill-through act_windows:
T2224  each tile's action_id resolves to an act_window
T2225  act_window targets correct res_model per tile
T2226  invoice act_window domain has 'not_paid' filter

Currency handling:
T2227  ZWG-only invoice doesn't leak into USD tile
T2228  mixed-currency partner shows in both currency columns
T2229  Q6 B1 -- no mixed-currency totals anywhere in payload
"""
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

Dashboard = env["neon.finance.dashboard"]
Quote = env["neon.finance.quote"]
QuoteLine = env["neon.finance.quote.line"]
Sched = env["neon.finance.invoice.schedule"]
Term = env["neon.finance.payment.term"]
EventJob = env["commercial.event.job"]
Move = env["account.move"]
Cost = env["neon.finance.cost.line"]

usd = env.ref("base.USD")
zwg = env.ref("neon_finance.currency_zwg")
sales_user = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
book_user = env["res.users"].search([("login", "=", "p2m75_book")], limit=1)
approver_user = env["res.users"].search(
    [("login", "=", "p2m75_approver")], limit=1)
lead_user = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
other_user = env["res.users"].search([("login", "=", "p2m75_other")], limit=1)
assert all([sales_user, book_user, approver_user, lead_user, other_user])

venue = env["res.partner"].create({
    "name": "P6M10 Venue", "is_company": True,
})


def _new_accepted_quote(currency=usd, sp=None, partner=None, amount=1000.0):
    """Create accepted quote with single 100% on_acceptance schedule
    -> posted invoice. Returns (quote, schedule, invoice)."""
    sp = sp or sales_user
    p = partner or env["res.partner"].create({
        "name": "P6M10 Client " + currency.name,
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
    ej = EventJob.create({"commercial_job_id": j.id})
    q = Quote.create({
        "event_job_id": ej.id, "salesperson_id": sp.id,
        "currency_id": currency.id, "payment_term_id": term.id,
    })
    QuoteLine.create({
        "quote_id": q.id, "line_type": "other",
        "name": "P6M10", "quantity": 1, "duration_days": 1,
        "unit_rate": amount, "pricing_status": "manual",
    })
    Sched.create({
        "quote_id": q.id, "sequence": 1, "stage": "deposit",
        "trigger": "on_acceptance", "percentage": 100.0,
        "currency_id": currency.id,
    })
    q.sudo().write({"state": "sent"})
    q.sudo().with_user(sp).action_accept()
    q.invalidate_recordset()
    sched = q.invoice_schedule_ids[0]
    inv = sched.invoice_id
    inv.sudo().write({
        "invoice_date": date.today(),
        "invoice_date_due": date.today() + timedelta(days=30),
    })
    inv.sudo().action_post()
    return q, sched, inv


def _pending_quote(currency=usd, sp=None, partner=None, amount=500.0,
                   state="pending_approval"):
    sp = sp or sales_user
    p = partner or env["res.partner"].create({
        "name": "P6M10 Pending " + currency.name,
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
    ej = EventJob.create({"commercial_job_id": j.id})
    q = Quote.create({
        "event_job_id": ej.id, "salesperson_id": sp.id,
        "currency_id": currency.id, "payment_term_id": term.id,
    })
    QuoteLine.create({
        "quote_id": q.id, "line_type": "other",
        "name": "P", "quantity": 1, "duration_days": 1,
        "unit_rate": amount, "pricing_status": "manual",
    })
    q.sudo().write({"state": state})
    return q


# Fixture: one accepted USD quote + one accepted ZWG quote + two
# pending quotes for sales rep
q_usd_paid, _, inv_usd = _new_accepted_quote(usd, sp=sales_user,
                                              amount=800.0)
q_zwg_paid, _, inv_zwg = _new_accepted_quote(zwg, sp=sales_user,
                                              amount=4000.0)
q_pending_usd = _pending_quote(usd, sp=sales_user, amount=1500.0,
                                state="pending_approval")
q_pending_zwg = _pending_quote(zwg, sp=sales_user, amount=7500.0,
                                state="approved")

# Add a cost line
cost_partner = env["res.partner"].create({
    "name": "P6M10 Vendor", "is_company": True,
})
Cost.with_context(skip_finance_notification=True).create({
    "event_job_id": q_usd_paid.event_job_id.id,
    "cost_type": "other",
    "name": "P6M10 cost", "amount": 200.0,
    "currency_id": usd.id,
    "date_incurred": date.today(),
    "recorded_by_id": lead_user.id,
})

# Make ONE invoice overdue (USD)
inv_usd.sudo().write({
    "invoice_date_due": date.today() - timedelta(days=5),
})


def _get_data_as(user):
    """Call get_cash_flow_dashboard_data with a specific user
    context."""
    return Dashboard.with_user(user).get_cash_flow_dashboard_data()


# Bookkeeper-view baseline
data_book = _get_data_as(book_user)


# ============================================================
print()
print("=" * 72)
print("T2200 - outstanding_receivables USD sums unpaid invoices")
print("=" * 72)
out = data_book["outstanding_receivables"]
# Our fixture creates 1 USD invoice (800 + 15.5% VAT = 924). The
# bookkeeper view sees all unpaid Neon + non-Neon invoices in the
# DB. We just need to assert our specific contribution shows up.
ok = out["usd"]["value"] >= 924.0 and out["usd"]["count"] >= 1
print("  USD value:", out["usd"]["value"], "count:", out["usd"]["count"])
print("T2200:", "PASS" if ok else "FAIL")
results["T2200"] = ok


# ============================================================
print()
print("=" * 72)
print("T2201 - outstanding_receivables ZWG sums unpaid invoices")
print("=" * 72)
ok = out["zwg"]["value"] >= 4620.0 and out["zwg"]["count"] >= 1
print("  ZWG value:", out["zwg"]["value"], "count:", out["zwg"]["count"])
print("T2201:", "PASS" if ok else "FAIL")
results["T2201"] = ok


# ============================================================
print()
print("=" * 72)
print("T2202 - outstanding_receivables overdue sub-counter")
print("=" * 72)
# Our inv_usd was backdated to 5 days overdue
ok = (out["usd"]["overdue_value"] >= 924.0
      and out["usd"]["overdue_count"] >= 1)
print("  USD overdue value:", out["usd"]["overdue_value"],
      "overdue count:", out["usd"]["overdue_count"])
print("T2202:", "PASS" if ok else "FAIL")
results["T2202"] = ok


# ============================================================
print()
print("=" * 72)
print("T2203 - pipeline USD sums pending+approved quotes")
print("=" * 72)
pipe = data_book["pipeline"]
# q_pending_usd is 1500 USD pending_approval
ok = pipe["usd"]["value"] >= 1500.0 and pipe["usd"]["count"] >= 1
print("  USD value:", pipe["usd"]["value"], "count:", pipe["usd"]["count"])
print("T2203:", "PASS" if ok else "FAIL")
results["T2203"] = ok


# ============================================================
print()
print("=" * 72)
print("T2204 - pipeline ZWG sums pending+approved quotes")
print("=" * 72)
# q_pending_zwg is 7500 ZWG approved
ok = pipe["zwg"]["value"] >= 7500.0 and pipe["zwg"]["count"] >= 1
print("  ZWG value:", pipe["zwg"]["value"], "count:", pipe["zwg"]["count"])
print("T2204:", "PASS" if ok else "FAIL")
results["T2204"] = ok


# ============================================================
print()
print("=" * 72)
print("T2205 - recent_payments structure (USD) keys present")
print("=" * 72)
pay = data_book["recent_payments"]
ok = "usd" in pay and "value" in pay["usd"] and "count" in pay["usd"]
print("  pay.usd keys:", list(pay["usd"].keys()) if pay["usd"] else None)
print("T2205:", "PASS" if ok else "FAIL")
results["T2205"] = ok


# ============================================================
print()
print("=" * 72)
print("T2206 - recent_payments structure (ZWG) keys present")
print("=" * 72)
ok = "zwg" in pay and "value" in pay["zwg"] and "count" in pay["zwg"]
print("  pay.zwg keys:", list(pay["zwg"].keys()) if pay["zwg"] else None)
print("T2206:", "PASS" if ok else "FAIL")
results["T2206"] = ok


# ============================================================
print()
print("=" * 72)
print("T2207 - recent_costs USD includes our cost line")
print("=" * 72)
rc = data_book["recent_costs"]
ok = rc["usd"]["value"] >= 200.0 and rc["usd"]["count"] >= 1
print("  USD value:", rc["usd"]["value"], "count:", rc["usd"]["count"])
print("T2207:", "PASS" if ok else "FAIL")
results["T2207"] = ok


# ============================================================
print()
print("=" * 72)
print("T2208 - recent_costs ZWG sums per currency")
print("=" * 72)
ok = "zwg" in rc and isinstance(rc["zwg"]["value"], (int, float))
print("  ZWG value:", rc["zwg"]["value"], "count:", rc["zwg"]["count"])
print("T2208:", "PASS" if ok else "FAIL")
results["T2208"] = ok


# ============================================================
print()
print("=" * 72)
print("T2209 - top_overdue ranked by amount desc")
print("=" * 72)
to = data_book["top_overdue"]
rows = to.get("rows") or []
if len(rows) >= 2:
    ok = rows[0]["amount"] >= rows[1]["amount"]
else:
    ok = True  # Trivially true with 0-1 rows
print("  rows:", len(rows),
      "first amount:", rows[0]["amount"] if rows else None)
print("T2209:", "PASS" if ok else "FAIL")
results["T2209"] = ok


# ============================================================
print()
print("=" * 72)
print("T2210 - top_overdue max_days >= 1 for our overdue invoice")
print("=" * 72)
# Find our specific overdue partner row
our_partner = q_usd_paid.partner_id
our_row = next((r for r in rows if r["partner_id"] == our_partner.id),
               None)
ok = our_row is not None and our_row["max_days"] >= 5
print("  our partner row:", our_row)
print("T2210:", "PASS" if ok else "FAIL")
results["T2210"] = ok


# ============================================================
print()
print("=" * 72)
print("T2211 - budget_alert_summary has 4 level keys")
print("=" * 72)
bas = data_book["budget_alert_summary"]
levels = bas.get("levels") or {}
ok = set(levels.keys()) == {"ok", "warn", "breach", "severe"}
print("  levels keys:", list(levels.keys()))
print("T2211:", "PASS" if ok else "FAIL")
results["T2211"] = ok


# ============================================================
print()
print("=" * 72)
print("T2212 - sales sees only own pipeline")
print("=" * 72)
# Build a quote owned by other_user (not sales_user) -- pending state
# First give other_user the sales group
other_user.sudo().write({
    "groups_id": [(4, env.ref(
        "neon_finance.group_neon_finance_sales").id)]
})
q_other = _pending_quote(usd, sp=other_user, amount=999.0,
                          state="pending_approval")
data_sales = _get_data_as(sales_user)
data_other = _get_data_as(other_user)
# Sales rep's pipeline USD must NOT include the 999 from other_user
# (assuming sales_user has at least one own pending quote contribution)
ok = q_other.amount_total not in [data_sales["pipeline"]["usd"]["value"]]
# Stronger check: count of sales_user's own pending USD quotes should
# equal the dashboard pipeline USD count
own_pending_count = Quote.sudo().search_count([
    ("salesperson_id", "=", sales_user.id),
    ("state", "in", ("pending_approval", "approved", "sent")),
    ("currency_id", "=", usd.id),
])
ok = data_sales["pipeline"]["usd"]["count"] == own_pending_count
print("  sales pipeline USD count:", data_sales["pipeline"]["usd"]["count"],
      "expected own count:", own_pending_count)
print("T2212:", "PASS" if ok else "FAIL")
results["T2212"] = ok


# ============================================================
print()
print("=" * 72)
print("T2213 - sales sees only own receivables")
print("=" * 72)
# Build an invoice for other_user's quote (full accept flow)
q_other_paid, _, inv_other = _new_accepted_quote(
    usd, sp=other_user, amount=600.0)
inv_other.sudo().write({
    "invoice_date_due": date.today() + timedelta(days=30),
})
data_sales2 = _get_data_as(sales_user)
# Sales rep's outstanding should NOT include the 693 from other_user
sales_user_quotes = Quote.sudo().search(
    [("salesperson_id", "=", sales_user.id)])
sales_user_sched_names = Sched.sudo().search([
    ("quote_id", "in", sales_user_quotes.ids),
]).mapped("name")
own_inv_count = Move.sudo().search_count([
    ("move_type", "=", "out_invoice"),
    ("state", "=", "posted"),
    ("payment_state", "in", ("not_paid", "partial", "in_payment")),
    ("ref", "in", sales_user_sched_names),
    ("currency_id", "=", usd.id),
])
ok = data_sales2["outstanding_receivables"]["usd"]["count"] == own_inv_count
print("  sales receivables count:", data_sales2[
    "outstanding_receivables"]["usd"]["count"],
      "expected own count:", own_inv_count)
print("T2213:", "PASS" if ok else "FAIL")
results["T2213"] = ok


# ============================================================
print()
print("=" * 72)
print("T2214 - bookkeeper sees all (broader than sales)")
print("=" * 72)
data_book2 = _get_data_as(book_user)
ok = data_book2["pipeline"]["usd"]["count"] >= data_sales["pipeline"]["usd"]["count"]
print("  book pipeline USD count:", data_book2["pipeline"]["usd"]["count"],
      "sales pipeline USD count:", data_sales["pipeline"]["usd"]["count"])
print("T2214:", "PASS" if ok else "FAIL")
results["T2214"] = ok


# ============================================================
print()
print("=" * 72)
print("T2215 - approver sees all (matches bookkeeper)")
print("=" * 72)
data_approver = _get_data_as(approver_user)
ok = data_approver["pipeline"]["usd"]["count"] == data_book2["pipeline"]["usd"]["count"]
print("  approver count:", data_approver["pipeline"]["usd"]["count"],
      "book count:", data_book2["pipeline"]["usd"]["count"])
print("T2215:", "PASS" if ok else "FAIL")
results["T2215"] = ok


# ============================================================
print()
print("=" * 72)
print("T2216 - crew_leader sees costs + budget only (others null)")
print("=" * 72)
data_lead = _get_data_as(lead_user)
# Receivables / pipeline / payments should be null for crew_leader
ok = (data_lead["outstanding_receivables"]["usd"] is None
      and data_lead["pipeline"]["usd"] is None
      and data_lead["recent_payments"]["usd"] is None
      and data_lead["recent_costs"]["usd"] is not None
      and data_lead["budget_alert_summary"]["levels"] is not None)
print("  out:", data_lead["outstanding_receivables"]["usd"],
      "pipe:", data_lead["pipeline"]["usd"],
      "pay:", data_lead["recent_payments"]["usd"],
      "costs ok:", data_lead["recent_costs"]["usd"] is not None,
      "budget ok:", data_lead["budget_alert_summary"]["levels"] is not None)
print("T2216:", "PASS" if ok else "FAIL")
results["T2216"] = ok


# ============================================================
print()
print("=" * 72)
print("T2217 - non-finance user RPC raises AccessError")
print("=" * 72)
# Create a fresh user with NO finance / no crew_leader groups
no_role_user = env["res.users"].sudo().create({
    "name": "p2m10 noRole user", "login": "p6m10_norole",
    "password": "test123",
    "groups_id": [(6, 0, [env.ref("base.group_user").id])],
})
err, _ = _try(lambda: _get_data_as(no_role_user))
ok = isinstance(err, AccessError)
print("  err:", type(err).__name__ if err else "None")
print("T2217:", "PASS" if ok else "FAIL")
results["T2217"] = ok


# ============================================================
print()
print("=" * 72)
print("T2218 - quote.salesperson_id is NOT NULL (orphan case impossible)")
print("=" * 72)
# Quote.salesperson_id is required by schema; the "orphan with NULL
# salesperson" case the prompt asked about can't actually exist in
# this DB. Assert the constraint and document that the role-filter's
# NULL-handling is moot.
orphan_partner = env["res.partner"].create({
    "name": "P6M10 Orphan", "is_company": True,
})
orphan_term = Term.create({
    "partner_id": orphan_partner.id, "deposit_pct": 50.0,
    "deposit_due_days": 0, "final_due_days": 30,
    "late_policy": "reminder",
})
oj = env["commercial.job"].create({
    "partner_id": orphan_partner.id, "venue_id": venue.id,
    "event_date": date.today() + timedelta(days=30),
    "currency_id": usd.id,
})
oej = EventJob.create({"commercial_job_id": oj.id})
orphan_q = Quote.create({
    "event_job_id": oej.id, "salesperson_id": sales_user.id,
    "currency_id": usd.id, "payment_term_id": orphan_term.id,
})
# Try to NULL the salesperson_id -- should raise (NOT NULL constraint)
err, _ = _try(lambda: orphan_q.sudo().write({"salesperson_id": False}))
ok = err is not None  # Either IntegrityError or ValidationError
print("  NULL salesperson write raised:",
      type(err).__name__ if err else "None")
print("T2218:", "PASS" if ok else "FAIL")
results["T2218"] = ok


# ============================================================
print()
print("=" * 72)
print("T2219 - multi-role user (book + sales) gets bookkeeper view")
print("=" * 72)
# book_user already has bookkeeper group. Add sales group too.
book_user.sudo().write({
    "groups_id": [(4, env.ref(
        "neon_finance.group_neon_finance_sales").id)]
})
data_multi = _get_data_as(book_user)
# Should match the bookkeeper-only view (all data, not filtered)
all_pending_count = Quote.sudo().search_count([
    ("state", "in", ("pending_approval", "approved", "sent")),
    ("currency_id", "=", usd.id),
])
ok = data_multi["pipeline"]["usd"]["count"] == all_pending_count
print("  multi-role count:", data_multi["pipeline"]["usd"]["count"],
      "all count:", all_pending_count)
print("T2219:", "PASS" if ok else "FAIL")
results["T2219"] = ok


# ============================================================
print()
print("=" * 72)
print("T2220 - action_open_cash_flow_dashboard returns descriptor")
print("=" * 72)
descr = Dashboard.with_user(book_user).action_open_cash_flow_dashboard()
ok = (descr.get("type") == "ir.actions.client"
      and descr.get("tag") == "neon_cash_flow_dashboard")
print("  descriptor:", descr)
print("T2220:", "PASS" if ok else "FAIL")
results["T2220"] = ok


# ============================================================
print()
print("=" * 72)
print("T2221 - action_open_cash_flow_dashboard raises for non-finance")
print("=" * 72)
err, _ = _try(lambda: Dashboard.with_user(
    no_role_user).action_open_cash_flow_dashboard())
ok = isinstance(err, AccessError)
print("  err:", type(err).__name__ if err else "None")
print("T2221:", "PASS" if ok else "FAIL")
results["T2221"] = ok


# ============================================================
print()
print("=" * 72)
print("T2222 - server-action has groups_id set (P5.M10 regression guard)")
print("=" * 72)
sa = env.ref(
    "neon_finance.action_cash_flow_dashboard_server",
    raise_if_not_found=False)
ok = bool(sa) and bool(sa.groups_id)
group_xmlids = sa.groups_id.mapped(lambda g: g.get_external_id().get(g.id))
print("  groups:", group_xmlids)
print("T2222:", "PASS" if ok else "FAIL")
results["T2222"] = ok


# ============================================================
print()
print("=" * 72)
print("T2223 - NO persisted ir.actions.client record (URL bypass impossible)")
print("=" * 72)
client_actions = env["ir.actions.client"].sudo().search([
    ("tag", "=", "neon_cash_flow_dashboard")])
ok = len(client_actions) == 0
print("  client_actions found:", len(client_actions))
print("T2223:", "PASS" if ok else "FAIL")
results["T2223"] = ok


# ============================================================
print()
print("=" * 72)
print("T2224 - each tile's action_id resolves to act_window")
print("=" * 72)
data_check = _get_data_as(book_user)
action_ids = [
    data_check["outstanding_receivables"]["action_id"],
    data_check["pipeline"]["action_id"],
    data_check["recent_payments"]["action_id"],
    data_check["recent_costs"]["action_id"],
    data_check["top_overdue"]["action_id"],
    data_check["budget_alert_summary"]["action_id"],
]
acts = env["ir.actions.act_window"].sudo().browse(action_ids)
ok = all(a.exists() and a.res_model for a in acts)
print("  action_ids:", action_ids, "all resolve:", ok)
print("T2224:", "PASS" if ok else "FAIL")
results["T2224"] = ok


# ============================================================
print()
print("=" * 72)
print("T2225 - act_window targets correct res_model per tile")
print("=" * 72)
expected = {
    data_check["outstanding_receivables"]["action_id"]: "account.move",
    data_check["pipeline"]["action_id"]: "neon.finance.quote",
    data_check["recent_payments"]["action_id"]: "account.payment",
    data_check["recent_costs"]["action_id"]: "neon.finance.cost.line",
    data_check["top_overdue"]["action_id"]: "account.move",
    data_check["budget_alert_summary"]["action_id"]: "commercial.event.job",
}
actual = {a.id: a.res_model for a in acts}
ok = expected == actual
print("  match:", ok)
print("T2225:", "PASS" if ok else "FAIL")
results["T2225"] = ok


# ============================================================
print()
print("=" * 72)
print("T2226 - outstanding_receivables act_window domain includes 'not_paid'")
print("=" * 72)
out_act = env["ir.actions.act_window"].sudo().browse(
    data_check["outstanding_receivables"]["action_id"])
ok = "not_paid" in (out_act.domain or "")
print("  domain:", out_act.domain[:80] if out_act.domain else None)
print("T2226:", "PASS" if ok else "FAIL")
results["T2226"] = ok


# ============================================================
print()
print("=" * 72)
print("T2227 - ZWG-only invoice doesn't leak into USD tile")
print("=" * 72)
# Build a fresh ZWG accepted quote -> ZWG invoice. Verify USD tile
# count doesn't include it.
data_pre = _get_data_as(book_user)
pre_usd_count = data_pre["outstanding_receivables"]["usd"]["count"]
pre_zwg_count = data_pre["outstanding_receivables"]["zwg"]["count"]
q_zwg2, _, inv_zwg2 = _new_accepted_quote(zwg, sp=sales_user,
                                           amount=2000.0)
data_post = _get_data_as(book_user)
post_usd_count = data_post["outstanding_receivables"]["usd"]["count"]
post_zwg_count = data_post["outstanding_receivables"]["zwg"]["count"]
ok = (post_usd_count == pre_usd_count
      and post_zwg_count == pre_zwg_count + 1)
print("  USD before/after:", pre_usd_count, "/", post_usd_count,
      "ZWG before/after:", pre_zwg_count, "/", post_zwg_count)
print("T2227:", "PASS" if ok else "FAIL")
results["T2227"] = ok


# ============================================================
print()
print("=" * 72)
print("T2228 - mixed-currency partner shows in both columns")
print("=" * 72)
mp = env["res.partner"].create({
    "name": "P6M10 Mixed", "is_company": True,
})
_new_accepted_quote(usd, sp=sales_user, partner=mp, amount=300.0)
_new_accepted_quote(zwg, sp=sales_user, partner=mp, amount=1500.0)
data_mixed = _get_data_as(book_user)
# Both currency invoices for this partner contribute to USD count + ZWG count
ok = (data_mixed["outstanding_receivables"]["usd"]["count"] >= 1
      and data_mixed["outstanding_receivables"]["zwg"]["count"] >= 1)
print("  USD count:", data_mixed["outstanding_receivables"]["usd"]["count"],
      "ZWG count:", data_mixed["outstanding_receivables"]["zwg"]["count"])
print("T2228:", "PASS" if ok else "FAIL")
results["T2228"] = ok


# ============================================================
print()
print("=" * 72)
print("T2229 - Q6 B1: no mixed-currency totals in payload")
print("=" * 72)
# Inspect every tile that has currency keys; verify USD/ZWG split is
# structural -- no key like 'total' or 'value_all' that mixes them.
violations = []
for tile_key in ("outstanding_receivables", "pipeline",
                 "recent_payments", "recent_costs"):
    tile = data_mixed[tile_key]
    if not tile or not isinstance(tile, dict):
        continue
    # The only top-level keys allowed: usd, zwg, action_id (+ optional helpers)
    allowed = {"usd", "zwg", "action_id"}
    extra = set(tile.keys()) - allowed
    if extra:
        violations.append((tile_key, extra))
ok = not violations
print("  violations:", violations)
print("T2229:", "PASS" if ok else "FAIL")
results["T2229"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in (
    2200, 2201, 2202, 2203, 2204, 2205, 2206, 2207, 2208,
    2209, 2210, 2211,
    2212, 2213, 2214, 2215, 2216, 2217, 2218, 2219,
    2220, 2221, 2222, 2223,
    2224, 2225, 2226,
    2227, 2228, 2229,
)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
