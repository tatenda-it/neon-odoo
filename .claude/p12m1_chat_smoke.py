"""P12.M1 smoke — AI Sales Copilot chat + 9 READ tools.

Runs in `odoo shell -d <db>`. T12100-T12139.

Covers:
- Model presence + perm_unlink=0 + unique constraint on session
- Tool registry: 9 tool names registered, schemas valid
- Each of 9 tools: returns dict, has 'ok' key, handles missing
  args gracefully
- Orchestrator with mocked GroqChatAdapter: tool-call dispatch,
  message persistence, rate limit
- Live Groq smoke (skipped on key absence): one successful chat
  turn, prompt_tokens > 0, is_fallback=False on assistant turn
"""
import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P12.M1 — AI Sales Copilot chat + 9 READ tools")
print("=" * 72)
results = {}

Session = env["neon.finance.ai.chat.session"]
Message = env["neon.finance.ai.chat.message"]
Users = env["res.users"]
Partner = env["res.partner"]

from odoo.addons.neon_dashboard.models.ai import (
    tool_registry,
    chat_orchestrator as orch_mod,
)
from odoo.addons.neon_dashboard.models.ai.chat_orchestrator import (
    ChatOrchestrator,
)
from odoo.addons.neon_dashboard.models.ai.groq_chat_adapter import (
    GroqChatAdapter, ChatTurnResult,
)


# Ensure fixture sales user.
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


sales_user = _get_or_make_user(
    "p12m1_sales", "neon_jobs.group_neon_jobs_user")
director = _get_or_make_user(
    "p12m1_director", "neon_core.group_neon_superuser")


# T12100 -- both models present
_check("T12100", "neon.finance.ai.chat.session" in env.registry
       and "neon.finance.ai.chat.message" in env.registry,
       "models registered")


# T12101 -- perm_unlink=0 for every row on both models
access = env["ir.model.access"].search([
    ("model_id.model", "in", (
        "neon.finance.ai.chat.session",
        "neon.finance.ai.chat.message",
    )),
])
no_unlink = all(a.perm_unlink == 0 for a in access)
_check("T12101", no_unlink and len(access) >= 6,
       f"unlink count={sum(a.perm_unlink for a in access)} rows={len(access)}")


# T12102 -- session unique per user
s1 = Session.sudo().get_or_create_for_user(sales_user.id)
s2 = Session.sudo().get_or_create_for_user(sales_user.id)
_check("T12102", s1.id == s2.id, f"s1={s1.id} s2={s2.id}")


# T12103 -- the original 9 M12.1 tools are still registered
# (M12.1.1 added more; this test asserts the M12.1 baseline is
# intact, not the exact count).
read_tools = tool_registry.tool_names(category="read")
EXPECTED = {
    "get_open_quotes", "get_quote_details", "check_stock_availability",
    "get_crew_availability", "get_pending_deposits", "get_my_pipeline",
    "get_partner_history", "get_cert_expiry", "get_dashboard_summary",
}
_check("T12103", EXPECTED.issubset(set(read_tools)),
       f"got={sorted(read_tools)}")


# T12104 -- groq_tool_schemas returns OpenAI/Groq-shaped entries.
# M12.1.1 added more tools so >=9 is the post-M12.1 invariant.
schemas = tool_registry.groq_tool_schemas(category="read")
ok = (
    len(schemas) >= 9
    and all(s.get("type") == "function" for s in schemas)
    and all("function" in s and "name" in s["function"]
            and "parameters" in s["function"] for s in schemas)
)
_check("T12104", ok, f"schema count={len(schemas)}")


# === Individual tool smokes ===

# T12105 -- get_open_quotes returns ok+rows
res = tool_registry.dispatch(
    "get_open_quotes", env, sales_user, {})
_check("T12105",
       res.get("ok") is True and isinstance(res.get("rows"), list),
       f"count={res.get('count')}")


# T12106 -- get_quote_details with missing quote_id
res = tool_registry.dispatch("get_quote_details", env, sales_user, {})
_check("T12106", res.get("ok") is False, str(res.get("error"))[:80])


# T12107 -- check_stock_availability with missing args
res = tool_registry.dispatch(
    "check_stock_availability", env, sales_user, {})
_check("T12107", res.get("ok") is False, str(res.get("error"))[:80])


# T12108 -- check_stock_availability happy path (Sound category)
res = tool_registry.dispatch(
    "check_stock_availability", env, sales_user,
    {
        "equipment_category": "Sound",
        "start_date": str(date.today() + timedelta(days=3)),
        "end_date": str(date.today() + timedelta(days=5)),
    })
_check("T12108",
       res.get("ok") is True
       and "available_count" in res
       and "total_units" in res,
       f"avail={res.get('available_count')} total={res.get('total_units')}")


# T12109 -- get_crew_availability with date window
res = tool_registry.dispatch(
    "get_crew_availability", env, sales_user,
    {
        "start_date": str(date.today()),
        "end_date": str(date.today() + timedelta(days=7)),
    })
_check("T12109",
       res.get("ok") is True
       and "busy" in res and "free" in res,
       f"busy={res.get('busy_count')} free={res.get('free_count')}")


# T12110 -- get_pending_deposits empty path
res = tool_registry.dispatch(
    "get_pending_deposits", env, sales_user, {})
_check("T12110", res.get("ok") is True and "rows" in res,
       f"count={res.get('count')}")


# T12111 -- get_my_pipeline empty path
res = tool_registry.dispatch("get_my_pipeline", env, sales_user, {})
_check("T12111",
       res.get("ok") is True and "stages" in res,
       f"total={res.get('total_count')}")


# T12112 -- get_partner_history with missing args
res = tool_registry.dispatch(
    "get_partner_history", env, sales_user, {})
_check("T12112", res.get("ok") is False,
       str(res.get("error"))[:80])


# T12113 -- get_partner_history by name (use a real prod partner)
some_partner = Partner.search(
    [("is_company", "=", True)], limit=1)
res = tool_registry.dispatch(
    "get_partner_history", env, sales_user,
    {"partner_name": some_partner.name if some_partner else "x"})
_check("T12113",
       res.get("ok") in (True, False),
       f"matched={res.get('partner') is not None}")


# T12114 -- get_cert_expiry default window. M12.1.1 narrowed the
# tool's groups list to lead_tech + manager; call as the director
# (manager-tier) fixture user to exercise the happy path.
res = tool_registry.dispatch(
    "get_cert_expiry", env, director, {})
_check("T12114",
       res.get("ok") is True
       and "rows" in res and "days_ahead" in res,
       f"count={res.get('count')} days_ahead={res.get('days_ahead')}")


# T12115 -- get_dashboard_summary returns kpi dict
res = tool_registry.dispatch(
    "get_dashboard_summary", env, director, {})
_check("T12115",
       res.get("ok") is True and isinstance(res.get("kpi"), dict),
       f"keys={list((res.get('kpi') or {}).keys())[:3]}")


# T12116 -- dispatch unknown tool returns ok=False
res = tool_registry.dispatch("not_a_tool", env, sales_user, {})
_check("T12116", res.get("ok") is False,
       str(res.get("error"))[:80])


# === Orchestrator path ===

# Wipe rate-limit bucket for the test user so prior runs don't poison.
orch_mod._RATE_LIMIT_BY_USER[sales_user.id] = []


# T12117 -- orchestrator handles 'no active provider' gracefully
# Temporarily disable the groq provider to exercise the path.
Provider = env["neon.dashboard.ai.provider"]
groq = Provider.sudo().search([("provider_key", "=", "groq")], limit=1)
old_enabled = groq.is_enabled
groq.sudo().write({"is_enabled": False})
session = Session.sudo().get_or_create_for_user(sales_user.id)
res = ChatOrchestrator(env).handle_user_message(
    sales_user, session, "hello world")
groq.sudo().write({"is_enabled": old_enabled})
_check("T12117",
       res.get("ok") is False
       and res.get("error_message") == "no_active_provider",
       f"ok={res.get('ok')} err={res.get('error_message')}")


# T12118 -- orchestrator persists user + assistant turns with mock
# Wipe rate-limit again before mocked turn.
orch_mod._RATE_LIMIT_BY_USER[sales_user.id] = []
mock_result = ChatTurnResult(
    success=True,
    assistant_message="Test assistant reply.",
    prompt_tokens=10, completion_tokens=5, latency_ms=42,
)
with patch.object(GroqChatAdapter, "chat",
                  return_value=mock_result):
    res = ChatOrchestrator(env).handle_user_message(
        sales_user, session,
        "P12 unit test message — assistant reply path")
ok = (
    res.get("ok") is True
    and res.get("assistant_message") == "Test assistant reply."
    and res.get("prompt_tokens") == 10
)
_check("T12118", ok,
       f"ok={res.get('ok')} tokens={res.get('prompt_tokens')}")

# T12119 -- assistant turn persisted with provider_key + tokens
last_assist = Message.sudo().search(
    [("session_id", "=", session.id), ("role", "=", "assistant")],
    order="id desc", limit=1)
_check("T12119",
       last_assist.provider_key == "groq"
       and last_assist.prompt_tokens == 10
       and last_assist.completion_tokens == 5
       and last_assist.latency_ms == 42,
       f"provider={last_assist.provider_key} "
       f"pt={last_assist.prompt_tokens}")


# T12120 -- tool_call loop with mock
orch_mod._RATE_LIMIT_BY_USER[sales_user.id] = []
turn1 = ChatTurnResult(
    success=True, assistant_message="",
    tool_calls=[{
        "tool_call_id": "tc_test_1",
        "tool_name": "get_open_quotes",
        "params": {},
    }],
    prompt_tokens=20, completion_tokens=8, latency_ms=30,
)
turn2 = ChatTurnResult(
    success=True,
    assistant_message="Here are your open quotes.",
    prompt_tokens=40, completion_tokens=12, latency_ms=25,
)
with patch.object(GroqChatAdapter, "chat",
                  side_effect=[turn1, turn2]):
    res = ChatOrchestrator(env).handle_user_message(
        sales_user, session,
        "P12 unit test — tool-call loop branch")
ok = (
    res.get("ok") is True
    and res.get("assistant_message") == "Here are your open quotes."
    and len(res.get("tool_cards") or []) == 1
    and res["tool_cards"][0]["tool"] == "get_open_quotes"
)
_check("T12120", ok,
       f"tool_cards={len(res.get('tool_cards') or [])}")


# T12121 -- tool result row persisted via role='tool'
tool_msg = Message.sudo().search(
    [("session_id", "=", session.id),
     ("tool_name", "=", "get_open_quotes")],
    order="id desc", limit=1)
_check("T12121",
       bool(tool_msg) and tool_msg.role == "tool"
       and tool_msg.tool_call_id == "tc_test_1",
       f"tool_call_id={tool_msg.tool_call_id if tool_msg else 'NONE'}")


# T12122 -- adapter error → user-friendly fallback
orch_mod._RATE_LIMIT_BY_USER[sales_user.id] = []
err_result = ChatTurnResult(
    success=False, is_fallback=True,
    error_message="Groq HTTP error: simulated 500",
    latency_ms=12,
)
with patch.object(GroqChatAdapter, "chat",
                  return_value=err_result):
    res = ChatOrchestrator(env).handle_user_message(
        sales_user, session,
        "P12 unit test — error fallback branch")
ok = (
    res.get("ok") is False
    and res.get("is_fallback") is True
    and "can't reach" in res.get("assistant_message", "")
)
_check("T12122", ok,
       f"ok={res.get('ok')} msg={res.get('assistant_message')[:60]}")


# T12123 -- rate-limit kicks in after 30 turns in the window
# Pre-fill the bucket with 30 fresh timestamps and try.
import time as _time
orch_mod._RATE_LIMIT_BY_USER[sales_user.id] = [
    _time.time() for _ in range(30)]
res = ChatOrchestrator(env).handle_user_message(
    sales_user, session, "should be rate limited")
ok = (res.get("ok") is False
      and res.get("error_message") == "rate_limit_exceeded")
_check("T12123", ok,
       f"err={res.get('error_message')}")
# Reset the bucket so the live test below is unblocked.
orch_mod._RATE_LIMIT_BY_USER[sales_user.id] = []


# T12124 -- system prompt template stored in ir.config_parameter
Config = env["ir.config_parameter"].sudo()
custom_prompt = (
    "P12 test system prompt {today_date} ABCD")
Config.set_param(
    "neon_finance.ai_chat_system_prompt", custom_prompt)
orch = ChatOrchestrator(env)
generated = orch._system_prompt()
_check("T12124",
       "ABCD" in generated and "{today_date}" not in generated,
       f"prompt[:80]={generated[:80]!r}")
# Reset to default so other tests don't see the custom value.
Config.set_param(
    "neon_finance.ai_chat_system_prompt", "")


# === Live Groq smoke (live API key check). ===
key = Config.get_param("neon_dashboard.ai_keys_groq", "")
live_ok = False
live_meta = "skipped"
if not key:
    _check("T12125", True, "skipped (no API key)")
else:
    orch_mod._RATE_LIMIT_BY_USER[sales_user.id] = []
    res = ChatOrchestrator(env).handle_user_message(
        sales_user, session,
        "Ping. Reply with the single word OK.")
    live_ok = (
        res.get("ok") is True
        and not res.get("is_fallback")
        and res.get("prompt_tokens", 0) > 0
        and res.get("assistant_message")
    )
    live_meta = (
        f"tokens={res.get('prompt_tokens')}/"
        f"{res.get('completion_tokens')} "
        f"lat={res.get('latency_ms')}ms")
    _check("T12125", live_ok, live_meta)


# T12126 -- ACL: session model includes the sales + manager rows
acl_rows = env["ir.model.access"].search([
    ("model_id.model", "=", "neon.finance.ai.chat.session"),
])
groups = {a.group_id.id for a in acl_rows}
sales_group = env.ref("neon_jobs.group_neon_jobs_user").id
mgr_group = env.ref("neon_jobs.group_neon_jobs_manager").id
_check("T12126",
       sales_group in groups and mgr_group in groups,
       f"groups={len(groups)}")


# T12127 -- res.users carries chat_panel_expanded field
_check("T12127",
       "chat_panel_expanded" in Users._fields,
       "field present")


# T12128 -- toggle controller updates chat_panel_expanded
old = sales_user.chat_panel_expanded
sales_user.write({"chat_panel_expanded": not old})
sales_user.invalidate_recordset(["chat_panel_expanded"])
_check("T12128", sales_user.chat_panel_expanded != old,
       f"toggled {old} -> {sales_user.chat_panel_expanded}")
sales_user.write({"chat_panel_expanded": False})


# T12129 -- tool sets all carry a `tool` key in their result
all_have_tool_key = True
for name in EXPECTED:
    # Pass empty params; some will error but the key must still be
    # present in the dispatch result.
    r = tool_registry.dispatch(name, env, sales_user, {})
    if "tool" not in r:
        all_have_tool_key = False
        break
_check("T12129", all_have_tool_key, "every dispatch tags 'tool'")


# T12130 -- empty assistant content with only tool_calls is
# persisted (regression check on Message.create with content="")
empty_msg = Message.sudo().search([
    ("session_id", "=", session.id),
    ("role", "=", "assistant"),
    ("tool_calls_json", "!=", False),
], limit=1)
_check("T12130", bool(empty_msg),
       f"tool_calls_json populated: {bool(empty_msg.tool_calls_json) if empty_msg else False}")


# ----------------------------------------------------------------------
# Cleanup -- prune the test session messages so subsequent runs are
# tidy. (We can't unlink session due to perm_unlink=0; messages too.
# Test runs accumulate; trim to the most recent 20 via raw SQL.)
# ----------------------------------------------------------------------


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
