# -*- coding: utf-8 -*-
"""Phase 12.1 / 12.1.1 — Chat orchestrator.

Drives the multi-turn LLM<->tool-call loop. Persists every turn to
neon.finance.ai.chat.message as an audit log.

⚠️ DECISION (M12.1, marker inline): rate limit lives at module
scope as an in-memory dict keyed on user_id. 30 req / hour / user.
Sliding 1-hour window via timestamp list per user.

⚠️ DECISION (M12.1, marker inline): max 3 tool-call iterations
per user turn. After the 3rd iteration we return the partial
output with a guardrail message.

⚠️ DECISION (M12.1.1, D17): tool-call deduplication within one
user turn. A duplicate (tool_name + normalised params) reuses the
prior result instead of re-running + re-rendering.

⚠️ DECISION (M12.1.1, D18): history pruning counts ALL message
roles (user / assistant / tool), but never splits an assistant
tool-emit from its matching tool responses. Walk backwards from
the end; if the cutoff lands mid-pairing, extend back to the
preceding assistant turn.

⚠️ DECISION (M12.1.1, D24): tool advertisement intersects user
groups with the variant's TOOLS_BY_VARIANT set. Manager+director
sees all tools (no intersection).

⚠️ DECISION (M12.1.1, D25): role_label in system prompt derives
from the active variant, not the user's primary group. Director
peeking Bookkeeper variant gets "Finance Copilot" framing.
"""
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

from odoo import fields

from .groq_chat_adapter import GroqChatAdapter, ChatTurnResult
from . import tool_registry


_logger = logging.getLogger(__name__)


_RATE_LIMIT_PER_HOUR = 30
_RATE_LIMIT_WINDOW_SECONDS = 3600
_RATE_LIMIT_BY_USER: dict = defaultdict(list)

_MAX_TOOL_ITERATIONS = 3
# D18 — count ALL message rows, not just user+assistant turns.
_HISTORY_MESSAGE_LIMIT = 10

# D25 — variant → "Copilot" role label mapping.
_ROLE_LABELS = {
    "director": "Director",
    "sales": "Sales",
    "bookkeeper": "Finance",
    "lead_tech": "Operations",
}

_DEFAULT_SYSTEM_PROMPT = (
    "You are the Neon Events {role_label} Copilot. You help "
    "{user_name} at Neon Events Elements (event production "
    "company in Harare, Zimbabwe). Their role is {role_label}. "
    "You have tools relevant to their work -- never suggest "
    "actions outside this role. Use tools to answer factual "
    "questions -- never guess or invent numbers, dates, or "
    "names. When you don't have a tool, say so. Keep responses "
    "concise (2-3 sentences max unless asked for detail). "
    "Currency: USD or ZiG (Zimbabwe Gold). VAT: 15%. Today's "
    "date is {today_date}."
)

_SYSTEM_PROMPT_CONFIG_KEY = "neon_finance.ai_chat_system_prompt"


@dataclass
class OrchestratorResponse:
    success: bool
    assistant_message: str = ""
    tool_cards: List[dict] = field(default_factory=list)
    is_fallback: bool = False
    error_message: str = ""
    provider_key: str = ""
    model_version: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0

    def to_dict(self):
        return {
            "ok": self.success,
            "assistant_message": self.assistant_message,
            "tool_cards": self.tool_cards,
            "is_fallback": self.is_fallback,
            "error_message": self.error_message,
            "provider_key": self.provider_key,
            "model_version": self.model_version,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_ms": self.latency_ms,
        }


def _check_rate_limit(user_id):
    now = time.time()
    bucket = _RATE_LIMIT_BY_USER[user_id]
    fresh = [t for t in bucket
             if now - t < _RATE_LIMIT_WINDOW_SECONDS]
    _RATE_LIMIT_BY_USER[user_id] = fresh
    if len(fresh) >= _RATE_LIMIT_PER_HOUR:
        return False
    fresh.append(now)
    return True


def _dedup_key(tool_name, params):
    """Stable canonical key for D17 dedup. Sort dict keys, coerce
    string values to lowercase, leave numerics/dates alone."""
    canonical = []
    for k in sorted((params or {}).keys()):
        v = (params or {})[k]
        if isinstance(v, str):
            canonical.append((k, v.strip().lower()))
        elif isinstance(v, (int, float, bool)) or v is None:
            canonical.append((k, v))
        else:
            canonical.append((k, json.dumps(v, sort_keys=True,
                                              default=str)))
    return (tool_name, tuple(canonical))


class ChatOrchestrator:
    """One instance per request. Persists messages, calls the
    adapter, loops on tool calls."""

    def __init__(self, env):
        self.env = env
        self.Message = env["neon.finance.ai.chat.message"].sudo()

    # ==============================================================
    # Public entry
    # ==============================================================
    def handle_user_message(self, user, session, text,
                             active_variant=None):
        """Append the user turn, call the LLM, dispatch tools,
        persist intermediate turns, return the final response.

        ``active_variant`` is the dashboard variant the user is
        currently looking at — drives tool advertisement (D24) and
        the system prompt's role label (D25).
        """
        if not _check_rate_limit(user.id):
            return OrchestratorResponse(
                success=False, is_fallback=True,
                assistant_message=(
                    "Slow down -- you've hit 30 messages this hour. "
                    "Try again in a few minutes."),
                error_message="rate_limit_exceeded",
            ).to_dict()

        self._append(session, role="user", content=text or "")

        provider = self._active_provider()
        if not provider:
            msg = (
                "AI provider not configured. Ask an administrator "
                "to set the Groq key in Settings -> Neon -> AI "
                "Insights.")
            self._append(session, role="assistant", content=msg,
                         is_fallback=True,
                         error_message="no_active_provider")
            return OrchestratorResponse(
                success=False, is_fallback=True,
                assistant_message=msg,
                error_message="no_active_provider",
            ).to_dict()

        adapter = GroqChatAdapter(provider)
        history = self._load_history(session)
        messages = self._build_messages(
            history, text, user=user, variant=active_variant)
        # D24 — variant ∩ groups filter for the tool schemas the
        # LLM sees this turn. dispatch() also enforces the group
        # filter defensively.
        tools = tool_registry.filter_tools_for_variant_and_user(
            user, active_variant, category="read")
        tools_schema = tool_registry.groq_tool_schemas(tools=tools)

        tool_cards: List[dict] = []
        # D17 — dedup cache per user turn. Key: (tool_name, params).
        dedup_cache: dict = {}
        last_result: Optional[ChatTurnResult] = None
        total_prompt = 0
        total_completion = 0
        total_latency = 0

        for iteration in range(_MAX_TOOL_ITERATIONS):
            result = adapter.chat(messages, tools=tools_schema)
            last_result = result
            total_prompt += result.prompt_tokens
            total_completion += result.completion_tokens
            total_latency += result.latency_ms

            if not result.success:
                msg = result.error_message or "Chat failed."
                # D18 — log diagnostic metrics on 4xx-class errors
                # (payload size + message count) so we can tune the
                # history limit if Groq starts rejecting again.
                diag = (
                    f"messages_sent={len(messages)} "
                    f"payload_chars={len(json.dumps(messages, default=str))}"
                )
                self._append(
                    session, role="assistant",
                    content=msg, is_fallback=True,
                    error_message=f"{msg} | {diag}",
                    provider_key=provider.provider_key,
                    model_version=provider.model_id,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    latency_ms=result.latency_ms,
                    # P12.M1.1.1 — capture the outgoing payload
                    # for forensic inspection. Adapter already
                    # truncated to 10k chars.
                    request_body_snapshot=result.request_body_snapshot,
                )
                return OrchestratorResponse(
                    success=False, is_fallback=True,
                    assistant_message=(
                        "Sorry -- I can't reach the AI service "
                        "right now. " + msg),
                    error_message=msg,
                    provider_key=provider.provider_key,
                    model_version=provider.model_id,
                    prompt_tokens=total_prompt,
                    completion_tokens=total_completion,
                    latency_ms=total_latency,
                ).to_dict()

            # Persist this assistant turn.
            self._append(
                session,
                role="assistant",
                content=result.assistant_message or "",
                tool_calls_json=(
                    json.dumps(result.tool_calls)
                    if result.tool_calls else ""),
                provider_key=provider.provider_key,
                model_version=provider.model_id,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                latency_ms=result.latency_ms,
            )

            if not result.tool_calls:
                return OrchestratorResponse(
                    success=True,
                    assistant_message=result.assistant_message or "",
                    tool_cards=tool_cards,
                    provider_key=provider.provider_key,
                    model_version=provider.model_id,
                    prompt_tokens=total_prompt,
                    completion_tokens=total_completion,
                    latency_ms=total_latency,
                ).to_dict()

            messages.append({
                "role": "assistant",
                "content": result.assistant_message or "",
                "tool_calls": [
                    {
                        "id": tc["tool_call_id"],
                        "type": "function",
                        "function": {
                            "name": tc["tool_name"],
                            "arguments": json.dumps(tc["params"]),
                        },
                    } for tc in result.tool_calls
                ],
            })

            # Dispatch each tool call with D17 dedup.
            for tc in result.tool_calls:
                key = _dedup_key(tc["tool_name"], tc["params"])
                cached = dedup_cache.get(key)
                if cached is not None:
                    # D17 — Groq re-emitted an identical call. Reuse
                    # the prior result without dispatching again
                    # AND without pushing a second tool_card. The
                    # tool-role message in `messages` still needs to
                    # be present (Groq protocol requires one tool
                    # response per tool_call_id).
                    tool_result = cached
                    # Annotate so audit log can see this was a dedup
                    # reuse rather than a fresh tool execution.
                    tool_result_for_msg = dict(tool_result)
                    tool_result_for_msg["_dedup_reused"] = True
                else:
                    tool_result = tool_registry.dispatch(
                        tc["tool_name"], self.env, user,
                        tc["params"])
                    dedup_cache[key] = tool_result
                    tool_cards.append({
                        "tool": tc["tool_name"],
                        "tool_call_id": tc["tool_call_id"],
                        "params": tc["params"],
                        "result": tool_result,
                    })
                    tool_result_for_msg = tool_result
                self._append(
                    session,
                    role="tool",
                    content=json.dumps(tool_result_for_msg),
                    tool_call_id=tc["tool_call_id"],
                    tool_name=tc["tool_name"],
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["tool_call_id"],
                    "name": tc["tool_name"],
                    "content": json.dumps(tool_result_for_msg),
                })

        # Loop exhausted -- graceful exit message.
        guard_msg = (
            "I've gathered some information but need your guidance "
            "to proceed.")
        self._append(
            session, role="assistant", content=guard_msg,
            is_fallback=True,
            error_message="tool_loop_exhausted",
            provider_key=provider.provider_key,
            model_version=provider.model_id,
        )
        return OrchestratorResponse(
            success=True,
            assistant_message=guard_msg,
            tool_cards=tool_cards,
            is_fallback=True,
            provider_key=provider.provider_key,
            model_version=provider.model_id,
            prompt_tokens=total_prompt,
            completion_tokens=total_completion,
            latency_ms=total_latency,
            error_message="tool_loop_exhausted",
        ).to_dict()

    # ==============================================================
    # Helpers
    # ==============================================================
    def _active_provider(self):
        return self.env["neon.dashboard.ai.provider"].sudo().search([
            ("is_default", "=", True),
            ("is_enabled", "=", True),
            ("provider_key", "=", "groq"),
        ], limit=1)

    def _load_history(self, session):
        """D18: count ALL message rows (user / assistant / tool),
        keep the last _HISTORY_MESSAGE_LIMIT, never split an
        assistant turn from its tool replies. Returns rows in
        chronological order (oldest first)."""
        # Fetch ALL non-system messages oldest-first; the slice +
        # tool-pairing fixup happens in memory below.
        rows = self.Message.search(
            [("session_id", "=", session.id),
             ("role", "!=", "system")],
            order="created_at, id",
        )
        if len(rows) <= _HISTORY_MESSAGE_LIMIT:
            return rows
        # Take the last N rows; then walk backwards to find a safe
        # cutoff that doesn't strand a tool message from its
        # parent assistant turn.
        cut_index = len(rows) - _HISTORY_MESSAGE_LIMIT
        # If rows[cut_index] is a tool-role message, we need to
        # back the cut up to the assistant turn that emitted it.
        while (cut_index > 0
               and rows[cut_index].role == "tool"):
            cut_index -= 1
        # If the new cut points AT an assistant turn carrying
        # tool_calls, include that assistant turn (the loop above
        # left us pointing at the assistant). If by chance it is
        # an assistant with NO tool_calls, that's fine — still
        # include it.
        return rows[cut_index:]

    def _build_messages(self, history, latest_user_text,
                         user=None, variant=None):
        sys_prompt = self._system_prompt(user=user, variant=variant)
        messages = [{"role": "system", "content": sys_prompt}]
        for m in history:
            if m.role == "user":
                messages.append({"role": "user",
                                  "content": m.content or ""})
            elif m.role == "assistant":
                msg = {"role": "assistant",
                       "content": m.content or ""}
                if m.tool_calls_json:
                    try:
                        calls = json.loads(m.tool_calls_json)
                        msg["tool_calls"] = [
                            {
                                "id": c["tool_call_id"],
                                "type": "function",
                                "function": {
                                    "name": c["tool_name"],
                                    "arguments": json.dumps(
                                        c.get("params", {})),
                                },
                            } for c in calls
                        ]
                    except (json.JSONDecodeError, KeyError):
                        pass
                messages.append(msg)
            elif m.role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or "",
                    "name": m.tool_name or "",
                    "content": m.content or "",
                })
        # Ensure the just-appended user turn is the trailing entry.
        if not (messages and messages[-1].get("role") == "user"
                and (messages[-1].get("content") or "")
                == (latest_user_text or "")):
            messages.append({"role": "user",
                             "content": latest_user_text or ""})
        return messages

    def _system_prompt(self, user=None, variant=None):
        Config = self.env["ir.config_parameter"].sudo()
        template = (Config.get_param(_SYSTEM_PROMPT_CONFIG_KEY, "")
                    or _DEFAULT_SYSTEM_PROMPT)
        today = fields.Date.context_today(
            self.env["res.users"].browse(self.env.uid))
        role_label = _ROLE_LABELS.get(
            (variant or "director").lower(), "Sales")
        user_name = (user.name if user else
                      self.env.user.name) or ""
        return (template
                .replace("{today_date}", today.isoformat())
                .replace("{role_label}", role_label)
                .replace("{user_name}", user_name))

    def _append(self, session, role, content="", **kw):
        vals = {
            "session_id": session.id,
            "role": role,
            "content": content,
        }
        for k in ("tool_calls_json", "tool_call_id", "tool_name",
                  "provider_key", "model_version", "prompt_tokens",
                  "completion_tokens", "latency_ms", "is_fallback",
                  "error_message", "request_body_snapshot"):
            if k in kw and kw[k] is not None:
                vals[k] = kw[k]
        msg = self.Message.create(vals)
        session.touch()
        return msg
