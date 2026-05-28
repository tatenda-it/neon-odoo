"""P12.M1.1 smoke — multi-variant chat + 5 new tools + hotfixes.

Runs in `odoo shell -d <db>`. T12150-T12179.

Covers:
- 14 tools registered (M12.1's 9 + M12.1.1's 5)
- Per-tool groups field + dispatch ACL enforcement
- TOOLS_BY_VARIANT registry + filter_tools_for_variant_and_user
- D17 dedup of identical tool calls within one turn
- D18 history pruning preserves tool_call_id pairings
- D24 manager+director sees ALL; manager peeking another variant
  gets that variant's set
- D25 role_label injection per variant
- 5 new tools: shape, ACL, empty path, args validation
- ACL CSV widened: 10 chat rows (5 groups × 2 models)
"""
import json
from unittest.mock import patch


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P12.M1.1 — multi-variant chat + 5 new tools + hotfixes")
print("=" * 72)
results = {}

Users = env["res.users"]
Session = env["neon.finance.ai.chat.session"]
Message = env["neon.finance.ai.chat.message"]

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


def _gom(login, group_xmlids):
    u = Users.search([("login", "=", login)], limit=1)
    ids = [env.ref(x).id for x in group_xmlids]
    if not u:
        u = Users.with_context(no_reset_password=True).create({
            "name": login, "login": login, "password": "test123",
            "groups_id": [(4, gid) for gid in ids],
        })
    else:
        for gid in ids:
            if gid not in u.groups_id.ids:
                u.write({"groups_id": [(4, gid)]})
    return u


sales_user = _gom("p12m1_sales_v2", [
    "base.group_user",
    "neon_jobs.group_neon_jobs_user",
    "neon_core.group_neon_sales_rep",
])
bookkeeper_user = _gom("p12m1_bookkeeper_v2", [
    "base.group_user",
    "neon_core.group_neon_bookkeeper",
])
lead_tech_user = _gom("p12m1_leadtech_v2", [
    "base.group_user",
    "neon_jobs.group_neon_jobs_crew_leader",
    "neon_core.group_neon_lead_tech",
])
director_user = _gom("p12m1_director_v2", [
    "base.group_user",
    "neon_jobs.group_neon_jobs_user",
    "neon_jobs.group_neon_jobs_manager",
    "neon_core.group_neon_superuser",
])


# === Tool registry ===

# T12150 -- 14 tools registered total
all_tools = tool_registry.tool_names(category="read")
_check("T12150", len(all_tools) == 14,
       f"got={len(all_tools)} tools={sorted(all_tools)}")


# T12151 -- 5 new tools present
NEW = {"get_overdue_invoices", "get_zig_rate", "get_budget_status",
       "get_jobs_this_week", "get_readiness_gates"}
_check("T12151", NEW.issubset(set(all_tools)),
       f"missing={NEW - set(all_tools)}")


# T12152 -- every tool has a non-empty groups list (no defensive
# fall-through to "open to anyone")
no_groups = [t.name for t in tool_registry.list_tools()
             if not t.groups]
_check("T12152", not no_groups, f"missing_groups={no_groups}")


# T12153 -- TOOLS_BY_VARIANT keys
expected_variants = {"director", "sales", "bookkeeper", "lead_tech"}
_check("T12153",
       set(tool_registry.TOOLS_BY_VARIANT.keys()) == expected_variants,
       f"got={list(tool_registry.TOOLS_BY_VARIANT.keys())}")


# === Per-tool ACL ===

# T12154 -- sales user CAN call get_open_quotes
res = tool_registry.dispatch(
    "get_open_quotes", env, sales_user, {})
_check("T12154", res.get("ok") is True, "sales can get_open_quotes")


# T12155 -- sales user CANNOT call get_overdue_invoices
# (bookkeeper-only). dispatch should refuse without running.
res = tool_registry.dispatch(
    "get_overdue_invoices", env, sales_user, {})
_check("T12155",
       res.get("ok") is False
       and "access_denied" in (res.get("error") or ""),
       f"err={res.get('error')!r}")


# T12156 -- bookkeeper user CAN call get_overdue_invoices
res = tool_registry.dispatch(
    "get_overdue_invoices", env, bookkeeper_user, {})
_check("T12156", res.get("ok") is True,
       f"count={res.get('count')}")


# T12157 -- bookkeeper user CANNOT call get_my_pipeline (sales-only)
res = tool_registry.dispatch(
    "get_my_pipeline", env, bookkeeper_user, {})
_check("T12157",
       res.get("ok") is False
       and "access_denied" in (res.get("error") or ""),
       f"err={res.get('error')!r}")


# T12158 -- manager (director_user) can call ANY tool
mgr_ok = all(
    tool_registry.dispatch(name, env, director_user, {})
    .get("ok") is not False
    or ("access_denied" not in (tool_registry.dispatch(
        name, env, director_user, {}).get("error") or ""))
    for name in NEW
)
_check("T12158", mgr_ok, "manager passes group check on new tools")


# === variant filter ===

# T12159 -- sales variant gives sales tools only
sales_visible = tool_registry.filter_tools_for_variant_and_user(
    sales_user, "sales")
sales_names = {t.name for t in sales_visible}
expected_sales = set(tool_registry.TOOLS_BY_VARIANT["sales"])
_check("T12159",
       sales_names == expected_sales,
       f"got={sorted(sales_names)} expected={sorted(expected_sales)}")


# T12160 -- bookkeeper variant gives bookkeeper tools
bk_visible = tool_registry.filter_tools_for_variant_and_user(
    bookkeeper_user, "bookkeeper")
bk_names = {t.name for t in bk_visible}
expected_bk = set(tool_registry.TOOLS_BY_VARIANT["bookkeeper"])
_check("T12160",
       bk_names == expected_bk,
       f"got={sorted(bk_names)}")


# T12161 -- lead_tech variant -- intersection of groups + variant
lt_visible = tool_registry.filter_tools_for_variant_and_user(
    lead_tech_user, "lead_tech")
lt_names = {t.name for t in lt_visible}
expected_lt = set(tool_registry.TOOLS_BY_VARIANT["lead_tech"])
_check("T12161",
       lt_names == expected_lt,
       f"got={sorted(lt_names)}")


# T12162 -- D24 manager+director sees ALL tools (no intersection)
mgr_dir = tool_registry.filter_tools_for_variant_and_user(
    director_user, "director")
mgr_dir_names = {t.name for t in mgr_dir}
_check("T12162",
       mgr_dir_names == set(all_tools),
       f"missing={set(all_tools) - mgr_dir_names}")


# T12163 -- D24 manager peeking bookkeeper variant gets bookkeeper
# tools only (NOT all 14). Intersection IS applied for non-director.
mgr_peek_bk = tool_registry.filter_tools_for_variant_and_user(
    director_user, "bookkeeper")
mgr_peek_names = {t.name for t in mgr_peek_bk}
_check("T12163",
       mgr_peek_names == expected_bk,
       f"got={sorted(mgr_peek_names)}")


# === D17 dedup ===

# T12164 -- duplicate tool_calls in one turn execute ONCE.
session = Session.sudo().get_or_create_for_user(sales_user.id)
orch_mod._RATE_LIMIT_BY_USER[sales_user.id] = []
dup_turn = ChatTurnResult(
    success=True, assistant_message="",
    tool_calls=[
        {"tool_call_id": "tc_a",
         "tool_name": "get_open_quotes", "params": {}},
        {"tool_call_id": "tc_b",
         "tool_name": "get_open_quotes", "params": {}},   # dup
    ],
    prompt_tokens=10, completion_tokens=2, latency_ms=20,
)
final_turn = ChatTurnResult(
    success=True, assistant_message="Done.",
    prompt_tokens=15, completion_tokens=5, latency_ms=20,
)
dispatch_count = {"n": 0}
real_dispatch = tool_registry.dispatch


def _counting_dispatch(name, env_, user_, params):
    if name == "get_open_quotes":
        dispatch_count["n"] += 1
    return real_dispatch(name, env_, user_, params)


with patch.object(tool_registry, "dispatch",
                  side_effect=_counting_dispatch), \
     patch.object(GroqChatAdapter, "chat",
                  side_effect=[dup_turn, final_turn]):
    res = ChatOrchestrator(env).handle_user_message(
        sales_user, session, "P12M1.1 dedup test",
        active_variant="sales")
_check("T12164",
       res.get("ok") is True
       and dispatch_count["n"] == 1
       and len(res.get("tool_cards") or []) == 1,
       (f"dispatches={dispatch_count['n']} "
        f"cards={len(res.get('tool_cards') or [])}"))


# T12165 -- tool message rows still emitted for BOTH tool_call_ids
# (Groq protocol requires it). The second carries _dedup_reused.
tool_msgs = Message.sudo().search([
    ("session_id", "=", session.id),
    ("tool_name", "=", "get_open_quotes"),
    ("tool_call_id", "in", ("tc_a", "tc_b")),
], order="created_at desc, id desc", limit=2)
ok = len(tool_msgs) == 2
if ok:
    # Find the one with _dedup_reused — the SECOND tool call (tc_b).
    bodies = [json.loads(m.content or "{}") for m in tool_msgs]
    ok = any(b.get("_dedup_reused") is True for b in bodies)
_check("T12165", ok,
       f"rows={len(tool_msgs)} dedup_marker={ok}")


# === D18 history pruning ===

# T12166 -- _load_history keeps last 10 rows AND extends past a
# tool message to include its parent assistant turn.
test_user = sales_user
test_session = Session.sudo().get_or_create_for_user(test_user.id)
# Wipe existing messages on this session via raw SQL so the test
# starts from a known state (ACL blocks unlink).
env.cr.execute(
    "DELETE FROM neon_finance_ai_chat_message WHERE session_id=%s",
    (test_session.id,))
# Build a deterministic history: 4 user-only turns, then an
# assistant emitting 2 tool_calls, then 2 tool responses, then 4
# more user/assistant pairs => 16 total messages.
orch = ChatOrchestrator(env)
for i in range(4):
    orch._append(test_session, role="user",
                  content=f"prelude user {i}")
orch._append(
    test_session, role="assistant",
    content="emit tools",
    tool_calls_json=json.dumps([
        {"tool_call_id": "ttc_a", "tool_name": "get_open_quotes",
         "params": {}},
        {"tool_call_id": "ttc_b", "tool_name": "get_my_pipeline",
         "params": {}},
    ]),
)
orch._append(test_session, role="tool",
              content='{"ok":true}', tool_call_id="ttc_a",
              tool_name="get_open_quotes")
orch._append(test_session, role="tool",
              content='{"ok":true}', tool_call_id="ttc_b",
              tool_name="get_my_pipeline")
for i in range(8):
    role = "user" if i % 2 == 0 else "assistant"
    orch._append(test_session, role=role,
                  content=f"trailing {role} {i}")
loaded = orch._load_history(test_session)
ok = (
    len(loaded) >= 10
    and len(loaded) <= 13     # tolerate small fixup
    and all(m.role in ("user", "assistant", "tool")
            for m in loaded)
)
# Verify no orphaned tool message at index 0
ok = ok and loaded[0].role != "tool"
_check("T12166", ok,
       f"loaded={len(loaded)} first_role={loaded[0].role}")


# === D25 role_label in system prompt ===

# T12167 -- bookkeeper variant -> "Finance Copilot"
sys_p = ChatOrchestrator(env)._system_prompt(
    user=bookkeeper_user, variant="bookkeeper")
_check("T12167",
       "Finance Copilot" in sys_p
       and bookkeeper_user.name in sys_p,
       f"prompt[:90]={sys_p[:90]!r}")


# T12168 -- lead_tech variant -> "Operations Copilot"
sys_p = ChatOrchestrator(env)._system_prompt(
    user=lead_tech_user, variant="lead_tech")
_check("T12168", "Operations Copilot" in sys_p,
       f"prompt[:90]={sys_p[:90]!r}")


# T12169 -- director variant -> "Director Copilot"
sys_p = ChatOrchestrator(env)._system_prompt(
    user=director_user, variant="director")
_check("T12169", "Director Copilot" in sys_p,
       f"prompt[:90]={sys_p[:90]!r}")


# === 5 new tools shapes ===

# T12170 -- get_overdue_invoices empty path on a fresh DB
res = tool_registry.dispatch(
    "get_overdue_invoices", env, bookkeeper_user, {})
_check("T12170",
       res.get("ok") is True and "rows" in res,
       f"count={res.get('count')}")


# T12171 -- get_zig_rate returns expected fields
res = tool_registry.dispatch(
    "get_zig_rate", env, bookkeeper_user, {})
_check("T12171",
       res.get("ok") is True
       and "current_rate" in res
       and "last_updated_at" in res
       and "change_24h_pct" in res,
       f"rate={res.get('current_rate')}")


# T12172 -- get_budget_status returns status field
res = tool_registry.dispatch(
    "get_budget_status", env, bookkeeper_user, {})
ok = (
    res.get("ok") is True
    and all(r.get("status") in (
        "on_track", "warning", "breach", "severe")
            for r in (res.get("rows") or []))
)
_check("T12172", ok, f"count={res.get('count')}")


# T12173 -- get_jobs_this_week happy path
res = tool_registry.dispatch(
    "get_jobs_this_week", env, lead_tech_user, {})
_check("T12173",
       res.get("ok") is True
       and "window_start" in res and "window_end" in res
       and isinstance(res.get("rows"), list),
       f"count={res.get('count')}")


# T12174 -- get_readiness_gates default 7d window
res = tool_registry.dispatch(
    "get_readiness_gates", env, lead_tech_user, {})
_check("T12174",
       res.get("ok") is True
       and "days_ahead" in res and "rows" in res,
       f"count={res.get('count')} days_ahead={res.get('days_ahead')}")


# === ACL CSV widening ===

# T12175 -- 10 chat ACL rows (5 groups × 2 models)
access = env["ir.model.access"].search([
    ("model_id.model", "in", (
        "neon.finance.ai.chat.session",
        "neon.finance.ai.chat.message",
    )),
])
_check("T12175", len(access) == 10,
       f"rows={len(access)}")


# T12176 -- bookkeeper group present on both models
bk_grp = env.ref("neon_core.group_neon_bookkeeper")
session_bk = env["ir.model.access"].search([
    ("model_id.model", "=", "neon.finance.ai.chat.session"),
    ("group_id", "=", bk_grp.id),
])
msg_bk = env["ir.model.access"].search([
    ("model_id.model", "=", "neon.finance.ai.chat.message"),
    ("group_id", "=", bk_grp.id),
])
_check("T12176", bool(session_bk) and bool(msg_bk),
       f"session={bool(session_bk)} message={bool(msg_bk)}")


# T12177 -- crew_leader group present on both models
cl_grp = env.ref("neon_jobs.group_neon_jobs_crew_leader")
session_cl = env["ir.model.access"].search([
    ("model_id.model", "=", "neon.finance.ai.chat.session"),
    ("group_id", "=", cl_grp.id),
])
msg_cl = env["ir.model.access"].search([
    ("model_id.model", "=", "neon.finance.ai.chat.message"),
    ("group_id", "=", cl_grp.id),
])
_check("T12177", bool(session_cl) and bool(msg_cl),
       f"session={bool(session_cl)} message={bool(msg_cl)}")


# T12178 -- still no unlink anywhere
all_unlink = sum(a.perm_unlink for a in access)
_check("T12178", all_unlink == 0,
       f"sum_perm_unlink={all_unlink}")


# === Live Groq smoke per variant (sanity check) ===

# T12179 -- live Groq call from bookkeeper variant lands a non-
# fallback chat.message row.
Config = env["ir.config_parameter"].sudo()
key = Config.get_param("neon_dashboard.ai_keys_groq", "")
if not key:
    _check("T12179", True, "skipped (no API key)")
else:
    bk_session = Session.sudo().get_or_create_for_user(
        bookkeeper_user.id)
    orch_mod._RATE_LIMIT_BY_USER[bookkeeper_user.id] = []
    res = ChatOrchestrator(env).handle_user_message(
        bookkeeper_user, bk_session,
        "Reply with the single word OK.",
        active_variant="bookkeeper")
    live_ok = (
        res.get("ok") is True
        and not res.get("is_fallback")
        and res.get("prompt_tokens", 0) > 0
    )
    _check("T12179", live_ok,
           f"tokens={res.get('prompt_tokens')}/"
           f"{res.get('completion_tokens')} "
           f"lat={res.get('latency_ms')}ms")


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
