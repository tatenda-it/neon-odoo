# -*- coding: utf-8 -*-
"""Phase 12.1 / 12.1.1 — AI Sales Copilot tool registry.

Singleton dict + ``@ai_tool`` decorator + per-user group filter +
variant-scoped advertisement.

⚠️ DECISION (M12.1, marker inline): plain-Python registry, NOT an
Odoo Model. Tools are stateless functions taking (env, user, **kw)
and returning a JSON-serialisable dict.

⚠️ DECISION (M12.1, marker inline): tool execution elevates env
to SUPERUSER_ID so cross-module reads bypass row-level ACL; the
``user`` arg is passed through so tool bodies can scope by user_id.

⚠️ DECISION (M12.1.1, D23): every @ai_tool registers with a
``groups`` list. dispatch + schema generation filter against the
calling user's group membership; tools the user can't call are
never exposed to the LLM.

⚠️ DECISION (M12.1.1, D24): variant scope wins over group scope
for tool advertisement. A Director peeking the Bookkeeper variant
sees bookkeeper tools only, even though their group set permits
every tool. Exception: manager+director combo sees ALL tools.

⚠️ DECISION (M12.2, D28+D34): writes are two-phase. A category="write"
tool's @ai_tool-decorated function is the PROPOSE step (returns a
structured proposal, never mutates). The matching execute()
function is registered via register_executor(action_type, fn) and
called only by the /neon/ai_chat/confirm endpoint after the user
clicks Confirm in the UI card. dispatch() of a write tool returns
a result tagged is_proposal=True; the orchestrator persists it as
a pending action and ends the LLM turn there (no further iteration
on that tool_call).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from odoo import SUPERUSER_ID


# Manager tier — used in two places: the per-tool group check
# (manager is an automatic superset) and the variant-intersection
# exception (manager + director sees all tools).
_MANAGER_GROUP = "neon_jobs.group_neon_jobs_manager"


@dataclass
class ToolSpec:
    name: str
    description: str
    params_schema: Dict[str, Any]
    category: str = "read"            # "read" | "write"
    requires_confirmation: bool = False
    groups: List[str] = field(default_factory=list)
    fn: Optional[Callable[..., Dict[str, Any]]] = None


_AI_TOOLS: Dict[str, ToolSpec] = {}

# D28 — executor registry for write-category tools. The decorator
# binds the PROPOSE function; this dict binds the matching EXECUTE
# function. /neon/ai_chat/confirm dispatches the executor by
# action_type.
_AI_WRITE_EXECUTORS: Dict[str, Callable[..., Dict[str, Any]]] = {}


# ⚠️ DECISION (M12.1.1, D27): variant-scoped tool sets. Sentinel
# value "*" means "all registered tools" (director sees the union).
# The actual resolution happens in filter_tools_for_variant_and_user.
#
# ⚠️ DECISION (M12.2, D30): write tools layer on top of the read
# tool sets. log_lead / move_stage / update_deal_value sit on the
# sales surface; post_chatter_note is generic so it lands on every
# tier that has chat access.
TOOLS_BY_VARIANT: Dict[str, List[str]] = {
    "director": ["*"],
    "sales": [
        "get_open_quotes", "get_quote_details",
        "check_stock_availability", "get_crew_availability",
        "get_pending_deposits", "get_my_pipeline",
        "get_partner_history", "get_dashboard_summary",
        # L2.1 -- read-only client intelligence (commercial only; the
        # sensitive collections tool is NOT advertised to sales).
        "get_client_intel",
        # L2.2 -- read-only demand & seasonality (commercial, not sensitive).
        "get_demand_intel",
        # P12.M2 -- writes
        "log_lead", "move_stage", "update_deal_value",
        "post_chatter_note",
    ],
    "bookkeeper": [
        "get_overdue_invoices", "get_zig_rate",
        "get_budget_status", "get_pending_deposits",
        "get_open_quotes", "get_quote_details",
        "get_partner_history", "get_dashboard_summary",
        # L2.1 -- client intelligence incl. the sensitive collections tool.
        "get_client_intel", "get_client_outstanding",
        # L2.2 -- read-only demand & seasonality.
        "get_demand_intel",
        # P12.M2 -- writes (chatter note only on finance surface)
        "post_chatter_note",
    ],
    "lead_tech": [
        "get_jobs_this_week", "get_readiness_gates",
        "get_crew_availability", "get_cert_expiry",
        "check_stock_availability", "get_dashboard_summary",
        # P12.M2 -- writes (chatter note only on ops surface)
        "post_chatter_note",
    ],
}


def ai_tool(
    *,
    name: str,
    description: str,
    params_schema: Dict[str, Any],
    category: str = "read",
    requires_confirmation: bool = False,
    groups: Optional[Iterable[str]] = None,
):
    """Register a tool with the singleton registry. ``groups`` is
    the list of xmlids that grant permission to call this tool. A
    user who holds ANY of the listed groups (or the manager group
    by D23 superset rule) can invoke it."""

    def wrap(fn):
        _AI_TOOLS[name] = ToolSpec(
            name=name,
            description=description,
            params_schema=params_schema,
            category=category,
            requires_confirmation=requires_confirmation,
            groups=list(groups or []),
            fn=fn,
        )
        return fn

    return wrap


def get_tool(name: str) -> Optional[ToolSpec]:
    return _AI_TOOLS.get(name)


def register_executor(action_type: str, fn: Callable[..., Dict[str, Any]]):
    """Wire a write tool's EXECUTE function. Called from each
    write_tools/<tool>.py at import time. The action_type matches
    the proposal's action_type emitted by propose()."""
    _AI_WRITE_EXECUTORS[action_type] = fn


def get_executor(action_type: str
                 ) -> Optional[Callable[..., Dict[str, Any]]]:
    return _AI_WRITE_EXECUTORS.get(action_type)


def list_tools(category: Optional[str] = None) -> List[ToolSpec]:
    tools = list(_AI_TOOLS.values())
    if category:
        tools = [t for t in tools if t.category == category]
    return sorted(tools, key=lambda t: t.name)


def tool_names(category: Optional[str] = None) -> List[str]:
    return [t.name for t in list_tools(category)]


def user_can_call(user, tool: ToolSpec) -> bool:
    """True if ``user`` (res.users record) is entitled to call
    ``tool``. Manager group is automatic superset."""
    if not tool.groups:
        # Tool without explicit groups is open to any chat-eligible
        # user (defensive default for tools authored before the
        # groups field landed).
        return True
    try:
        if user.has_group(_MANAGER_GROUP):
            return True
    except Exception:  # noqa: BLE001
        pass
    for g in tool.groups:
        try:
            if user.has_group(g):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def filter_tools_for_variant_and_user(
    user, variant: Optional[str], category: Optional[str] = "read",
) -> List[ToolSpec]:
    """Resolution per D24:
    1. base = tools the user is entitled to (group filter)
    2. variant_set = TOOLS_BY_VARIANT[variant] (or all for director)
    3. result = base ∩ variant_set, EXCEPT manager+director keeps
       all (no intersection).

    ``category`` defaults to "read" for backward compat; pass None to
    include BOTH read + write tools (the orchestrator does this so
    the LLM sees write tools alongside reads on each turn).
    """
    base = [t for t in list_tools(category=category)
            if user_can_call(user, t)]
    variant = (variant or "director").lower()
    variant_list = TOOLS_BY_VARIANT.get(variant) or ["*"]
    # Manager + director exception — no intersection.
    try:
        is_manager = user.has_group(_MANAGER_GROUP)
    except Exception:  # noqa: BLE001
        is_manager = False
    if variant == "director" and is_manager:
        return base
    if "*" in variant_list:
        return base
    allowed = set(variant_list)
    return [t for t in base if t.name in allowed]


def groq_tool_schemas(
    tools: Optional[Iterable[ToolSpec]] = None,
    category: Optional[str] = None,
) -> List[Dict]:
    """Format the registry (or a filtered subset) as the Groq
    /chat/completions ``tools`` parameter expects."""
    if tools is None:
        tools = list_tools(category=category)
    schemas = []
    for tool in tools:
        schemas.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.params_schema,
            },
        })
    return schemas


def dispatch(name: str, env, user, params: Dict[str, Any]
             ) -> Dict[str, Any]:
    """Execute the named tool. Wraps every error so the
    orchestrator can record it as a tool turn without crashing
    the chat loop. Enforces the per-tool group ACL: if the user
    is not entitled to the tool, returns ok=False without running
    the body."""
    tool = get_tool(name)
    if not tool or not tool.fn:
        return {"ok": False, "error": f"Unknown tool: {name!r}"}
    if not user_can_call(user, tool):
        return {
            "ok": False,
            "error": ("access_denied: this tool is not available "
                      "for your role."),
            "tool": name,
        }
    try:
        sudo_env = env(user=SUPERUSER_ID)
        result = tool.fn(env=sudo_env, user=user, **(params or {}))
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    if not isinstance(result, dict):
        return {
            "ok": False,
            "error": (
                f"Tool {name} returned {type(result).__name__}, "
                "expected dict."
            ),
        }
    result.setdefault("tool", name)
    # D28/D34 — for write tools, surface is_proposal so the
    # orchestrator routes the result through pending_action.propose()
    # instead of feeding it back to the LLM.
    if tool.category == "write" and result.get("ok"):
        result.setdefault("is_proposal", True)
    return result
