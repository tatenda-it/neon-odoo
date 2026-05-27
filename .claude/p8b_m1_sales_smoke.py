"""P8B.M1 smoke -- Sales variant dashboard.

T8B10-T8B27.

T8B10  _compute_kpi('sales') returns exactly the 6 sales tile keys
T8B11  each sales tile dict is well-shaped (value_display + empty)
T8B12  _kpi_hot_deals shape
T8B13  _kpi_aging_quotes shape
T8B14  _kpi_won_mtd shape
T8B15  _kpi_win_rate_tile shape
T8B16  _compute_hot_deals_block returns {empty, rows}
T8B17  _compute_aging_quotes_block returns {empty, rows}
T8B18  get_dashboard_data(sales) carries hot_deals_block + aging_quotes_block
T8B19  get_dashboard_data(sales) does NOT carry bookkeeper/lead_tech blocks
T8B20  sales layout seeded with 6 KPIs + 6 blocks (12 widgets)
T8B21  filter 'hot' hides aging/won widgets
T8B22  filter 'aging' hides hot/won widgets
T8B23  filter 'won' hides hot/aging widgets
T8B24  rule-based subset for 'sales' = pipeline/slow-lead/overdue (3)
T8B25  groq _system_prompt('sales') frames the sales audience
T8B26  orchestrator _build_context(sales dashboard) has dashboard_type='sales'
T8B27  sales-rep user can call get_dashboard_data (ACL) + no new groups
"""
results = {}
print("=" * 72)
print("P8B.M1 -- Sales variant")
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


u_sales = _get_or_make_user("p8b_sales", "neon_core.group_neon_sales_rep")


def _tile_ok(t):
    return isinstance(t, dict) and "value_display" in t and "empty" in t


# T8B10 -- dispatch returns the 6 sales keys.
kpi = Dashboard._compute_kpi("sales")
expected = {"kpi_pipeline", "kpi_leads", "kpi_hot_deals",
            "kpi_aging_quotes", "kpi_won_mtd", "kpi_win_rate"}
_check("T8B10", set(kpi.keys()) == expected, f"keys={sorted(kpi.keys())}")

# T8B11 -- every tile well-shaped.
_check("T8B11", all(_tile_ok(v) for v in kpi.values()))

# T8B12-T8B15 -- individual helpers.
_check("T8B12", _tile_ok(Dashboard._kpi_hot_deals()))
_check("T8B13", _tile_ok(Dashboard._kpi_aging_quotes()))
_check("T8B14", _tile_ok(Dashboard._kpi_won_mtd()))
_check("T8B15", _tile_ok(Dashboard._kpi_win_rate_tile()))

# T8B16-T8B17 -- blocks.
hd = Dashboard._compute_hot_deals_block()
_check("T8B16", isinstance(hd, dict) and "empty" in hd and "rows" in hd)
aq = Dashboard._compute_aging_quotes_block()
_check("T8B17", isinstance(aq, dict) and "empty" in aq and "rows" in aq)

# T8B18-T8B19 -- get_dashboard_data payload composition.
data = Dashboard.with_user(u_sales).get_dashboard_data(dashboard_type="sales")
_check("T8B18",
       data.get("dashboard_type") == "sales"
       and "hot_deals_block" in data and "aging_quotes_block" in data,
       f"type={data.get('dashboard_type')}")
_check("T8B19",
       "budget_alerts_block" not in data and "crew_gaps_block" not in data
       and "cert_expiry_block" not in data)

# T8B20 -- layout seed.
seed = Default.search([("dashboard_type", "=", "sales")], limit=1)
keys = set(seed.layout_line_ids.mapped("widget_key"))
expected_layout = {
    "kpi_pipeline", "kpi_leads", "kpi_hot_deals", "kpi_aging_quotes",
    "kpi_won_mtd", "kpi_win_rate", "block_sales", "block_hot_deals",
    "block_aging_quotes", "block_alerts", "block_tasks",
    "block_ai_insights"}
_check("T8B20", keys == expected_layout, f"n={len(keys)}")

# T8B21-T8B23 -- filter scoping.
hot_vis = set(Dashboard._widgets_for_filter("sales", "hot"))
_check("T8B21", not ({"kpi_aging_quotes", "kpi_won_mtd", "kpi_win_rate",
                      "block_aging_quotes"} & hot_vis))
aging_vis = set(Dashboard._widgets_for_filter("sales", "aging"))
_check("T8B22", not ({"kpi_hot_deals", "kpi_won_mtd", "kpi_win_rate",
                      "block_hot_deals"} & aging_vis))
won_vis = set(Dashboard._widgets_for_filter("sales", "won"))
_check("T8B23", not ({"kpi_hot_deals", "kpi_aging_quotes",
                      "block_hot_deals", "block_aging_quotes"} & won_vis))

# T8B24 -- rule-based subset.
from odoo.addons.neon_dashboard.models.ai.rule_based_adapter import (  # noqa: E402
    RuleBasedAdapter)
rb = RuleBasedAdapter(env=env)
rules = rb._rules_for_type("sales")
names = {r.__name__ for r in rules}
_check("T8B24",
       len(rules) == 3
       and names == {"_rule_pipeline_behind_target",
                     "_rule_slow_lead_followup",
                     "_rule_overdue_invoices"},
       f"{sorted(names)}")

# T8B25 -- groq system prompt framing.
from odoo.addons.neon_dashboard.models.ai.groq_adapter import (  # noqa: E402
    GroqAdapter)
provider = env["neon.dashboard.ai.provider"].sudo().search(
    [("provider_key", "=", "groq")], limit=1)
prompt = GroqAdapter(provider)._system_prompt(
    {"dashboard_type": "sales", "today_date": "2026-05-27"})
_check("T8B25", "sales" in prompt.lower() and "{role_framing}" not in prompt)

# T8B26 -- orchestrator context type.
from odoo.addons.neon_dashboard.models.ai.insight_orchestrator import (  # noqa: E402
    InsightOrchestrator)
sales_dash = Dashboard.sudo().get_or_create_for_user(
    user_id=u_sales.id, dashboard_type="sales")
ctx = InsightOrchestrator(env)._build_context(sales_dash)
_check("T8B26", ctx.get("dashboard_type") == "sales")

# T8B27 -- ACL + no new groups.
err = None
try:
    Dashboard.with_user(u_sales).get_dashboard_data()
except Exception as e:  # noqa: BLE001
    err = e
owned = env["ir.model.data"].search([
    ("module", "=", "neon_dashboard"), ("model", "=", "res.groups")])
_check("T8B27", err is None and len(owned) == 0, f"groups_owned={len(owned)}")

sp.close(rollback=True)
print("=" * 72)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{len(results)} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
