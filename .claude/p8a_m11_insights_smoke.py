"""P8A.M11 smoke -- AI Insights (Groq + Rule-based + orchestrator).

T9100-T9129.

T9100  Models registered: neon.dashboard.ai.provider + neon.dashboard.ai.insight
T9101  Seed records: Groq (default+enabled) + Rule-based (enabled, not default)
T9102  Cron seeded + active, model_id=neon.dashboard.ai.provider, hourly
T9103  Adapter contract: BaseAdapter -- both Groq + RuleBased subclass + implement methods
T9104  GroqAdapter success path (mocked): returns parsed insights from JSON response
T9105  GroqAdapter HTTP 500 path (mocked): success=False + error_message captured
T9106  GroqAdapter timeout path (mocked): success=False + error_message=timeout
T9107  GroqAdapter malformed JSON (mocked): parser fallback regex; returns empty if no JSON in body
T9108  GroqAdapter no API key: success=False with descriptive error
T9109  RuleBasedAdapter: overdue invoices rule produces InsightItems with source_ref
T9110  RuleBasedAdapter: crew gaps rule (skipped gracefully if no upcoming jobs)
T9111  RuleBasedAdapter: cert expiry rule (skipped gracefully if no expiring certs)
T9112  RuleBasedAdapter: pipeline behind target rule fires when pct < 80 AND days > 50%
T9113  RuleBasedAdapter: cash low rule fires when AR > 1.5x cash
T9114  RuleBasedAdapter: slow lead rule fires when leads stale > 3 days no activity
T9115  Orchestrator success: AI succeeds -> insight row is_fallback=False
T9116  Orchestrator AI failure: rule-based fires, is_fallback=True, error_message captured
T9117  Orchestrator no active provider: rule-based fires with descriptive error
T9118  Encryption: API key in ir.config_parameter not in api_key_encrypted field
T9119  _get_decrypted_api_key returns plaintext when set; empty when unset
T9120  _set_api_key writes to config_parameter + stamps reference marker
T9121  Cron at non-6/12/18 Harare: no-op (no insight created)
T9122  Cron at 6/12/18 Harare: generates for each dashboard
T9123  Manual refresh rate limit: 2nd within 5 min -> UserError
T9124  Manual refresh non-superuser: AccessError
T9125  ACL: non-superuser cannot read neon.dashboard.ai.provider
T9126  ACL: internal user can read neon.dashboard.ai.insight (latest)
T9127  Token truncation: large context > MAX_INPUT_CHARS -> low-priority fields dropped
T9128  rpc_latest_insight_for_current_user empty payload when no insight ever
T9129  manifest version 17.0.8.8.0
"""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import requests as _requests_module

from odoo.exceptions import AccessError, UserError


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


print("=" * 72)
print("P8A.M11 -- AI Insights")
print("=" * 72)
results = {}

Provider = env["neon.dashboard.ai.provider"]
Insight = env["neon.dashboard.ai.insight"]
Dashboard = env["neon.dashboard"]
Users = env["res.users"]
Config = env["ir.config_parameter"]


# Adapters (plain Python -- imported via the model file's path)
from odoo.addons.neon_dashboard.models.ai.base_adapter import (  # noqa: E402
    AdapterResult, BaseAdapter, InsightItem,
)
from odoo.addons.neon_dashboard.models.ai.groq_adapter import (  # noqa: E402
    GroqAdapter,
)
from odoo.addons.neon_dashboard.models.ai.rule_based_adapter import (  # noqa: E402
    RuleBasedAdapter,
)
from odoo.addons.neon_dashboard.models.ai.insight_orchestrator import (  # noqa: E402
    InsightOrchestrator,
    _MAX_INPUT_CHARS,
    MAX_INPUT_TOKENS,
)


# ============================================================
print()
print("T9100 -- both models registered")
print("=" * 72)
ok = ("neon.dashboard.ai.provider" in env.registry
      and "neon.dashboard.ai.insight" in env.registry)
print(f"  provider: {'neon.dashboard.ai.provider' in env.registry}")
print(f"  insight: {'neon.dashboard.ai.insight' in env.registry}")
print("T9100:", "PASS" if ok else "FAIL")
results["T9100"] = ok


# ============================================================
print()
print("T9101 -- seed records (Groq default+enabled, Rule-based enabled)")
print("=" * 72)
groq = env.ref("neon_dashboard.ai_provider_groq",
               raise_if_not_found=False)
rule = env.ref("neon_dashboard.ai_provider_rule_based",
               raise_if_not_found=False)
ok = (groq and groq.is_default and groq.is_enabled
      and rule and rule.is_enabled and not rule.is_default
      and groq.provider_key == "groq"
      and rule.provider_key == "rule_based")
print(f"  groq id={groq.id if groq else None} "
      f"default={groq.is_default if groq else None} "
      f"enabled={groq.is_enabled if groq else None}")
print(f"  rule id={rule.id if rule else None} "
      f"default={rule.is_default if rule else None}")
print("T9101:", "PASS" if ok else "FAIL")
results["T9101"] = ok


# ============================================================
print()
print("T9102 -- cron seeded, hourly, model neon.dashboard.ai.provider")
print("=" * 72)
cron = env.ref("neon_dashboard.cron_ai_insights_refresh",
               raise_if_not_found=False)
ok = (cron and cron.active and cron.interval_type == "hours"
      and cron.model_id.model == "neon.dashboard.ai.provider")
print(f"  cron id={cron.id if cron else None} "
      f"active={cron.active if cron else None} "
      f"interval={cron.interval_type if cron else None} "
      f"model={cron.model_id.model if cron else None}")
print("T9102:", "PASS" if ok else "FAIL")
results["T9102"] = ok


# ============================================================
print()
print("T9103 -- adapter contract")
print("=" * 72)
ok = (issubclass(GroqAdapter, BaseAdapter)
      and issubclass(RuleBasedAdapter, BaseAdapter)
      and hasattr(GroqAdapter, "generate_insights")
      and hasattr(GroqAdapter, "health_check")
      and hasattr(RuleBasedAdapter, "generate_insights")
      and hasattr(RuleBasedAdapter, "health_check"))
print(f"  contract holds: {ok}")
print("T9103:", "PASS" if ok else "FAIL")
results["T9103"] = ok


# Fixtures under savepoint
sp = env.cr.savepoint()

# Set a fake API key so the Groq adapter doesn't bail out on
# "no API key" before the mocked requests.post can fire.
groq._set_api_key("test-fake-key-for-smoke")


def _make_mock_response(status_code, json_payload=None, text_payload=""):
    """Build a requests-like mock response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json = MagicMock(return_value=json_payload or {})
    resp.text = text_payload
    if resp.ok:
        resp.raise_for_status = MagicMock()
    else:
        def _raise():
            raise _requests_module.exceptions.HTTPError(
                f"HTTP {status_code}")
        resp.raise_for_status = _raise
    return resp


_DUMMY_CONTEXT = {
    "today_date": "2026-05-26",
    "user_name": "Test User",
    "business_currency": "USD",
    "kpi_forecast": {"forecast_vs_target_pct": 65,
                     "days_elapsed_pct": 70},
    "kpi_cash": {"value_usd": 1000, "display": "$1k"},
    "kpi_ar_overdue": {"value_usd": 2000, "display": "$2k"},
}


# ============================================================
print()
print("T9104 -- Groq success path (mocked)")
print("=" * 72)
groq_response = {
    "choices": [{
        "message": {
            "content": json.dumps({
                "insights": [
                    {"priority": 1, "title": "Test 1", "detail": "D1",
                     "source_ref": {"model": "res.partner", "res_id": 1}},
                    {"priority": 2, "title": "Test 2", "detail": "D2",
                     "source_ref": None},
                ]
            })
        }
    }],
    "usage": {"prompt_tokens": 150, "completion_tokens": 80},
}
with patch.object(_requests_module, "post",
                  return_value=_make_mock_response(200, groq_response)):
    result = GroqAdapter(groq).generate_insights(_DUMMY_CONTEXT)
ok = (result.success and len(result.insights) == 2
      and result.insights[0].title == "Test 1"
      and result.prompt_tokens == 150
      and result.completion_tokens == 80)
print(f"  success={result.success} n_insights={len(result.insights)}")
print("T9104:", "PASS" if ok else "FAIL")
results["T9104"] = ok


# ============================================================
print()
print("T9105 -- Groq HTTP 500 path")
print("=" * 72)
with patch.object(_requests_module, "post",
                  return_value=_make_mock_response(500, text_payload="boom")):
    result = GroqAdapter(groq).generate_insights(_DUMMY_CONTEXT)
ok = (not result.success and "500" in (result.error_message or ""))
print(f"  success={result.success} err={result.error_message}")
print("T9105:", "PASS" if ok else "FAIL")
results["T9105"] = ok


# ============================================================
print()
print("T9106 -- Groq timeout path")
print("=" * 72)
with patch.object(
        _requests_module, "post",
        side_effect=_requests_module.exceptions.Timeout("simulated")):
    result = GroqAdapter(groq).generate_insights(_DUMMY_CONTEXT)
ok = (not result.success
      and "timed out" in (result.error_message or "").lower())
print(f"  success={result.success} err={result.error_message}")
print("T9106:", "PASS" if ok else "FAIL")
results["T9106"] = ok


# ============================================================
print()
print("T9107 -- Groq malformed JSON")
print("=" * 72)
malformed_resp = {
    "choices": [{"message": {"content": "not json at all"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
}
with patch.object(_requests_module, "post",
                  return_value=_make_mock_response(200, malformed_resp)):
    result = GroqAdapter(groq).generate_insights(_DUMMY_CONTEXT)
ok = (result.success and len(result.insights) == 0)  # success=True but empty
print(f"  success={result.success} n_insights={len(result.insights)}")
print("T9107:", "PASS" if ok else "FAIL")
results["T9107"] = ok


# ============================================================
print()
print("T9108 -- Groq no API key")
print("=" * 72)
# Temporarily clear key
saved_key = groq._get_decrypted_api_key()
Config.sudo().set_param("neon_dashboard.ai_keys_groq", "")
result = GroqAdapter(groq).generate_insights(_DUMMY_CONTEXT)
ok = (not result.success
      and "api key" in (result.error_message or "").lower())
print(f"  success={result.success} err={result.error_message}")
# Restore
Config.sudo().set_param("neon_dashboard.ai_keys_groq", saved_key)
print("T9108:", "PASS" if ok else "FAIL")
results["T9108"] = ok


# ============================================================
print()
print("T9109 -- RuleBased: overdue invoices")
print("=" * 72)
# Create one overdue invoice as a fixture
Partner = env["res.partner"]
Move = env["account.move"]
test_partner = Partner.sudo().create({"name": "M11 overdue test"})
today = Dashboard._today_harare()
overdue_due = today - timedelta(days=70)
test_move = Move.sudo().create({
    "move_type": "out_invoice",
    "partner_id": test_partner.id,
    "invoice_date": today - timedelta(days=80),
    "invoice_date_due": overdue_due,
    "invoice_line_ids": [(0, 0, {
        "name": "Test", "quantity": 1, "price_unit": 500,
    })],
})
test_move.sudo().action_post()
items = []
RuleBasedAdapter(provider_record=None, env=env)\
    ._rule_overdue_invoices(items, _DUMMY_CONTEXT)
ok = any(test_partner.name[:20] in i.title for i in items)
print(f"  items produced: {len(items)}; matches: {ok}")
for i in items[:3]:
    print(f"    {i.title}")
print("T9109:", "PASS" if ok else "FAIL")
results["T9109"] = ok


# ============================================================
print()
print("T9110 -- RuleBased: crew gaps (skip when none)")
print("=" * 72)
items = []
# Just verify the rule doesn't crash. Real prod data may or may
# not have an upcoming gap; we only assert no exception.
err, _ = _try(lambda: RuleBasedAdapter(
    provider_record=None, env=env)._rule_crew_gaps(
        items, _DUMMY_CONTEXT))
ok = err is None
print(f"  err: {err}")
print("T9110:", "PASS" if ok else "FAIL")
results["T9110"] = ok


# ============================================================
print()
print("T9111 -- RuleBased: cert expiry (no crash)")
print("=" * 72)
items = []
err, _ = _try(lambda: RuleBasedAdapter(
    provider_record=None, env=env)._rule_cert_expiry(
        items, _DUMMY_CONTEXT))
ok = err is None
print(f"  err: {err}")
print("T9111:", "PASS" if ok else "FAIL")
results["T9111"] = ok


# ============================================================
print()
print("T9112 -- RuleBased: pipeline behind target")
print("=" * 72)
items = []
RuleBasedAdapter(provider_record=None, env=env)\
    ._rule_pipeline_behind_target(items, _DUMMY_CONTEXT)
ok = (len(items) == 1 and "65%" in items[0].title)
print(f"  items: {len(items)}; first: {items[0].title if items else None}")
print("T9112:", "PASS" if ok else "FAIL")
results["T9112"] = ok


# ============================================================
print()
print("T9113 -- RuleBased: cash low (AR > 1.5x cash)")
print("=" * 72)
items = []
# DUMMY ctx has AR=2000, cash=1000 -> 2.0x -> rule fires.
RuleBasedAdapter(provider_record=None, env=env)\
    ._rule_cash_low(items, _DUMMY_CONTEXT)
ok = len(items) == 1 and "AR overdue" in items[0].title
print(f"  items: {len(items)}; first: {items[0].title if items else None}")
print("T9113:", "PASS" if ok else "FAIL")
results["T9113"] = ok


# ============================================================
print()
print("T9114 -- RuleBased: slow lead followup (no crash)")
print("=" * 72)
items = []
err, _ = _try(lambda: RuleBasedAdapter(
    provider_record=None, env=env)._rule_slow_lead_followup(
        items, _DUMMY_CONTEXT))
ok = err is None
print(f"  err: {err}")
print("T9114:", "PASS" if ok else "FAIL")
results["T9114"] = ok


# ============================================================
print()
print("T9115 -- Orchestrator success path (Groq mocked)")
print("=" * 72)
test_user = Users.sudo().search(
    [("login", "=", "p8a_director")], limit=1)
if not test_user:
    test_user = Users.sudo().with_context(no_reset_password=True).create({
        "name": "p8a_director", "login": "p8a_director",
        "password": "test123",
        "groups_id": [(4, env.ref("neon_core.group_neon_superuser").id)],
    })
test_dashboard = Dashboard.sudo().search(
    [("user_id", "=", test_user.id)], limit=1)
if not test_dashboard:
    test_dashboard = Dashboard.sudo().get_or_create_for_user(test_user.id)
with patch.object(_requests_module, "post",
                  return_value=_make_mock_response(200, groq_response)):
    new_insight = InsightOrchestrator(env)\
        .generate_for_dashboard(test_dashboard)
ok = (new_insight and not new_insight.is_fallback
      and new_insight.provider_id == groq
      and len(new_insight.parsed_insights) == 2)
print(f"  insight id={new_insight.id} is_fallback={new_insight.is_fallback} "
      f"provider={new_insight.provider_id.name}")
print("T9115:", "PASS" if ok else "FAIL")
results["T9115"] = ok


# ============================================================
print()
print("T9116 -- Orchestrator AI failure -> rule-based fallback")
print("=" * 72)
with patch.object(
        _requests_module, "post",
        return_value=_make_mock_response(500, text_payload="boom")):
    fb_insight = InsightOrchestrator(env)\
        .generate_for_dashboard(test_dashboard)
ok = (fb_insight and fb_insight.is_fallback
      and fb_insight.provider_id == rule
      and "500" in (fb_insight.error_message or ""))
print(f"  fallback id={fb_insight.id} is_fallback={fb_insight.is_fallback} "
      f"err={(fb_insight.error_message or '')[:80]}")
print("T9116:", "PASS" if ok else "FAIL")
results["T9116"] = ok


# ============================================================
print()
print("T9117 -- Orchestrator no active provider -> fallback")
print("=" * 72)
# Temporarily clear default
groq.sudo().write({"is_default": False})
no_active_insight = InsightOrchestrator(env)\
    .generate_for_dashboard(test_dashboard)
ok = (no_active_insight.is_fallback
      and "No active" in (no_active_insight.error_message or ""))
print(f"  err: {no_active_insight.error_message}")
# Restore
groq.sudo().write({"is_default": True})
print("T9117:", "PASS" if ok else "FAIL")
results["T9117"] = ok


# ============================================================
print()
print("T9118 -- API key in config_parameter not in model field")
print("=" * 72)
groq._set_api_key("super-secret-key-9000")
field_value = groq.api_key_encrypted or ""
config_value = Config.sudo().get_param(
    "neon_dashboard.ai_keys_groq", "")
ok = (field_value == "groq:v1"
      and config_value == "super-secret-key-9000")
print(f"  field={field_value!r} (reference marker only)")
print(f"  config_param={'***' if config_value else 'empty'}")
print("T9118:", "PASS" if ok else "FAIL")
results["T9118"] = ok


# ============================================================
print()
print("T9119 -- _get_decrypted_api_key")
print("=" * 72)
key = groq._get_decrypted_api_key()
ok_set = key == "super-secret-key-9000"
# Empty case
Config.sudo().set_param("neon_dashboard.ai_keys_groq", "")
key_empty = groq._get_decrypted_api_key()
ok_empty = key_empty == ""
ok = ok_set and ok_empty
print(f"  set={ok_set} empty={ok_empty}")
Config.sudo().set_param("neon_dashboard.ai_keys_groq", "super-secret-key-9000")
print("T9119:", "PASS" if ok else "FAIL")
results["T9119"] = ok


# ============================================================
print()
print("T9120 -- _set_api_key writes to config_parameter")
print("=" * 72)
groq._set_api_key("another-key")
ok = (Config.sudo().get_param("neon_dashboard.ai_keys_groq")
      == "another-key")
print(f"  written: {ok}")
print("T9120:", "PASS" if ok else "FAIL")
results["T9120"] = ok


# ============================================================
print()
print("T9121 -- Cron skip at non-6/12/18 Harare hour")
print("=" * 72)
import pytz as _pytz
HARARE_TZ = _pytz.timezone("Africa/Harare")

def _harare_mock(hour):
    """Return a real tz-aware datetime at the given Harare hour.
    Used to mock _now_harare in cron + compute paths -- a plain
    class lacks .replace() which _compute_age_hours requires."""
    return HARARE_TZ.localize(datetime(2026, 5, 26, hour, 0, 0))

with patch.object(type(Dashboard), "_now_harare",
                  return_value=_harare_mock(9)):
    before = Insight.search_count([])
    Provider.cron_refresh_ai_insights()
    after = Insight.search_count([])
ok = after == before
print(f"  before={before} after={after}")
print("T9121:", "PASS" if ok else "FAIL")
results["T9121"] = ok


# ============================================================
print()
print("T9122 -- Cron fires at 6/12/18 Harare")
print("=" * 72)
with patch.object(type(Dashboard), "_now_harare",
                  return_value=_harare_mock(12)), \
     patch.object(_requests_module, "post",
                  return_value=_make_mock_response(200, groq_response)):
    before = Insight.search_count([])
    Provider.cron_refresh_ai_insights()
    after = Insight.search_count([])
ok = after > before
print(f"  before={before} after={after}")
print("T9122:", "PASS" if ok else "FAIL")
results["T9122"] = ok


# ============================================================
print()
print("T9123 -- Manual refresh rate limit")
print("=" * 72)
# Clear in-memory rate map
from odoo.addons.neon_dashboard.models import neon_dashboard_ai_provider as _mod  # noqa: E402
_mod._MANUAL_REFRESH_LAST_BY_USER.clear()
with patch.object(_requests_module, "post",
                  return_value=_make_mock_response(200, groq_response)):
    err1, _ = _try(lambda: Provider.with_user(test_user)
                   .rpc_refresh_for_current_user())
    err2, _ = _try(lambda: Provider.with_user(test_user)
                   .rpc_refresh_for_current_user())
ok = (err1 is None and isinstance(err2, UserError)
      and "rate-limited" in (str(err2)).lower())
print(f"  err1={err1} err2={type(err2).__name__ if err2 else None}: "
      f"{str(err2)[:80] if err2 else ''}")
print("T9123:", "PASS" if ok else "FAIL")
results["T9123"] = ok


# ============================================================
print()
print("T9124 -- Manual refresh non-superuser")
print("=" * 72)
basic_user = Users.sudo().search(
    [("login", "=", "p8a_m11_basic")], limit=1)
if not basic_user:
    basic_user = Users.sudo().with_context(
        no_reset_password=True).create({
            "name": "p8a_m11_basic", "login": "p8a_m11_basic",
            "password": "test123",
            "groups_id": [(4, env.ref("base.group_user").id)],
        })
err, _ = _try(lambda: Provider.with_user(basic_user)
              .rpc_refresh_for_current_user())
ok = isinstance(err, AccessError)
print(f"  err: {type(err).__name__ if err else 'no error'}")
print("T9124:", "PASS" if ok else "FAIL")
results["T9124"] = ok


# ============================================================
print()
print("T9125 -- ACL: non-superuser cannot read provider")
print("=" * 72)
err, _ = _try(lambda: Provider.with_user(basic_user)
              .search([]).mapped("id"))
ok = isinstance(err, AccessError)
print(f"  err: {type(err).__name__ if err else 'no error'}")
print("T9125:", "PASS" if ok else "FAIL")
results["T9125"] = ok


# ============================================================
print()
print("T9126 -- ACL: internal user CAN read insight history")
print("=" * 72)
err, val = _try(lambda: Insight.with_user(basic_user)
                .search([], limit=1).mapped("generated_on"))
ok = err is None
print(f"  err: {err}; returned: {val}")
print("T9126:", "PASS" if ok else "FAIL")
results["T9126"] = ok


# ============================================================
print()
print("T9127 -- Token truncation: large context -> low-priority dropped")
print("=" * 72)
huge_ctx = {
    "today_date": "2026-05-26",
    "kpi_cash": {"display": "$1k"},
    "tasks_block": {"tasks": ["x" * 100 for _ in range(500)]},
    "crew_equipment_block": {"detail": "y" * 5000},
    "sales_block": {"stages": ["z" * 100 for _ in range(100)]},
    "alerts_block": {"alerts": ["a" * 100 for _ in range(50)]},
    "jobs_block": {"rows": [{"name": "job"} for _ in range(20)]},
}
truncated = InsightOrchestrator(env)._truncate_context(huge_ctx)
size_before = len(json.dumps(huge_ctx, default=str))
size_after = len(json.dumps(truncated, default=str))
ok = (size_after < size_before
      and "tasks_block" not in truncated
      and "kpi_cash" in truncated)
print(f"  before={size_before}b after={size_after}b "
      f"(limit={_MAX_INPUT_CHARS}b)")
print(f"  dropped: tasks_block + others; kept: kpi_cash")
print("T9127:", "PASS" if ok else "FAIL")
results["T9127"] = ok


# ============================================================
print()
print("T9128 -- rpc_latest empty payload when no insight")
print("=" * 72)
# Fresh dashboard with no insights yet
fresh_user = Users.sudo().with_context(
    no_reset_password=True).create({
        "name": "p8a_m11_fresh", "login": "p8a_m11_fresh",
        "password": "test123",
        "groups_id": [(4, env.ref("neon_core.group_neon_superuser").id)],
    })
fresh_dashboard = Dashboard.sudo().get_or_create_for_user(fresh_user.id)
payload = Provider.with_user(fresh_user)\
    .rpc_latest_insight_for_current_user()
ok = (isinstance(payload, dict) and payload.get("empty") is True
      and isinstance(payload.get("insights"), list))
print(f"  payload: empty={payload.get('empty')} "
      f"configured={payload.get('configured')}")
print("T9128:", "PASS" if ok else "FAIL")
results["T9128"] = ok


# ============================================================
print()
print("T9129 -- manifest version >= 17.0.8.8.0 (M11 bump or later)")
print("=" * 72)
mod = env["ir.module.module"].search(
    [("name", "=", "neon_dashboard")], limit=1)
def _ver_tuple(v):
    return tuple(int(x) for x in (v or "0").split(".") if x.isdigit())
ok = mod and _ver_tuple(mod.latest_version) >= _ver_tuple("17.0.8.8.0")
print(f"  installed version: {mod.latest_version if mod else 'MISSING'}")
print("T9129:", "PASS" if ok else "FAIL")
results["T9129"] = ok


# Rollback fixtures.
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
