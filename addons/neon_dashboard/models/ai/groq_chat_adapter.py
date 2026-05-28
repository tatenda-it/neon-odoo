# -*- coding: utf-8 -*-
"""Phase 12.1 — Groq chat adapter (tool-calling).

Sends multi-turn messages with tool schemas to the Groq
OpenAI-compatible /chat/completions endpoint. Llama 3.3 70B
supports the native ``tools`` parameter; on a tool-call turn the
response carries ``message.tool_calls`` we parse into the
ChatTurnResult.

⚠️ DECISION (M12.1, marker inline): a single chat() call is ONE
HTTP round-trip. The orchestrator's tool-call loop (up to 3
iterations) means we may call chat() three times for one user
turn. Each call carries the full message history (system + N
turns) so the model has full context across iterations. Same
15s timeout as M11.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from typing import List

import requests


_logger = logging.getLogger(__name__)


_TIMEOUT_SECONDS = 15
_HEALTH_TIMEOUT_SECONDS = 5


@dataclass
class ChatTurnResult:
    """One LLM chat() call's result. Either the assistant text
    landed in `assistant_message` (final answer), or one or more
    tool_calls fired which the orchestrator must dispatch and feed
    back."""
    success: bool
    assistant_message: str = ""
    tool_calls: List[dict] = field(default_factory=list)
    raw_response: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    is_fallback: bool = False
    error_message: str = ""


class GroqChatAdapter:
    """Stateless adapter; constructed with a provider record from
    neon.dashboard.ai.provider. Reuses the same row (and key) as
    M11's GroqAdapter — the provider is multi-use-case."""

    def __init__(self, provider_record):
        self.provider = provider_record

    def chat(self, messages, tools=None):
        """Send messages (list of {role, content[, tool_calls,
        tool_call_id, name]} dicts) plus optional tool schemas.

        Returns ChatTurnResult. NEVER raises -- the orchestrator
        relies on success=False / error_message to drive fallback.
        """
        start = time.time()
        try:
            api_key = self.provider._get_decrypted_api_key()
        except Exception as exc:  # noqa: BLE001
            return ChatTurnResult(
                success=False, is_fallback=True,
                error_message=f"API key lookup failed: {exc}",
                latency_ms=int((time.time() - start) * 1000),
            )
        if not api_key:
            return ChatTurnResult(
                success=False, is_fallback=True,
                error_message="Groq API key not configured.",
                latency_ms=int((time.time() - start) * 1000),
            )
        try:
            payload = {
                "model": self.provider.model_id,
                "messages": messages,
                "temperature": self.provider.temperature,
                "max_tokens": self.provider.max_tokens,
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
            response = requests.post(
                self.provider.endpoint_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content") or ""
            tool_calls_raw = message.get("tool_calls") or []
            usage = data.get("usage") or {}
            parsed_tool_calls = []
            for tc in tool_calls_raw:
                fn = tc.get("function") or {}
                args_raw = fn.get("arguments") or "{}"
                try:
                    params = json.loads(args_raw) if isinstance(
                        args_raw, str) else args_raw
                except json.JSONDecodeError:
                    params = {}
                parsed_tool_calls.append({
                    "tool_call_id": tc.get("id") or "",
                    "tool_name": fn.get("name") or "",
                    "params": params if isinstance(params, dict) else {},
                })
            return ChatTurnResult(
                success=True,
                assistant_message=content,
                tool_calls=parsed_tool_calls,
                raw_response=json.dumps(message),
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                latency_ms=int((time.time() - start) * 1000),
            )
        except requests.exceptions.Timeout:
            return ChatTurnResult(
                success=False, is_fallback=True,
                error_message=(
                    f"Groq request timed out (>{_TIMEOUT_SECONDS}s)."),
                latency_ms=int((time.time() - start) * 1000),
            )
        except requests.exceptions.RequestException as exc:
            return ChatTurnResult(
                success=False, is_fallback=True,
                error_message=f"Groq HTTP error: {exc}",
                latency_ms=int((time.time() - start) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            return ChatTurnResult(
                success=False, is_fallback=True,
                error_message=f"Groq adapter error: {exc}",
                latency_ms=int((time.time() - start) * 1000),
            )

    def health_check(self):
        try:
            api_key = self.provider._get_decrypted_api_key()
        except Exception:  # noqa: BLE001
            return False
        if not api_key:
            return False
        try:
            response = requests.post(
                self.provider.endpoint_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.provider.model_id,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5,
                },
                timeout=_HEALTH_TIMEOUT_SECONDS,
            )
            return bool(response.ok)
        except Exception:  # noqa: BLE001
            return False
