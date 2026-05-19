"""P6.M3 smoke -- pricing engine wiring.

T700  _find_pricing_rule returns the latest active rule for category x currency
T701  _find_pricing_rule with no matching rule returns empty recordset
T702  _find_pricing_rule honors effective_date <= today filter
T703  _find_pricing_rule honors active=True filter (archived rule skipped)
T704  _find_bracket finds an in-range bracket for total_days
T705  _find_bracket honors day_to=-1 open-ended tail
T706  _find_bracket returns empty when no bracket matches
T707  _decompose_days fallback returns (0, duration_days, 0) when event_job lacks day-type fields
T708  create() with line_type='equipment' + equipment_line_id stamps snapshot
T709  snapshot_taken flips True after engine runs
T710  pricing_status = 'priced' on successful engine run
T711  bracket_multiplier snapshotted on engine run
T712  day_breakdown_json populated with full structure
T713  unit_rate stamped as blended per-day rate (base * bracket * day_mult event)
T714  line_subtotal = qty * unit_rate * duration_days after compute
T715  manual line (no equipment_line_id, unit_rate>0) gets pricing_status='manual'
T716  duration_days edit after snapshot does NOT change unit_rate (snapshot frozen)
T717  action_recalculate_pricing clears snapshot + re-runs engine
T718  action_recalculate_pricing blocked when state != draft
T719  action_recalculate_pricing requires at least one line
T720  Recalculate restores fresh values when underlying rule changed
T721  No-rule path: pricing_status = 'no_rule', unit_rate unchanged
T722  Open-ended bracket (15+ days) priced correctly via day_to=-1
T723  Multi-day breakdown: 1d, 3d, 8d, 15d use correct bracket multipliers
T724  USD line resolves USD pricing rule (currency match)
T725  ZWG line resolves ZWG pricing rule (currency separation)
T726  Cross-currency: same category, different currency yields different rate
T727  bracket boundary: day_from inclusive, day_to inclusive (closed range)
"""
import json
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
Rule = env["neon.finance.pricing.rule"]
Bracket = env["neon.finance.pricing.bracket"]
Term = env["neon.finance.payment.term"]
Category = env["neon.equipment.category"]

usd = env.ref("base.USD")
zwg = env.ref("neon_finance.currency_zwg")
cat_sound = env.ref("neon_jobs.equipment_category_sound")
cat_visual = env.ref("neon_jobs.equipment_category_visual")
cat_lighting = env.ref("neon_jobs.equipment_category_lighting")

sales_user = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
assert sales_user, "Need p2m75_sales seed user (p2m7_5_smoke.py)."

partner = env["res.partner"].create({
    "name": "P6M3 Smoke Client", "is_company": True,
})
venue = env["res.partner"].create({
    "name": "P6M3 Smoke Venue", "is_company": True,
})
job = env["commercial.job"].create({
    "partner_id": partner.id, "venue_id": venue.id,
    "event_date": date.today() + timedelta(days=30),
    "currency_id": usd.id,
})
event_job = env["commercial.event.job"].create({
    "commercial_job_id": job.id,
})

# Need at least one equipment line on the event_job so quote.line can
# resolve a category. Use the workshop_item domain helper from M2 smoke
# pattern -- find or create a workshop product first.
product = env["product.template"].search(
    [("is_workshop_item", "=", True)], limit=1)
if not product:
    product = env["product.template"].create({
        "name": "P6M3 Smoke Product",
        "is_workshop_item": True,
    })
# Override the product's equipment_category for the test so we can
# steer category-based rule lookup. Sound category for the main tests.
product.equipment_category_id = cat_sound.id

ej_line_sound = env["commercial.event.job.equipment.line"].create({
    "event_job_id": event_job.id,
    "product_template_id": product.id,
    "quantity_planned": 1,
})

term = Term.create({
    "partner_id": partner.id,
    "deposit_pct": 50.0, "deposit_due_days": 0,
    "final_due_days": 30, "late_policy": "reminder",
})


# ============================================================
print()
print("=" * 72)
print("T700 - _find_pricing_rule returns latest active rule for category x currency")
print("=" * 72)
q_usd = Quote.create({
    "event_job_id": event_job.id, "currency_id": usd.id,
    "salesperson_id": sales_user.id, "payment_term_id": term.id,
})
probe_line = QuoteLine.new({
    "quote_id": q_usd.id, "line_type": "equipment",
    "name": "probe", "quantity": 1.0,
    "unit_rate": 0.0, "duration_days": 3,
    "equipment_line_id": ej_line_sound.id,
})
# new() doesn't persist or compute -- we exercise the lookup method directly
rule_found = probe_line._find_pricing_rule()
expected = Rule.search([
    ("category_id", "=", cat_sound.id),
    ("currency_id", "=", usd.id),
    ("active", "=", True),
    ("effective_date", "<=", date.today()),
], order="effective_date desc, id desc", limit=1)
ok = bool(rule_found) and rule_found == expected
print("  found:", rule_found.name if rule_found else None,
      "expected:", expected.name if expected else None)
print("T700:", "PASS" if ok else "FAIL")
results["T700"] = ok


# ============================================================
print()
print("=" * 72)
print("T701 - _find_pricing_rule no match returns empty recordset")
print("=" * 72)
# Use an event_job linked to a partner with no category bound, or
# manipulate: create a new category with no rule.
cat_nonexistent = Category.create({
    "name": "P6M3 Smoke No-Rule Category",
    "code": "p6m3_norule",
})
product_norule = env["product.template"].create({
    "name": "P6M3 No-Rule Product",
    "is_workshop_item": True,
    "equipment_category_id": cat_nonexistent.id,
})
ej_line_norule = env["commercial.event.job.equipment.line"].create({
    "event_job_id": event_job.id,
    "product_template_id": product_norule.id,
    "quantity_planned": 1,
})
probe = QuoteLine.new({
    "quote_id": q_usd.id, "line_type": "equipment",
    "name": "norule", "quantity": 1.0,
    "unit_rate": 0.0, "duration_days": 3,
    "equipment_line_id": ej_line_norule.id,
})
no_rule = probe._find_pricing_rule()
ok = not no_rule
print("  result:", no_rule)
print("T701:", "PASS" if ok else "FAIL")
results["T701"] = ok


# ============================================================
print()
print("=" * 72)
print("T702 - effective_date <= today filter")
print("=" * 72)
future_rule = Rule.create({
    "category_id": cat_sound.id, "currency_id": usd.id,
    "base_rate": 999.0,
    "effective_date": date.today() + timedelta(days=30),
})
probe = QuoteLine.new({
    "quote_id": q_usd.id, "line_type": "equipment",
    "name": "future", "quantity": 1.0,
    "unit_rate": 0.0, "duration_days": 3,
    "equipment_line_id": ej_line_sound.id,
})
found = probe._find_pricing_rule()
# Should NOT return the future-dated rule; should still return the
# seeded today-or-earlier rule.
ok = bool(found) and found != future_rule
print("  found:", found.name, "(NOT future_rule with effective_date=+30d)")
print("T702:", "PASS" if ok else "FAIL")
results["T702"] = ok


# ============================================================
print()
print("=" * 72)
print("T703 - active=True filter (archived rule skipped)")
print("=" * 72)
# Archive the seeded rule for sound + USD, create a NEW one with lower
# base_rate, see which one wins.
sound_usd_rule = env.ref("neon_finance.pricing_rule_sound_usd")
sound_usd_rule.active = False
# Pick a date that won't collide with the seeded sound USD rule
# (effective_date 2026-05-18 in the seed) or with the future rule
# created in T702.
backup_rule = Rule.create({
    "category_id": cat_sound.id, "currency_id": usd.id,
    "base_rate": 33.0,
    "effective_date": date.today() - timedelta(days=5),
})
probe = QuoteLine.new({
    "quote_id": q_usd.id, "line_type": "equipment",
    "name": "active filter", "quantity": 1.0,
    "unit_rate": 0.0, "duration_days": 3,
    "equipment_line_id": ej_line_sound.id,
})
found = probe._find_pricing_rule()
ok = bool(found) and found == backup_rule and found.base_rate == 33.0
print("  found:", found.name if found else None, "base_rate:", found.base_rate if found else None)
print("T703:", "PASS" if ok else "FAIL")
results["T703"] = ok
# Restore for downstream tests.
sound_usd_rule.active = True


# ============================================================
print()
print("=" * 72)
print("T704 - _find_bracket finds in-range bracket")
print("=" * 72)
rule = sound_usd_rule  # seeded: 1-2, 3-7, 8-14, 15--1
bracket_5d = QuoteLine._find_bracket(rule, 5)
ok = bool(bracket_5d) and bracket_5d.day_from == 3 and bracket_5d.day_to == 7
print("  bracket for 5 days:", bracket_5d.day_from, "-", bracket_5d.day_to,
      "multiplier:", bracket_5d.multiplier)
print("T704:", "PASS" if ok else "FAIL")
results["T704"] = ok


# ============================================================
print()
print("=" * 72)
print("T705 - day_to=-1 open-ended tail")
print("=" * 72)
bracket_30d = QuoteLine._find_bracket(rule, 30)
ok = bool(bracket_30d) and bracket_30d.day_from == 15 and bracket_30d.day_to == -1
print("  bracket for 30 days:", bracket_30d.day_from, "-", bracket_30d.day_to)
print("T705:", "PASS" if ok else "FAIL")
results["T705"] = ok


# ============================================================
print()
print("=" * 72)
print("T706 - no bracket match returns empty recordset")
print("=" * 72)
# Create a rule with brackets only covering 1-2 days.
narrow_rule = Rule.create({
    "category_id": cat_lighting.id, "currency_id": usd.id,
    "base_rate": 100.0,
    "effective_date": date.today() - timedelta(days=2),
})
Bracket.create({
    "rule_id": narrow_rule.id, "sequence": 10,
    "day_from": 1, "day_to": 2, "multiplier": 1.0,
})
no_bracket = QuoteLine._find_bracket(narrow_rule, 50)
ok = not no_bracket
print("  result for 50 days on narrow rule:", no_bracket)
print("T706:", "PASS" if ok else "FAIL")
results["T706"] = ok


# ============================================================
print()
print("=" * 72)
print("T707 - _decompose_days fallback (event_job lacks day-type fields)")
print("=" * 72)
probe = QuoteLine.new({
    "quote_id": q_usd.id, "line_type": "equipment",
    "name": "decompose", "quantity": 1.0,
    "unit_rate": 0.0, "duration_days": 5,
    "equipment_line_id": ej_line_sound.id,
})
setup, ev, strike = probe._decompose_days()
ok = (setup == 0 and ev == 5 and strike == 0)
print("  decomposed: setup=%d event=%d strike=%d" % (setup, ev, strike))
print("T707:", "PASS" if ok else "FAIL")
results["T707"] = ok


# ============================================================
print()
print("=" * 72)
print("T708 - create() with equipment + equipment_line stamps snapshot")
print("=" * 72)
line_t708 = QuoteLine.create({
    "quote_id": q_usd.id, "line_type": "equipment",
    "name": "Sound rig 3 days", "quantity": 1.0,
    "unit_rate": 0.0,  # will be overwritten by engine
    "duration_days": 3,
    "equipment_line_id": ej_line_sound.id,
})
ok = line_t708.snapshot_taken
print("  snapshot_taken:", line_t708.snapshot_taken,
      "pricing_status:", line_t708.pricing_status,
      "unit_rate:", line_t708.unit_rate)
print("T708:", "PASS" if ok else "FAIL")
results["T708"] = ok


# ============================================================
print()
print("=" * 72)
print("T709 - snapshot_taken flips True after engine runs")
print("=" * 72)
ok = line_t708.snapshot_taken is True
print("  snapshot_taken:", line_t708.snapshot_taken)
print("T709:", "PASS" if ok else "FAIL")
results["T709"] = ok


# ============================================================
print()
print("=" * 72)
print("T710 - pricing_status = 'priced'")
print("=" * 72)
ok = line_t708.pricing_status == "priced"
print("  pricing_status:", line_t708.pricing_status)
print("T710:", "PASS" if ok else "FAIL")
results["T710"] = ok


# ============================================================
print()
print("=" * 72)
print("T711 - bracket_multiplier snapshotted")
print("=" * 72)
# Sound USD rule day=3 maps to the 3-7 bracket = 0.80 multiplier.
ok = abs(line_t708.bracket_multiplier - 0.80) < 0.001
print("  bracket_multiplier:", line_t708.bracket_multiplier, "(expected 0.80)")
print("T711:", "PASS" if ok else "FAIL")
results["T711"] = ok


# ============================================================
print()
print("=" * 72)
print("T712 - day_breakdown_json populated with full structure")
print("=" * 72)
breakdown = json.loads(line_t708.day_breakdown_json or "{}")
expected_keys = {
    "setup_days", "event_days", "strike_days",
    "base_rate", "bracket_multiplier",
    "setup_day_multiplier", "event_day_multiplier",
    "strike_day_multiplier", "blended_per_day",
}
ok = set(breakdown.keys()) == expected_keys
print("  breakdown keys:", sorted(breakdown.keys()))
print("T712:", "PASS" if ok else "FAIL")
results["T712"] = ok


# ============================================================
print()
print("=" * 72)
print("T713 - unit_rate = blended per-day rate")
print("=" * 72)
# Sound USD base_rate=50, bracket=0.80, event_day_multiplier (default
# from day.multiplier seed) = 1.0, all 3 days are event days.
# blended = 50 * 0.80 * 1.0 = 40.0
expected_unit = sound_usd_rule.base_rate * 0.80 * (
    env["neon.finance.day.multiplier"].search(
        [("category_id", "=", cat_sound.id)], limit=1
    ).event_day_multiplier or 1.0
)
ok = abs(line_t708.unit_rate - expected_unit) < 0.01
print("  unit_rate:", line_t708.unit_rate, "expected:", expected_unit)
print("T713:", "PASS" if ok else "FAIL")
results["T713"] = ok


# ============================================================
print()
print("=" * 72)
print("T714 - line_subtotal = qty * unit_rate * duration_days")
print("=" * 72)
expected_subtotal = line_t708.quantity * line_t708.unit_rate * line_t708.duration_days
ok = abs(line_t708.line_subtotal - expected_subtotal) < 0.01
print("  line_subtotal:", line_t708.line_subtotal, "expected:", expected_subtotal)
print("T714:", "PASS" if ok else "FAIL")
results["T714"] = ok


# ============================================================
print()
print("=" * 72)
print("T715 - manual line (no equipment_line_id) gets pricing_status='manual'")
print("=" * 72)
manual_line = QuoteLine.create({
    "quote_id": q_usd.id, "line_type": "other",
    "name": "Manual entry", "quantity": 1.0,
    "unit_rate": 200.0, "duration_days": 1,
})
ok = manual_line.pricing_status == "manual" and not manual_line.snapshot_taken
print("  pricing_status:", manual_line.pricing_status,
      "snapshot_taken:", manual_line.snapshot_taken)
print("T715:", "PASS" if ok else "FAIL")
results["T715"] = ok


# ============================================================
print()
print("=" * 72)
print("T716 - duration_days edit post-snapshot does NOT change unit_rate")
print("=" * 72)
pre_rate = line_t708.unit_rate
line_t708.duration_days = 10
post_rate = line_t708.unit_rate
ok = abs(pre_rate - post_rate) < 0.001
print("  pre_rate:", pre_rate, "post_rate:", post_rate, "(snapshot frozen)")
print("T716:", "PASS" if ok else "FAIL")
results["T716"] = ok


# ============================================================
print()
print("=" * 72)
print("T717 - action_recalculate_pricing clears snapshot + re-runs")
print("=" * 72)
# line_t708.duration_days is now 10 (changed above). After Recalculate
# the unit_rate should reflect the 8-14 bracket (multiplier 0.70).
err, _ = _try(lambda: q_usd.with_user(sales_user).action_recalculate_pricing())
expected_new_rate = sound_usd_rule.base_rate * 0.70 * (
    env["neon.finance.day.multiplier"].search(
        [("category_id", "=", cat_sound.id)], limit=1
    ).event_day_multiplier or 1.0
)
ok = (err is None
      and line_t708.snapshot_taken
      and abs(line_t708.bracket_multiplier - 0.70) < 0.001
      and abs(line_t708.unit_rate - expected_new_rate) < 0.01)
print("  err:", type(err).__name__ if err else None,
      "snapshot_taken:", line_t708.snapshot_taken,
      "bracket_multiplier:", line_t708.bracket_multiplier,
      "unit_rate:", line_t708.unit_rate)
print("T717:", "PASS" if ok else "FAIL")
results["T717"] = ok


# ============================================================
print()
print("=" * 72)
print("T718 - action_recalculate_pricing blocked when state != draft")
print("=" * 72)
q_blocked = Quote.create({
    "event_job_id": event_job.id, "currency_id": usd.id,
    "salesperson_id": sales_user.id, "payment_term_id": term.id,
})
QuoteLine.create({
    "quote_id": q_blocked.id, "line_type": "equipment",
    "name": "x", "quantity": 1.0, "unit_rate": 0.0,
    "duration_days": 3, "equipment_line_id": ej_line_sound.id,
})
q_blocked.state = "sent"  # force non-draft
err, _ = _try(lambda: q_blocked.with_user(sales_user).action_recalculate_pricing())
ok = isinstance(err, UserError)
print("  err:", type(err).__name__ if err else None)
print("T718:", "PASS" if ok else "FAIL")
results["T718"] = ok


# ============================================================
print()
print("=" * 72)
print("T719 - action_recalculate_pricing requires at least one line")
print("=" * 72)
q_empty = Quote.create({
    "event_job_id": event_job.id, "currency_id": usd.id,
    "salesperson_id": sales_user.id, "payment_term_id": term.id,
})
err, _ = _try(lambda: q_empty.with_user(sales_user).action_recalculate_pricing())
ok = isinstance(err, UserError)
print("  err:", type(err).__name__ if err else None)
print("T719:", "PASS" if ok else "FAIL")
results["T719"] = ok


# ============================================================
print()
print("=" * 72)
print("T720 - Recalculate reflects underlying rule changes")
print("=" * 72)
# Bump the rule's base_rate. Recalculate the line and verify the new
# rate propagates.
q_t720 = Quote.create({
    "event_job_id": event_job.id, "currency_id": usd.id,
    "salesperson_id": sales_user.id, "payment_term_id": term.id,
})
line_t720 = QuoteLine.create({
    "quote_id": q_t720.id, "line_type": "equipment",
    "name": "rule change test", "quantity": 1.0, "unit_rate": 0.0,
    "duration_days": 3, "equipment_line_id": ej_line_sound.id,
})
pre_rate = line_t720.unit_rate
# Bump rule
sound_usd_rule.base_rate = sound_usd_rule.base_rate * 2.0
q_t720.with_user(sales_user).action_recalculate_pricing()
post_rate = line_t720.unit_rate
ok = abs(post_rate - 2 * pre_rate) < 0.01
print("  pre_rate:", pre_rate, "post_rate:", post_rate)
print("T720:", "PASS" if ok else "FAIL")
results["T720"] = ok


# ============================================================
print()
print("=" * 72)
print("T721 - no-rule path: pricing_status='no_rule', unit_rate unchanged")
print("=" * 72)
line_t721 = QuoteLine.create({
    "quote_id": q_usd.id, "line_type": "equipment",
    "name": "no-rule path", "quantity": 1.0,
    "unit_rate": 0.0, "duration_days": 3,
    "equipment_line_id": ej_line_norule.id,
})
ok = (line_t721.pricing_status == "no_rule"
      and not line_t721.snapshot_taken
      and line_t721.unit_rate == 0.0)
print("  pricing_status:", line_t721.pricing_status,
      "snapshot_taken:", line_t721.snapshot_taken,
      "unit_rate:", line_t721.unit_rate)
print("T721:", "PASS" if ok else "FAIL")
results["T721"] = ok


# ============================================================
print()
print("=" * 72)
print("T722 - open-ended bracket (15+ days)")
print("=" * 72)
line_t722 = QuoteLine.create({
    "quote_id": q_usd.id, "line_type": "equipment",
    "name": "long rental", "quantity": 1.0,
    "unit_rate": 0.0, "duration_days": 20,
    "equipment_line_id": ej_line_sound.id,
})
# bracket 15--1 = 0.60 multiplier on the seeded sound USD rule
ok = abs(line_t722.bracket_multiplier - 0.60) < 0.001
print("  duration_days: 20  bracket_multiplier:", line_t722.bracket_multiplier)
print("T722:", "PASS" if ok else "FAIL")
results["T722"] = ok


# ============================================================
print()
print("=" * 72)
print("T723 - multi-day breakdown hits correct brackets")
print("=" * 72)
cases = [
    (1, 1.00),    # 1-2 bracket
    (3, 0.80),    # 3-7 bracket
    (8, 0.70),    # 8-14 bracket
    (15, 0.60),   # 15--1 bracket
]
all_pass = True
for days, expected_mult in cases:
    l = QuoteLine.create({
        "quote_id": q_usd.id, "line_type": "equipment",
        "name": "case_%d" % days, "quantity": 1.0,
        "unit_rate": 0.0, "duration_days": days,
        "equipment_line_id": ej_line_sound.id,
    })
    actual = l.bracket_multiplier
    case_pass = abs(actual - expected_mult) < 0.001
    print("  days=%d expected=%.2f actual=%.2f %s" % (
        days, expected_mult, actual, "OK" if case_pass else "FAIL"))
    all_pass = all_pass and case_pass
print("T723:", "PASS" if all_pass else "FAIL")
results["T723"] = all_pass


# ============================================================
print()
print("=" * 72)
print("T724 - USD line resolves USD rule")
print("=" * 72)
line_usd_currency = QuoteLine.create({
    "quote_id": q_usd.id, "line_type": "equipment",
    "name": "USD currency check", "quantity": 1.0,
    "unit_rate": 0.0, "duration_days": 3,
    "equipment_line_id": ej_line_sound.id,
})
breakdown_usd = json.loads(line_usd_currency.day_breakdown_json or "{}")
# Resolve against the live rule's base_rate (T720 doubled it earlier
# in the run, so we read the current value rather than the seed
# value).
ok = abs(breakdown_usd.get("base_rate", 0) - sound_usd_rule.base_rate) < 0.01
print("  resolved base_rate:", breakdown_usd.get("base_rate"),
      "expected (live rule):", sound_usd_rule.base_rate, "(USD)")
print("T724:", "PASS" if ok else "FAIL")
results["T724"] = ok


# ============================================================
print()
print("=" * 72)
print("T725 - ZWG line resolves ZWG rule")
print("=" * 72)
q_zwg = Quote.create({
    "event_job_id": event_job.id, "currency_id": zwg.id,
    "salesperson_id": sales_user.id, "payment_term_id": term.id,
})
line_zwg = QuoteLine.create({
    "quote_id": q_zwg.id, "line_type": "equipment",
    "name": "ZWG currency check", "quantity": 1.0,
    "unit_rate": 0.0, "duration_days": 3,
    "equipment_line_id": ej_line_sound.id,
})
breakdown_zwg = json.loads(line_zwg.day_breakdown_json or "{}")
# Sound ZWG seeded base_rate = 500.0
ok = abs(breakdown_zwg.get("base_rate", 0) - 500.0) < 0.01
print("  resolved base_rate:", breakdown_zwg.get("base_rate"), "expected: 500.0 (ZWG)")
print("T725:", "PASS" if ok else "FAIL")
results["T725"] = ok


# ============================================================
print()
print("=" * 72)
print("T726 - cross-currency: same category, different currency = different rate")
print("=" * 72)
# Same line (same category, same days, same equipment_line) on USD
# quote vs ZWG quote should yield different unit_rates because base
# rates differ (50 vs 500).
ok = line_usd_currency.unit_rate != line_zwg.unit_rate
print("  USD unit_rate:", line_usd_currency.unit_rate,
      "ZWG unit_rate:", line_zwg.unit_rate)
print("T726:", "PASS" if ok else "FAIL")
results["T726"] = ok


# ============================================================
print()
print("=" * 72)
print("T727 - bracket boundary inclusivity (day_from + day_to both inclusive)")
print("=" * 72)
# Brackets: 1-2, 3-7, 8-14, 15--1
# Test the exact-boundary days
boundary_cases = [
    (2, 1.00),  # day 2 -> 1-2 bracket (day_to=2 inclusive)
    (3, 0.80),  # day 3 -> 3-7 bracket (day_from=3 inclusive)
    (7, 0.80),  # day 7 -> 3-7 bracket (day_to=7 inclusive)
    (8, 0.70),  # day 8 -> 8-14 bracket (day_from=8 inclusive)
    (14, 0.70), # day 14 -> 8-14 bracket (day_to=14 inclusive)
    (15, 0.60), # day 15 -> 15--1 bracket (day_from=15 inclusive)
]
all_pass = True
for days, expected_mult in boundary_cases:
    bracket = QuoteLine._find_bracket(sound_usd_rule, days)
    actual = bracket.multiplier if bracket else 0
    case_pass = abs(actual - expected_mult) < 0.001
    all_pass = all_pass and case_pass
    print("  days=%d expected=%.2f actual=%.2f %s" % (
        days, expected_mult, actual, "OK" if case_pass else "FAIL"))
print("T727:", "PASS" if all_pass else "FAIL")
results["T727"] = all_pass


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in range(700, 728)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
