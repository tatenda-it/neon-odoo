"""P8B.M3 smoke -- Lead Tech variant dashboard + MD-peek selector.

T8B50-T8B68.

T8B50  _compute_kpi('lead_tech') returns exactly the 4 tile keys
T8B51  each lead_tech tile dict is well-shaped
T8B52  _kpi_crew_gaps shape
T8B53  _kpi_certs_30 shape (neon.training.certification sudo read)
T8B54  _compute_crew_gaps_block returns {empty, rows}
T8B55  _compute_cert_expiry_block returns {empty, rows}
T8B56  get_dashboard_data(lead_tech) carries crew_gaps + cert_expiry blocks
T8B57  get_dashboard_data(lead_tech) excludes sales/bookkeeper blocks
T8B58  lead_tech layout seeded with 4 KPIs + 7 blocks
T8B59  filter 'today' hides jobs_week + certs widgets
T8B60  filter 'next7' hides certs widgets
T8B61  filter 'next30' hides nothing
T8B62  rule-based subset for 'lead_tech' = crew_gaps/cert_expiry (2)
T8B63  crew-gap rule fix: commercial.event.job has crew_total_count +
       crew_confirmed_count (not crew_required/crew_assigned)
T8B64  groq _system_prompt('lead_tech') frames the ops/crew audience
T8B65  orchestrator _build_context(lead_tech dash) has dashboard_type
T8B66  selector/peek: superuser _resolve_dashboard_type('lead_tech') honoured
T8B67  selector/peek: non-superuser requested type IGNORED (ACL wall)
T8B68  lead_tech user can call get_dashboard_data (ACL)
"""
results = {}
print("=" * 72)
print("P8B.M3 -- Lead Tech variant + MD-peek selector")
print("=" * 72)

Dashboard = env["neon.dashboard"]
Users = env["res.users"]
Default = env["neon.dashboard.default.layout"]
EventJob = env["commercial.event.job"]
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


u_lead = _get_or_make_user("p8b_lead", "neon_core.group_neon_lead_tech")
u_super = _get_or_make_user(
    "p8b_super", "neon_core.group_neon_superuser")


def _tile_ok(t):
    return isinstance(t, dict) and "value_display" in t and "empty" in t


# T8B50-T8B51 -- dispatch + shapes.
kpi = Dashboard._compute_kpi("lead_tech")
expected = {"kpi_jobs_today", "kpi_jobs_week", "kpi_crew_gaps",
            "kpi_certs_30"}
_check("T8B50", set(kpi.keys()) == expected, f"keys={sorted(kpi.keys())}")
_check("T8B51", all(_tile_ok(v) for v in kpi.values()))

# T8B52-T8B53 -- helpers.
_check("T8B52", _tile_ok(Dashboard._kpi_crew_gaps()))
_check("T8B53", _tile_ok(Dashboard._kpi_certs_30()))

# T8B54-T8B55 -- blocks.
cg = Dashboard._compute_crew_gaps_block()
_check("T8B54", isinstance(cg, dict) and "empty" in cg and "rows" in cg)
ce = Dashboard._compute_cert_expiry_block()
_check("T8B55", isinstance(ce, dict) and "empty" in ce and "rows" in ce)

# T8B56-T8B57 -- payload composition.
data = Dashboard.with_user(u_lead).get_dashboard_data(
    dashboard_type="lead_tech")
_check("T8B56",
       data.get("dashboard_type") == "lead_tech"
       and "crew_gaps_block" in data and "cert_expiry_block" in data)
_check("T8B57",
       "hot_deals_block" not in data and "budget_alerts_block" not in data)

# T8B58 -- layout.
seed = Default.search([("dashboard_type", "=", "lead_tech")], limit=1)
keys = set(seed.layout_line_ids.mapped("widget_key"))
expected_layout = {
    "kpi_jobs_today", "kpi_jobs_week", "kpi_crew_gaps", "kpi_certs_30",
    "block_jobs", "block_crew_gaps", "block_cert_expiry",
    "block_crew_equipment", "block_alerts", "block_tasks",
    "block_ai_insights"}
_check("T8B58", keys == expected_layout, f"n={len(keys)}")

# T8B59-T8B61 -- filter scoping.
td = set(Dashboard._widgets_for_filter("lead_tech", "today"))
_check("T8B59", not ({"kpi_jobs_week", "kpi_certs_30",
                      "block_cert_expiry"} & td))
n7 = set(Dashboard._widgets_for_filter("lead_tech", "next7"))
_check("T8B60", not ({"kpi_certs_30", "block_cert_expiry"} & n7))
n30 = set(Dashboard._widgets_for_filter("lead_tech", "next30"))
base = set(Dashboard._default_widgets_for_dashboard_type("lead_tech"))
_check("T8B61", n30 == base, "next30 hides nothing")

# T8B62 -- rule subset.
from odoo.addons.neon_dashboard.models.ai.rule_based_adapter import (  # noqa: E402
    RuleBasedAdapter)
rules = RuleBasedAdapter(env=env)._rules_for_type("lead_tech")
names = {r.__name__ for r in rules}
_check("T8B62", names == {"_rule_crew_gaps", "_rule_cert_expiry"},
       f"{sorted(names)}")

# T8B63 -- crew-gap field-name fix.
fields = EventJob._fields
_check("T8B63",
       "crew_total_count" in fields and "crew_confirmed_count" in fields
       and "crew_required" not in fields and "crew_assigned" not in fields)

# T8B64 -- groq prompt.
from odoo.addons.neon_dashboard.models.ai.groq_adapter import (  # noqa: E402
    GroqAdapter)
provider = env["neon.dashboard.ai.provider"].sudo().search(
    [("provider_key", "=", "groq")], limit=1)
prompt = GroqAdapter(provider)._system_prompt(
    {"dashboard_type": "lead_tech", "today_date": "2026-05-27"})
_check("T8B64",
       ("crew" in prompt.lower() or "technician" in prompt.lower())
       and "{role_framing}" not in prompt)

# T8B65 -- orchestrator context.
from odoo.addons.neon_dashboard.models.ai.insight_orchestrator import (  # noqa: E402
    InsightOrchestrator)
lt_dash = Dashboard.sudo().get_or_create_for_user(
    user_id=u_lead.id, dashboard_type="lead_tech")
ctx = InsightOrchestrator(env)._build_context(lt_dash)
_check("T8B65", ctx.get("dashboard_type") == "lead_tech")

# T8B66 -- superuser peek honours requested type.
resolved_super = Dashboard.with_user(u_super)._resolve_dashboard_type(
    "lead_tech")
_check("T8B66", resolved_super == "lead_tech", f"got={resolved_super}")

# T8B67 -- non-superuser requested type ignored (peek = superuser-only;
# the ACL wall is that a lead_tech user asking for 'bookkeeper' still
# lands on their own default).
resolved_lead = Dashboard.with_user(u_lead)._resolve_dashboard_type(
    "bookkeeper")
_check("T8B67", resolved_lead == "lead_tech", f"got={resolved_lead}")

# T8B68 -- ACL.
err = None
try:
    Dashboard.with_user(u_lead).get_dashboard_data()
except Exception as e:  # noqa: BLE001
    err = e
_check("T8B68", err is None, f"err={err}")

sp.close(rollback=True)
print("=" * 72)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{len(results)} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
