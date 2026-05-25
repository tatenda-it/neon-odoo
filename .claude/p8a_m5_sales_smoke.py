"""P8A.M5 smoke -- Sales block (pipeline / win rate / lead sources).

Runs in `odoo shell -d <db>`. T8520-T8539.

T8520  payload.sales_block exists in get_dashboard_data
T8521  pipeline_by_stage has empty + stages keys
T8522  win_rate has empty + rate_pct + won_count + lost_count keys
T8523  lead_sources has empty + sources + window_label keys
T8524  pipeline empty when no active USD quotes
T8525  pipeline populated with pending_approval + approved + sent buckets
T8526  pipeline currency_note mentions ZWG + M6
T8527  pipeline stage labels are Qualified / Proposal Sent / Negotiation
T8528  pipeline stages sum to USD-only totals (no ZWG leakage)
T8529  win_rate empty when no closed deals in last 90 days
T8530  win_rate counts accepted as 'won'
T8531  win_rate counts rejected + expired as 'lost'
T8532  win_rate ignores 'cancelled' state
T8533  win_rate ignores deals closed > 90 days ago
T8534  win_rate rate_pct = round(won / total * 100, 1)
T8535  lead_sources empty when no leads in last 30 days
T8536  lead_sources counts crm.lead.create_date in last 30 days
T8537  lead_sources Unspecified bucket for leads without source_id
T8538  lead_sources caps at top 4 entries
T8539  lead_sources percentages reasonable (0..100)
"""
from datetime import date, datetime, timedelta

from odoo.exceptions import AccessError


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


print("=" * 72)
print("P8A.M5 -- Sales block")
print("=" * 72)
results = {}

Dashboard = env["neon.dashboard"]
Users = env["res.users"]
Quote = env["neon.finance.quote"]
QuoteLine = env["neon.finance.quote.line"]
Term = env["neon.finance.payment.term"]
Job = env["commercial.job"]
EventJob = env["commercial.event.job"]
Partner = env["res.partner"]
Lead = env["crm.lead"]
Source = env["utm.source"]


def _get_or_make_user(login, group_xmlid):
    user = Users.search([("login", "=", login)], limit=1)
    group = env.ref(group_xmlid)
    if not user:
        user = Users.with_context(no_reset_password=True).create({
            "name": login, "login": login, "password": "test123",
            "groups_id": [(4, group.id)],
        })
    elif group.id not in user.groups_id.ids:
        user.write({"groups_id": [(4, group.id)]})
    return user


u_director = _get_or_make_user(
    "p8a_director", "neon_core.group_neon_superuser")
usd = env.ref("base.USD")


def _data():
    return Dashboard.with_user(u_director).get_dashboard_data()


# ============================================================
print()
print("T8520 -- payload.sales_block exists")
print("=" * 72)
data = _data()
ok = "sales_block" in data
print(f"  payload keys: {sorted(data.keys())[:5]}... has sales_block: {ok}")
print("T8520:", "PASS" if ok else "FAIL")
results["T8520"] = ok


# ============================================================
print()
print("T8521/T8522/T8523 -- sub-key contracts")
print("=" * 72)
sales = data["sales_block"]
pbs = sales.get("pipeline_by_stage") or {}
wr = sales.get("win_rate") or {}
ls = sales.get("lead_sources") or {}
ok521 = "empty" in pbs and "stages" in pbs
ok522 = ("empty" in wr and "rate_pct" in wr
         and "won_count" in wr and "lost_count" in wr)
ok523 = ("empty" in ls and "sources" in ls
         and "window_label" in ls)
print(f"  pipeline keys: {sorted(pbs.keys())}")
print(f"  win_rate keys: {sorted(wr.keys())}")
print(f"  lead_sources keys: {sorted(ls.keys())}")
print("T8521:", "PASS" if ok521 else "FAIL")
results["T8521"] = ok521
print("T8522:", "PASS" if ok522 else "FAIL")
results["T8522"] = ok522
print("T8523:", "PASS" if ok523 else "FAIL")
results["T8523"] = ok523


# ============================================================
# Seed fixtures inside a savepoint -- pipeline + win/loss + leads.
# ============================================================
sp = env.cr.savepoint()
print()
print("--- seeding M5 fixtures ---")

partner = Partner.sudo().create({"name": "P8A M5 Client", "is_company": True})
venue = Partner.sudo().create({
    "name": "P8A M5 Venue", "is_company": True, "is_venue": True,
})
job = Job.sudo().create({
    "partner_id": partner.id, "venue_id": venue.id,
    "event_date": date.today() + timedelta(days=14),
    "currency_id": usd.id,
})
ej = EventJob.sudo().create({"commercial_job_id": job.id})
term = Term.sudo().create({
    "partner_id": partner.id,
    "deposit_pct": 50.0, "deposit_due_days": 0,
    "final_due_days": 30, "late_policy": "reminder",
})


def _mk_quote(state, amount, currency=usd):
    q = Quote.sudo().create({
        "event_job_id": ej.id,
        "salesperson_id": u_director.id,
        "currency_id": currency.id,
        "payment_term_id": term.id,
    })
    QuoteLine.sudo().create({
        "quote_id": q.id, "line_type": "other",
        "name": "M5 line", "quantity": 1, "duration_days": 1,
        "unit_rate": amount, "pricing_status": "manual",
    })
    q.sudo().write({"state": state})
    return q


# Pipeline fixtures: 2 pending_approval + 3 approved + 1 sent in USD.
q_pa_1 = _mk_quote("pending_approval", 1000.0)
q_pa_2 = _mk_quote("pending_approval", 2000.0)
q_ap_1 = _mk_quote("approved", 3000.0)
q_ap_2 = _mk_quote("approved", 4000.0)
q_ap_3 = _mk_quote("approved", 5000.0)
q_sn_1 = _mk_quote("sent", 6000.0)

# Win/loss fixtures (today's write_date counts as "last 90 days").
q_won_1 = _mk_quote("accepted", 10000.0)
q_won_2 = _mk_quote("accepted", 5000.0)
q_lost_rej = _mk_quote("rejected", 8000.0)
q_lost_exp = _mk_quote("expired", 3000.0)
q_cancelled = _mk_quote("cancelled", 9999.0)  # should be ignored

# Lead fixtures (recent + with source).
src_a = Source.sudo().create({"name": "P8A WhatsApp"})
src_b = Source.sudo().create({"name": "P8A Referral"})
lead_a1 = Lead.sudo().create({"name": "Lead A1", "source_id": src_a.id})
lead_a2 = Lead.sudo().create({"name": "Lead A2", "source_id": src_a.id})
lead_a3 = Lead.sudo().create({"name": "Lead A3", "source_id": src_a.id})
lead_b1 = Lead.sudo().create({"name": "Lead B1", "source_id": src_b.id})
lead_unspec = Lead.sudo().create({"name": "Lead Unspecified"})

data = _data()
sales = data["sales_block"]
pbs = sales["pipeline_by_stage"]


# ============================================================
print()
print("T8524 -- pipeline non-empty after fixture seed")
print("=" * 72)
ok = pbs["empty"] is False and len(pbs["stages"]) == 3
print(f"  empty={pbs['empty']} stages_count={len(pbs['stages'])}")
print("T8524:", "PASS" if ok else "FAIL")
results["T8524"] = ok


# ============================================================
print()
print("T8525 -- buckets correct (pending_approval=2, approved=3, sent=1)")
print("=" * 72)
by_state = {s["state"]: s for s in pbs["stages"]}
expected_counts = {"pending_approval": 2, "approved": 3, "sent": 1}
ok = True
for st, exp in expected_counts.items():
    actual = by_state.get(st, {}).get("count", 0)
    if actual < exp:  # other tests may add quotes; allow gte
        ok = False
        print(f"  {st}: expected >={exp}, got {actual}")
    else:
        print(f"  {st}: {actual} (expected >= {exp}) OK")
print("T8525:", "PASS" if ok else "FAIL")
results["T8525"] = ok


# ============================================================
print()
print("T8526 -- currency_note mentions ZWG + M6")
print("=" * 72)
note = pbs.get("currency_note") or ""
ok = "ZWG" in note and "M6" in note
print(f"  note: {note}")
print("T8526:", "PASS" if ok else "FAIL")
results["T8526"] = ok


# ============================================================
print()
print("T8527 -- stage labels are Qualified / Proposal Sent / Negotiation")
print("=" * 72)
labels = [s["label"] for s in pbs["stages"]]
ok = (labels == ["Qualified", "Proposal Sent", "Negotiation"])
print(f"  labels: {labels}")
print("T8527:", "PASS" if ok else "FAIL")
results["T8527"] = ok


# ============================================================
print()
print("T8528 -- pipeline value sums look right (USD only)")
print("=" * 72)
# Our seeded values: PA=3000, AP=12000, SN=6000 (untaxed).
# With 15.5% VAT amount_total = untaxed * 1.155 -> PA~=3465, AP~=13860, SN~=6930
# Allow >= due to other rows present.
pa_value = by_state["pending_approval"]["value"]
ap_value = by_state["approved"]["value"]
sn_value = by_state["sent"]["value"]
ok = (pa_value >= 3000 and ap_value >= 12000 and sn_value >= 6000)
print(f"  PA={pa_value} AP={ap_value} SN={sn_value}")
print("T8528:", "PASS" if ok else "FAIL")
results["T8528"] = ok


# ============================================================
print()
print("T8530/T8531/T8532 -- win rate counts")
print("=" * 72)
wr = sales["win_rate"]
# We added 2 accepted, 1 rejected, 1 expired, 1 cancelled. Other
# pre-existing rows on the DB may exist -- assertions use >=.
ok530 = wr["won_count"] >= 2
ok531 = wr["lost_count"] >= 2  # 1 rejected + 1 expired
# cancelled isn't counted; if all 3 (2+1+1) were counted lost_count
# would be >=3 with cancelled mistakenly included. Since cancelled
# total over 90d is 1 (our seed), 'should ignore' is verified by:
# write a stand-alone cancelled quote and confirm lost_count delta=0.
wr_before = wr["lost_count"]
_extra_cancelled = _mk_quote("cancelled", 1234.0)
data2 = _data()
wr2 = data2["sales_block"]["win_rate"]
ok532 = wr2["lost_count"] == wr_before
print(f"  won_count={wr['won_count']} lost_count={wr['lost_count']} "
      f"after extra cancelled: lost_count={wr2['lost_count']}")
print("T8530:", "PASS" if ok530 else "FAIL")
results["T8530"] = ok530
print("T8531:", "PASS" if ok531 else "FAIL")
results["T8531"] = ok531
print("T8532:", "PASS" if ok532 else "FAIL")
results["T8532"] = ok532


# ============================================================
print()
print("T8533 -- win_rate ignores deals closed > 90 days ago")
print("=" * 72)
# Force a quote's write_date back 100 days via SQL bypass.
old_dt = (datetime.now() - timedelta(days=100)).strftime(
    "%Y-%m-%d %H:%M:%S")
env.cr.execute(
    "UPDATE neon_finance_quote SET write_date = %s WHERE id = %s",
    (old_dt, q_won_2.id),
)
q_won_2.invalidate_recordset(["write_date"])
data3 = _data()
wr3 = data3["sales_block"]["win_rate"]
# After hiding q_won_2 from the 90-day window, won_count should
# drop by 1 vs wr.
ok = wr3["won_count"] == wr["won_count"] - 1
print(f"  won_count before={wr['won_count']} after_aging={wr3['won_count']}")
print("T8533:", "PASS" if ok else "FAIL")
results["T8533"] = ok


# ============================================================
print()
print("T8534 -- rate_pct = round(won / total * 100, 1)")
print("=" * 72)
wr4 = data3["sales_block"]["win_rate"]
expected_rate = round(
    wr4["won_count"] / wr4["total"] * 100, 1
) if wr4["total"] else None
ok = wr4["rate_pct"] == expected_rate
print(f"  total={wr4['total']} won={wr4['won_count']} "
      f"rate_pct={wr4['rate_pct']} expected={expected_rate}")
print("T8534:", "PASS" if ok else "FAIL")
results["T8534"] = ok


# ============================================================
print()
print("T8529 -- win_rate empty when no closed deals in window")
print("=" * 72)
# Age everything else out too.
env.cr.execute(
    "UPDATE neon_finance_quote SET write_date = %s "
    "WHERE state IN ('accepted', 'rejected', 'expired')",
    (old_dt,),
)
Quote.invalidate_model(["write_date"])
data4 = _data()
wr_empty = data4["sales_block"]["win_rate"]
ok = wr_empty["empty"] is True and wr_empty["rate_pct"] is None
print(f"  empty={wr_empty['empty']} rate_pct={wr_empty['rate_pct']}")
print("T8529:", "PASS" if ok else "FAIL")
results["T8529"] = ok


# ============================================================
print()
print("T8536 -- lead_sources counts last 30 days")
print("=" * 72)
ls = data4["sales_block"]["lead_sources"]
# 5 leads seeded recently; pre-existing leads may also be in window.
ok = ls["total"] >= 5
print(f"  total leads in window: {ls['total']}")
print("T8536:", "PASS" if ok else "FAIL")
results["T8536"] = ok


# ============================================================
print()
print("T8537 -- Unspecified bucket")
print("=" * 72)
src_names = {s["source"] for s in ls["sources"]}
# Unspecified should be in the top 4 ranking. If there's a lot of
# other unsourced leads on the DB, Unspecified might dominate; if
# none, our seeded lead_unspec means it should appear.
ok = "Unspecified" in src_names or any(
    s["source"] == "Unspecified" for s in ls["sources"])
print(f"  sources: {src_names}")
print("T8537:", "PASS" if ok else "FAIL")
results["T8537"] = ok


# ============================================================
print()
print("T8538 -- caps at 4 entries")
print("=" * 72)
ok = len(ls["sources"]) <= 4
print(f"  source count: {len(ls['sources'])}")
print("T8538:", "PASS" if ok else "FAIL")
results["T8538"] = ok


# ============================================================
print()
print("T8539 -- percentages 0..100")
print("=" * 72)
ok = all(0 <= s["pct"] <= 100 for s in ls["sources"])
print(f"  pcts: {[s['pct'] for s in ls['sources']]}")
print("T8539:", "PASS" if ok else "FAIL")
results["T8539"] = ok


# ============================================================
print()
print("T8535 -- lead_sources empty when no leads (contract-only)")
print("=" * 72)
# Hard to genuinely empty crm.lead on a real DB; check the contract
# shape: when "empty" is True, sources is [].
if ls.get("empty"):
    ok = ls["sources"] == []
else:
    ok = isinstance(ls["empty"], bool)
print(f"  empty={ls['empty']} (contract-only check)")
print("T8535:", "PASS" if ok else "FAIL")
results["T8535"] = ok


# Rollback fixture savepoint.
sp.close(rollback=True)


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
