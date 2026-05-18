"""P6.M1 smoke — pricing rule foundation (16 tests).

T500 pricing.rule create with all required fields -> success
T501 pricing.rule create without category_id -> error
T502 pricing.bracket day_from > day_to (and day_to != -1) -> ValidationError
T503 pricing.bracket overlapping range within same rule -> ValidationError
T504 pricing.bracket two open-ended tails on same rule -> ValidationError
T505 day.multiplier auto-created on category create
T506 day.multiplier negative value -> ValidationError
T507 conversion.rate create with future effective_date -> success
T508 conversion.rate uniqueness on effective_date -> IntegrityError
T509 conversion.rate get_active_rate returns latest record
T510 conversion.rate get_active_rate returns None when no record
T511 category cost_strategy default = 'owned_zero'
T512 category cost_strategy -> 'consumable_actual' + consumable cost persists
T513 sales user can read pricing.rule
T514 sales user cannot write pricing.rule -> AccessError
T515 bookkeeper user can write pricing.rule + conversion.rate
T516 bookkeeper group implies account.group_account_invoice
T517 approver group implies account.group_account_invoice
T518 sales group does NOT imply account.group_account_invoice
T519 account.menu_finance_configuration grants Bookkeeper + Approver reach
"""
from datetime import date, timedelta

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

Rule = env["neon.finance.pricing.rule"]
Bracket = env["neon.finance.pricing.bracket"]
Multiplier = env["neon.finance.day.multiplier"]
ConvRate = env["neon.finance.conversion.rate"]
Category = env["neon.equipment.category"]

usd = env.ref("base.USD")
zwg = env.ref("neon_finance.currency_zwg")
cat_sound = env.ref("neon_jobs.equipment_category_sound")
cat_visual = env.ref("neon_jobs.equipment_category_visual")
cat_lighting = env.ref("neon_jobs.equipment_category_lighting")

# Test users + group bindings. The smoke binds finance role groups
# on p2m75_sales (sales tier) and p2m75_mgr (bookkeeper tier) so
# T513-T515 can exercise the role-based ACL. env.cr.rollback() at
# end of smoke cleans this up.
sales_user = env["res.users"].search(
    [("login", "=", "p2m75_sales")], limit=1)
mgr_user = env["res.users"].search(
    [("login", "=", "p2m75_mgr")], limit=1)
assert sales_user and mgr_user, (
    "Need p2m75_sales + p2m75_mgr seed users (P2.M7 fixtures).")

g_sales = env.ref("neon_finance.group_neon_finance_sales")
g_bookkeeper = env.ref("neon_finance.group_neon_finance_bookkeeper")
sales_user.sudo().write({"groups_id": [(4, g_sales.id)]})
mgr_user.sudo().write({"groups_id": [(4, g_bookkeeper.id)]})


# ============================================================
print()
print("=" * 72)
print("T500 - pricing.rule create with all required fields")
print("=" * 72)
err, rule_t500 = _try(lambda: Rule.create({
    "category_id": cat_lighting.id,
    "currency_id": usd.id,
    "base_rate": 75.00,
    "effective_date": date.today() + timedelta(days=1),
    "notes": "smoke T500",
}))
ok = err is None and bool(rule_t500) and rule_t500.name.startswith("PRC-")
print("  err:", type(err).__name__ if err else None,
      " name:", rule_t500.name if rule_t500 else None)
print("T500:", "PASS" if ok else "FAIL")
results["T500"] = ok


# ============================================================
print()
print("=" * 72)
print("T501 - pricing.rule create without category_id -> error")
print("=" * 72)
err, _v = _try(lambda: Rule.create({
    "currency_id": usd.id,
    "base_rate": 50.00,
}))
# Odoo can raise any of these depending on validation order.
ok = isinstance(err, (UserError, ValidationError, IntegrityError, KeyError))
print("  raised:", type(err).__name__ if err else None,
      " msg:", (str(err) or "")[:120])
print("T501:", "PASS" if ok else "FAIL")
results["T501"] = ok


# ============================================================
print()
print("=" * 72)
print("T502 - pricing.bracket day_from > day_to -> ValidationError")
print("=" * 72)
err, _v = _try(lambda: Bracket.create({
    "rule_id": rule_t500.id,
    "day_from": 5,
    "day_to": 3,
    "multiplier": 1.0,
}))
ok = isinstance(err, (ValidationError, IntegrityError))
print("  raised:", type(err).__name__ if err else None,
      " msg:", (str(err) or "")[:120])
print("T502:", "PASS" if ok else "FAIL")
results["T502"] = ok


# ============================================================
print()
print("=" * 72)
print("T503 - pricing.bracket overlapping range -> ValidationError")
print("=" * 72)
# Seed a rule with one bracket, then try to add an overlap.
rule_t503 = Rule.create({
    "category_id": cat_lighting.id,
    "currency_id": zwg.id,
    "base_rate": 600.00,
    "effective_date": date.today() + timedelta(days=2),
})
Bracket.create({
    "rule_id": rule_t503.id,
    "day_from": 1, "day_to": 5, "multiplier": 1.0,
})
err, _v = _try(lambda: Bracket.create({
    "rule_id": rule_t503.id,
    "day_from": 3, "day_to": 7, "multiplier": 0.8,
}))
ok = isinstance(err, ValidationError)
print("  raised:", type(err).__name__ if err else None,
      " msg:", (str(err) or "")[:120])
print("T503:", "PASS" if ok else "FAIL")
results["T503"] = ok


# ============================================================
print()
print("=" * 72)
print("T504 - pricing.bracket two open-ended tails -> ValidationError")
print("=" * 72)
rule_t504 = Rule.create({
    "category_id": cat_sound.id,
    "currency_id": usd.id,
    "base_rate": 55.00,
    "effective_date": date.today() + timedelta(days=3),
})
Bracket.create({
    "rule_id": rule_t504.id,
    "day_from": 10, "day_to": -1, "multiplier": 0.5,
})
err, _v = _try(lambda: Bracket.create({
    "rule_id": rule_t504.id,
    "day_from": 20, "day_to": -1, "multiplier": 0.4,
}))
ok = isinstance(err, ValidationError)
print("  raised:", type(err).__name__ if err else None,
      " msg:", (str(err) or "")[:120])
print("T504:", "PASS" if ok else "FAIL")
results["T504"] = ok


# ============================================================
print()
print("=" * 72)
print("T505 - day.multiplier auto-created on category create")
print("=" * 72)
new_cat = Category.create({
    "name": "P6M1 Smoke Category",
    "code": "p6m1_smoke_test_cat",
    "default_tracking": "quantity",
})
dm = Multiplier.search([("category_id", "=", new_cat.id)], limit=1)
ok = bool(dm) and dm.event_day_multiplier == 1.00
print("  multiplier exists:", bool(dm),
      " event:", dm.event_day_multiplier if dm else None,
      " setup:", dm.setup_day_multiplier if dm else None,
      " strike:", dm.strike_day_multiplier if dm else None)
print("T505:", "PASS" if ok else "FAIL")
results["T505"] = ok


# ============================================================
print()
print("=" * 72)
print("T506 - day.multiplier negative value -> ValidationError")
print("=" * 72)
# Use an existing seeded multiplier; flip one field negative.
dm_t506 = Multiplier.search(
    [("category_id", "=", cat_sound.id)], limit=1)
err, _v = _try(lambda: dm_t506.write({
    "event_day_multiplier": -0.5}))
ok = isinstance(err, (ValidationError, IntegrityError))
print("  raised:", type(err).__name__ if err else None,
      " msg:", (str(err) or "")[:120])
print("T506:", "PASS" if ok else "FAIL")
results["T506"] = ok


# ============================================================
print()
print("=" * 72)
print("T507 - conversion.rate create with future effective_date")
print("=" * 72)
future = date.today() + timedelta(days=30)
err, cr_t507 = _try(lambda: ConvRate.create({
    "effective_date": future,
    "usd_per_zig": 0.00005,
    "zig_per_usd": 20000.0,
    "source_note": "smoke T507",
}))
ok = err is None and bool(cr_t507) and cr_t507.name.startswith("FX-")
print("  err:", type(err).__name__ if err else None,
      " name:", cr_t507.name if cr_t507 else None)
print("T507:", "PASS" if ok else "FAIL")
results["T507"] = ok


# ============================================================
print()
print("=" * 72)
print("T508 - conversion.rate duplicate effective_date -> IntegrityError")
print("=" * 72)
err, _v = _try(lambda: ConvRate.create({
    "effective_date": future,  # same date as T507
    "usd_per_zig": 0.00006,
    "zig_per_usd": 16666.0,
}))
ok = isinstance(err, IntegrityError)
print("  raised:", type(err).__name__ if err else None,
      " msg:", (str(err) or "")[:120])
print("T508:", "PASS" if ok else "FAIL")
results["T508"] = ok


# ============================================================
print()
print("=" * 72)
print("T509 - get_active_rate returns latest record")
print("=" * 72)
# Seed an older rate so we can verify the latest one wins.
older_date = date.today() - timedelta(days=10)
ConvRate.create({
    "effective_date": older_date,
    "usd_per_zig": 0.0001,
    "zig_per_usd": 10000.0,
    "source_note": "smoke T509 older",
})
# Should return the rate that was seeded by data XML (today) since
# that's the latest with effective_date <= today.
rate_zwg_to_usd = ConvRate.get_active_rate(zwg, usd)
rate_usd_to_zwg = ConvRate.get_active_rate(usd, zwg)
# Same-currency identity
rate_same = ConvRate.get_active_rate(usd, usd)
ok = (
    rate_zwg_to_usd == 0.000040
    and rate_usd_to_zwg == 25000.000000
    and rate_same == 1.0
)
print("  zwg->usd:", rate_zwg_to_usd, "(want 0.000040)")
print("  usd->zwg:", rate_usd_to_zwg, "(want 25000.0)")
print("  usd->usd:", rate_same, "(want 1.0)")
print("T509:", "PASS" if ok else "FAIL")
results["T509"] = ok


# ============================================================
print()
print("=" * 72)
print("T510 - get_active_rate returns None when no record")
print("=" * 72)
# Query for a date BEFORE the older_date we just inserted.
very_old = older_date - timedelta(days=365)
rate_none = ConvRate.get_active_rate(zwg, usd, on_date=very_old)
ok = rate_none is None
print("  rate for", very_old.isoformat(), ":", rate_none)
print("T510:", "PASS" if ok else "FAIL")
results["T510"] = ok


# ============================================================
print()
print("=" * 72)
print("T511 - category cost_strategy default = 'owned_zero'")
print("=" * 72)
# The 9 seeded categories should all be owned_zero post-migration.
sample_categories = Category.search(
    [("code", "in", ("sound", "visual", "lighting"))])
strategies = sample_categories.mapped("cost_strategy")
ok = all(s == "owned_zero" for s in strategies) and len(strategies) == 3
print("  sample categories:", sample_categories.mapped("code"))
print("  cost_strategies :", strategies)
print("T511:", "PASS" if ok else "FAIL")
results["T511"] = ok


# ============================================================
print()
print("=" * 72)
print("T512 - cost_strategy change to consumable_actual persists")
print("=" * 72)
cat_for_consumable = Category.create({
    "name": "P6M1 Consumable",
    "code": "p6m1_consumable_test",
    "default_tracking": "quantity",
})
cat_for_consumable.write({
    "cost_strategy": "consumable_actual",
    "consumable_cost_per_unit": 12.50,
    "currency_id": usd.id,
})
cat_for_consumable.invalidate_recordset()
ok = (
    cat_for_consumable.cost_strategy == "consumable_actual"
    and abs(cat_for_consumable.consumable_cost_per_unit - 12.50) < 1e-6
)
print("  strategy:", cat_for_consumable.cost_strategy,
      " cost:", cat_for_consumable.consumable_cost_per_unit)
print("T512:", "PASS" if ok else "FAIL")
results["T512"] = ok


# ============================================================
print()
print("=" * 72)
print("T513 - sales user can read pricing.rule")
print("=" * 72)
# Read access expected; bound g_sales in setup.
try:
    rules_seen = Rule.with_user(sales_user).search([], limit=3)
    err = None
except Exception as e:  # noqa: BLE001
    rules_seen = None
    err = e
ok = err is None and rules_seen and len(rules_seen) >= 1
print("  rules visible:", len(rules_seen) if rules_seen else None,
      " err:", type(err).__name__ if err else None)
print("T513:", "PASS" if ok else "FAIL")
results["T513"] = ok


# ============================================================
print()
print("=" * 72)
print("T514 - sales user cannot write pricing.rule -> AccessError")
print("=" * 72)
err, _v = _try(lambda: Rule.with_user(sales_user).create({
    "category_id": cat_sound.id,
    "currency_id": usd.id,
    "base_rate": 999.99,
    "effective_date": date.today() + timedelta(days=99),
    "notes": "smoke T514 (should fail)",
}))
ok = isinstance(err, AccessError)
print("  raised:", type(err).__name__ if err else None,
      " msg:", (str(err) or "")[:120])
print("T514:", "PASS" if ok else "FAIL")
results["T514"] = ok


# ============================================================
print()
print("=" * 72)
print("T515 - bookkeeper user can write pricing.rule + conversion.rate")
print("=" * 72)
err1, rule_t515 = _try(lambda: Rule.with_user(mgr_user).create({
    "category_id": cat_visual.id,
    "currency_id": zwg.id,
    "base_rate": 1234.56,
    "effective_date": date.today() + timedelta(days=4),
    "notes": "smoke T515",
}))
err2, cr_t515 = _try(lambda: ConvRate.with_user(mgr_user).create({
    "effective_date": date.today() + timedelta(days=60),
    "usd_per_zig": 0.00007,
    "zig_per_usd": 14285.7,
    "source_note": "smoke T515",
}))
ok = (
    err1 is None and bool(rule_t515)
    and err2 is None and bool(cr_t515)
)
print("  rule.create err:", type(err1).__name__ if err1 else None,
      " name:", rule_t515.name if rule_t515 else None)
print("  conv.create err:", type(err2).__name__ if err2 else None,
      " name:", cr_t515.name if cr_t515 else None)
print("T515:", "PASS" if ok else "FAIL")
results["T515"] = ok


# ============================================================
print()
print("=" * 72)
print("T516 - Bookkeeper group implies account.group_account_invoice")
print("=" * 72)
# Implied so Kudzi can operate native Odoo Invoicing AND so the
# Accounting > Configuration parent menu becomes visible.
billing_admin = env.ref("account.group_account_invoice")
implied = g_bookkeeper.implied_ids
ok = billing_admin in implied
print("  bookkeeper implied groups:",
      [(g.id, g.name) for g in implied])
print("  billing_admin in implied:", ok)
print("T516:", "PASS" if ok else "FAIL")
results["T516"] = ok


# ============================================================
print()
print("=" * 72)
print("T517 - Approver group implies account.group_account_invoice")
print("=" * 72)
g_approver = env.ref("neon_finance.group_neon_finance_approver")
implied = g_approver.implied_ids
ok = billing_admin in implied
print("  approver implied groups:",
      [(g.id, g.name) for g in implied])
print("  billing_admin in implied:", ok)
print("T517:", "PASS" if ok else "FAIL")
results["T517"] = ok


# ============================================================
print()
print("=" * 72)
print("T518 - Sales group does NOT imply account.group_account_invoice")
print("=" * 72)
# Negative test: sales reps create quotes (P6.M2+) but don't manage
# invoices. Invoice visibility for sales arrives in P6.M7 via record
# rules on salesperson_id, not via a Billing Administrator grant.
implied = g_sales.implied_ids
ok = billing_admin not in implied
print("  sales implied groups:",
      [(g.id, g.name) for g in implied])
print("  billing_admin NOT in implied:", ok)
print("T518:", "PASS" if ok else "FAIL")
results["T518"] = ok


# ============================================================
print()
print("=" * 72)
print("T519 - Configuration menu grants Bookkeeper + Approver reach")
print("=" * 72)
# account.menu_finance_configuration is the parent of our Finance
# submenu. It normally gates on account.group_account_manager only,
# which Bookkeeper + Approver intentionally do NOT carry (scope
# creep into Odoo accounting admin). P6.M1.2 extends the menu's
# groups_id with our two finance roles directly so the path is
# navigable without granting Billing Administrator authority.
menu = env.ref("account.menu_finance_configuration")
ok_bookkeeper = g_bookkeeper in menu.groups_id
ok_approver = g_approver in menu.groups_id
# Defensive: confirm sales is NOT in the menu's groups_id.
ok_sales_absent = g_sales not in menu.groups_id
ok = ok_bookkeeper and ok_approver and ok_sales_absent
print("  menu.groups_id:", [g.name for g in menu.groups_id])
print("  bookkeeper present:", ok_bookkeeper,
      " approver present:", ok_approver,
      " sales absent:", ok_sales_absent)
print("T519:", "PASS" if ok else "FAIL")
results["T519"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in range(500, 520)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
