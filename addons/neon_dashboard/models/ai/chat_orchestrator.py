# -*- coding: utf-8 -*-
"""Phase 12.1 — Chat orchestrator.

Drives the multi-turn LLM<->tool-call loop. Persists every turn to
neon.finance.ai.chat.message as an audit log.

⚠️ DECISION (M12.1, marker inline): rate limit lives at module
scope as an in-memory dict keyed on user_id. Same pattern as M11's
manual-refresh rate limit. Restart clears it (acceptable; a chat
user who hits the cap can retry after process restart, and the dict
re-populates organically). 30 req / hour / user. Sliding 1-hour
window via timestamp list per user.

⚠️ DECISION (M12.1, marker inline): max 3 tool-call iterations
per user turn. After the 3rd iteration we return the partial
output with a guardrail message. Prevents runaway loops where the
model keeps requesting tool calls.
"""
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

from odoo import _, fields

from .groq_chat_adapter import GroqChatAdapter, ChatTurnResult
from . import tool_registry


_logger = logging.getLogger(__name__)


_RATE_LIMIT_PER_HOUR = 30
_RATE_LIMIT_WINDOW_SECONDS = 3600
_RATE_LIMIT_BY_USER: dict = defaultdict(list)

_MAX_TOOL_ITERATIONS = 3
_HISTORY_TURN_LIMIT = 10

_DEFAULT_SYSTEM_PROMPT = (
    "You are the Neon Events Sales Copilot. You help sales reps "
    "at Neon Events Elements (event production company in Harare, "
    "Zimbabwe) with their quotes, leads, stock, and crew. You have "
    "tools to read data. Use tools to answer factual questions -- "
    "never guess or invent numbers, dates, or names. When you "
    "don't have a tool for something, say so. Keep responses "
    "concise (2-3 sentences max unless asked for detail). Currency "
    "is USD or ZiG (Zimbabwe Gold). VAT is 15%. Today's date is "
    "{today_date}."
)

_SYSTEM_PROMPT_CONFIG_KEY = "neon_finance.ai_chat_system_prompt"


@dataclass
class OrchestratorResponse:
    """Wraps everything the controller needs to return to the
    OWL UI: the final assistant text, the structured tool result
    cards, and meta (provider, tokens, latency, fallback)."""
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
    # Drop timestamps outside the window.
    fresh = [t for t in bucket
             if now - t < _RATE_LIMIT_WINDOW_SECONDS]
    _RATE_LIMIT_BY_USER[user_id] = fresh
    if len(fresh) >= _RATE_LIMIT_PER_HOUR:
        return False
    fresh.append(now)
    return True


class ChatOrchestrator:
    """One instance per request. Persists messages, calls the
    adapter, loops on tool calls."""

    def __init__(self, env):
        self.env = env
        self.Message = env["neon.finance.ai.chat.message"].sudo()

    # ==============================================================
    # Public entry
    # ==============================================================
    def handle_user_message(self, user, session, text):
        """Append the user turn, call the LLM, dispatch tools,
        persist intermediate turns, return the final response."""
        if not _check_rate_limit(user.id):
            return OrchestratorResponse(
                success=False, is_fallback=True,
                assistant_message=(
                    "Slow down -- you've hit 30 messages this hour. "
                    "Try again in a few minutes."),
                error_message="rate_limit_exceeded",
            ).to_dict()

        # Persist the user turn.
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
        messages = self._build_messages(history, text)
        tools_schema = tool_registry.groq_tool_schemas(category="read")

        tool_cards: List[dict] = []
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
                self._append(
                    session, role="assistant",
                    content=msg, is_fallback=True,
                    error_message=msg,
                    provider_key=provider.provider_key,
                    model_version=provider.model_id,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    latency_ms=result.latency_ms,
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

            # Persist this assistant turn (content may be empty if
            # the model only emitted tool_calls).
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
                # Done — model produced a final assistant answer.
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

            # Append the assistant tool_calls turn to the message
            # array Groq sees on the next call. OpenAI/Groq format
            # requires the original assistant message + each tool
            # response keyed by tool_call_id.
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

            # Dispatch each tool call.
            for tc in result.tool_calls:
                tool_result = tool_registry.dispatch(
                    tc["tool_name"], self.env, user, tc["params"])
                tool_cards.append({
                    "tool": tc["tool_name"],
                    "tool_call_id": tc["tool_call_id"],
                    "params": tc["params"],
                    "result": tool_result,
                })
                # Persist + feed back into messages.
                self._append(
                    session,
                    role="tool",
                    content=json.dumps(tool_result),
                    tool_call_id=tc["tool_call_id"],
                    tool_name=tc["tool_name"],
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["tool_call_id"],
                    "name": tc["tool_name"],
                    "content": json.dumps(tool_result),
                })

        # If we exit the loop without a tool-call-free response,
        # the model is iterating. Return graceful fallback.
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
        """Last N (user/assistant/tool) turns ordered oldest-first.
        Excludes the system message (we re-inject it) and the just-
        appended user turn (we re-inject that as the trailing
        message in _build_messages)."""
        return self.Message.search(
            [("session_id", "=", session.id),
             ("role", "!=", "system")],
            order="created_at desc, id desc",
            limit=_HISTORY_TURN_LIMIT,
        ).sorted("created_at")

    def _build_messages(self, history, latest_user_text):
        sys_prompt = self._system_prompt()
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
        # The just-appended user turn is in the history; if the
        # last entry is NOT the user turn (race-y on rare cases),
        # append explicitly.
        if not (messages and messages[-1].get("role") == "user"
                and (messages[-1].get("content") or "")
                == (latest_user_text or "")):
            messages.append({"role": "user",
                             "content": latest_user_text or ""})
        return messages

    def _system_prompt(self):
        Config = self.env["ir.config_parameter"].sudo()
        template = (Config.get_param(_SYSTEM_PROMPT_CONFIG_KEY, "")
                    or _DEFAULT_SYSTEM_PROMPT)
        today = fields.Date.context_today(
            self.env["res.users"].browse(self.env.uid))
        return template.replace("{today_date}", today.isoformat())

    def _append(self, session, role, content="", **kw):
        vals = {
            "session_id": session.id,
            "role": role,
            "content": content,
        }
        # Pass-through optional fields.
        for k in ("tool_calls_json", "tool_call_id", "tool_name",
                  "provider_key", "model_version", "prompt_tokens",
                  "completion_tokens", "latency_ms", "is_fallback",
                  "error_message"):
            if k in kw and kw[k] is not None:
                vals[k] = kw[k]
        msg = self.Message.create(vals)
        session.touch()
        return msg
