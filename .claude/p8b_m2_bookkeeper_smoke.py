"""P8B.M2 smoke -- Bookkeeper variant dashboard.

T8B30-T8B47.

T8B30  _compute_kpi('bookkeeper') returns exactly the 6 tile keys
T8B31  each bookkeeper tile dict is well-shaped
T8B32  _kpi_overdue_60 shape
T8B33  _kpi_pending_invoices shape
T8B34  _kpi_recent_payments shape (Cash Flow Dashboard reuse)
T8B35  _kpi_recent_costs shape (Cash Flow Dashboard reuse)
T8B36  _finance_dashboard_tile returns a dict (sudo reuse works)
T8B37  _compute_budget_alerts_block has ok/warn/breach/severe ints
T8B38  _compute_invoice_queue_block returns {empty, rows}
T8B39  _compute_zig_costs_block has rate + costs keys
T8B40  get_dashboard_data(bookkeeper) carries budget/invoice/zig blocks
T8B41  get_dashboard_data(bookkeeper) excludes sales/lead_tech blocks
T8B42  bookkeeper layout seeded with 6 KPIs + 7 blocks
T8B43  filter 'overdue' hides recent payments/costs widgets
T8B44  filter 'recently_paid' hides overdue/pending widgets
T8B45  rule-based subset for 'bookkeeper' = overdue/cash-low (2)
T8B46  groq _system_prompt('bookkeeper') frames the finance audience
T8B47  bookkeeper user can call get_dashboard_data (ACL)
"""
results = {}
print("=" * 72)
print("P8B.M2 -- Bookkeeper variant")
print("=" * 72)

Dashboard = env["neon.dashboard"]
Users = env["res.users"]
Default = env["neon.dashboard.default.layout"]
sp = env.cr.savepoint()


def _check(tnum, cond, detail=""):
    results[tnum] = bool(cond)
    print(f"{tnum}: {'PASS' if cond else 'FAIL'} {detail}")


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


u_book = _get_or_make_user("p8b_book", "neon_core.group_neon_bookkeeper")


def _tile_ok(t):
    return isinstance(t, dict) and "value_display" in t and "empty" in t


# T8B30 -- dispatch keys.
kpi = Dashboard._compute_kpi("bookkeeper")
expected = {"kpi_cash", "kpi_ar_overdue", "kpi_overdue_60",
            "kpi_pending_invoices", "kpi_recent_payments",
            "kpi_recent_costs"}
_check("T8B30", set(kpi.keys()) == expected, f"keys={sorted(kpi.keys())}")

# T8B31 -- shapes.
_check("T8B31", all(_tile_ok(v) for v in kpi.values()))

# T8B32-T8B35 -- helpers.
_check("T8B32", _tile_ok(Dashboard._kpi_overdue_60()))
_check("T8B33", _tile_ok(Dashboard._kpi_pending_invoices()))
_check("T8B34", _tile_ok(Dashboard._kpi_recent_payments()))
_check("T8B35", _tile_ok(Dashboard._kpi_recent_costs()))

# T8B36 -- reuse helper.
tile = Dashboard._finance_dashboard_tile("_tile_recent_payments")
_check("T8B36", isinstance(tile, dict))

# T8B37-T8B39 -- blocks.
ba = Dashboard._compute_budget_alerts_block()
_check("T8B37",
       all(isinstance(ba.get(k), int) for k in
           ("ok", "warn", "breach", "severe")),
       f"{ {k: ba.get(k) for k in ('ok','warn','breach','severe')} }")
iq = Dashboard._compute_invoice_queue_block()
_check("T8B38", isinstance(iq, dict) and "empty" in iq and "rows" in iq)
zc = Dashboard._compute_zig_costs_block()
_check("T8B39", "rate" in zc and "costs" in zc)

# T8B40-T8B41 -- payload composition.
data = Dashboard.with_user(u_book).get_dashboard_data(
    dashboard_type="bookkeeper")
_check("T8B40",
       data.get("dashboard_type") == "bookkeeper"
       and "budget_alerts_block" in data
       and "invoice_queue_block" in data
       and "zig_costs_block" in data)
_check("T8B41",
       "hot_deals_block" not in data and "crew_gaps_block" not in data)

# T8B42 -- layout.
seed = Default.search([("dashboard_type", "=", "bookkeeper")], limit=1)
keys = set(seed.layout_line_ids.mapped("widget_key"))
expected_layout = {
    "kpi_cash", "kpi_ar_overdue", "kpi_overdue_60", "kpi_pending_invoices",
    "kpi_recent_payments", "kpi_recent_costs", "block_finance",
    "block_budget_alerts", "block_invoice_queue", "block_zig_costs",
    "block_alerts", "block_tasks", "block_ai_insights"}
_check("T8B42", keys == expected_layout, f"n={len(keys)}")

# T8B43-T8B44 -- filter scoping.
ov = set(Dashboard._widgets_for_filter("bookkeeper", "overdue"))
_check("T8B43", not ({"kpi_recent_payments", "kpi_recent_costs",
                      "kpi_pending_invoices", "block_invoice_queue",
                      "block_zig_costs"} & ov))
rp = set(Dashboard._widgets_for_filter("bookkeeper", "recently_paid"))
_check("T8B44", not ({"kpi_overdue_60", "kpi_pending_invoices",
                      "kpi_ar_overdue", "block_invoice_queue"} & rp))

# T8B45 -- rule subset.
from odoo.addons.neon_dashboard.models.ai.rule_based_adapter import (  # noqa: E402
    RuleBasedAdapter)
rules = RuleBasedAdapter(env=env)._rules_for_type("bookkeeper")
names = {r.__name__ for r in rules}
_check("T8B45",
       names == {"_rule_overdue_invoices", "_rule_cash_low"},
       f"{sorted(names)}")

# T8B46 -- groq prompt.
from odoo.addons.neon_dashboard.models.ai.groq_adapter import (  # noqa: E402
    GroqAdapter)
provider = env["neon.dashboard.ai.provider"].sudo().search(
    [("provider_key", "=", "groq")], limit=1)
prompt = GroqAdapter(provider)._system_prompt(
    {"dashboard_type": "bookkeeper", "today_date": "2026-05-27"})
_check("T8B46",
       ("bookkeeper" in prompt.lower() or "finance" in prompt.lower())
       and "{role_framing}" not in prompt)

# T8B47 -- ACL.
err = None
try:
    Dashboard.with_user(u_book).get_dashboard_data()
except Exception as e:  # noqa: BLE001
    err = e
_check("T8B47", err is None, f"err={err}")

sp.close(rollback=True)
print("=" * 72)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{len(results)} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
