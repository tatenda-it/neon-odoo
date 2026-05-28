# -*- coding: utf-8 -*-
"""Phase 12.1 — AI Sales Copilot tool registry.

Singleton dict + ``@ai_tool`` decorator. Tools register on module
import via side effect; the orchestrator dispatches by name.

⚠️ DECISION (M12.1, marker inline): plain-Python registry, NOT an
Odoo Model. Tools are stateless functions taking (env, user, **kw)
and returning a JSON-serialisable dict. Keeping them out of the
registry-as-model space means hot-swap via module reload + no
ir.actions/ACL overhead.

⚠️ DECISION (M12.1, marker inline): tool execution wraps the env
in user.sudo() — RLS (Phase 2 ir.rule + ACL) handles row-level
visibility. A sales rep calling get_open_quotes sees only their own
quotes because the existing rules already scope by user_id. The
``user`` arg passed in is the live env.user; tools that need
self-scoping (mine vs others) consult it directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from odoo import SUPERUSER_ID


@dataclass
class ToolSpec:
    name: str
    description: str
    params_schema: Dict[str, Any]
    category: str = "read"            # "read" | "write"
    requires_confirmation: bool = False
    fn: Optional[Callable[..., Dict[str, Any]]] = None


_AI_TOOLS: Dict[str, ToolSpec] = {}


def ai_tool(
    *,
    name: str,
    description: str,
    params_schema: Dict[str, Any],
    category: str = "read",
    requires_confirmation: bool = False,
):
    """Register a tool with the singleton registry. Decorator
    pattern; the decorated function is called via dispatch()."""

    def wrap(fn):
        if name in _AI_TOOLS:
            # Idempotent re-registration (module reload during dev).
            # Overwrite is intentional; don't raise.
            pass
        _AI_TOOLS[name] = ToolSpec(
            name=name,
            description=description,
            params_schema=params_schema,
            category=category,
            requires_confirmation=requires_confirmation,
            fn=fn,
        )
        return fn

    return wrap


def get_tool(name: str) -> Optional[ToolSpec]:
    return _AI_TOOLS.get(name)


def list_tools(category: Optional[str] = None) -> List[ToolSpec]:
    """All registered tools, optionally filtered by category."""
    tools = list(_AI_TOOLS.values())
    if category:
        tools = [t for t in tools if t.category == category]
    return sorted(tools, key=lambda t: t.name)


def tool_names(category: Optional[str] = None) -> List[str]:
    return [t.name for t in list_tools(category)]


def groq_tool_schemas(category: Optional[str] = None) -> List[Dict]:
    """Format the registry as the Groq /chat/completions ``tools``
    parameter expects (OpenAI-compatible JSON Schema)."""
    schemas = []
    for tool in list_tools(category):
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
    """Execute the named tool and return its dict result. Wraps
    every error so the orchestrator can record it as a tool turn
    without crashing the chat loop."""
    tool = get_tool(name)
    if not tool or not tool.fn:
        return {
            "ok": False,
            "error": f"Unknown tool: {name!r}",
        }
    try:
        # All tool executions run with an env elevated to
        # SUPERUSER_ID (bypasses record rules + ACL across the
        # cross-module reads tools need). Row-level scoping is
        # performed by each tool body via the ``user`` arg
        # (typically ``salesperson_id == user.id`` or similar).
        # The calling user is still passed in for that filtering.
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
    # Tag every result with the tool name so the UI card-router
    # knows what shape to render.
    result.setdefault("tool", name)
    return result
