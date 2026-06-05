# -*- coding: utf-8 -*-
"""B11 / WA-0 -- Google Gemini chat adapter (tool-calling).

Mirrors GroqChatAdapter's contract -- same `.chat(messages, tools)
-> ChatTurnResult` and `.health_check()` -- so any consumer (the WA-0
WhatsApp rails) can swap providers via the catalog without caring which
one runs. It is a REAL adapter, not a config alias: Gemini's
generateContent shape differs from Groq's OpenAI-compatible /chat/
completions, so this class translates both directions.

⚠️ DECISION (WA-0): reuses GroqChatAdapter.ChatTurnResult as the single
result type (one shape for the orchestration loop regardless of vendor).
Does NOT inherit the insight BaseAdapter (that ABC is insight-shaped and
lives in neon_dashboard); chat adapters are standalone in core.

Translation map (OpenAI-style messages  ->  Gemini generateContent):
  system            -> systemInstruction.parts[].text (concatenated)
  user              -> contents[] role=user,  parts=[{text}]
  assistant (text)  -> contents[] role=model, parts=[{text}]
  assistant + calls -> contents[] role=model, parts=[{functionCall}]
  tool (result)     -> contents[] role=user,  parts=[{functionResponse}]
  tools schema      -> tools[].functionDeclarations[] (Groq .function)
Response candidates[].content.parts[].functionCall {name,args} ->
  ChatTurnResult.tool_calls [{tool_call_id, tool_name, params}].

Key in ir.config_parameter neon_dashboard.ai_keys_google (via the
provider's _get_decrypted_api_key); sent as the x-goog-api-key header
(never in the URL/query, so it stays out of logs). Endpoint base on the
provider row; the model + ':generateContent' are appended here.
"""
import json
import logging
import time
from typing import List

import requests

from .groq_chat_adapter import ChatTurnResult, _snapshot_request


_logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15
_HEALTH_TIMEOUT_SECONDS = 5


def _to_gemini_tools(tools):
    """Groq tool schemas -> Gemini tools[].functionDeclarations[].

    groq_tool_schemas() emits {"type":"function","function":{name,
    description,parameters}}. Gemini wants the inner ``function`` dict
    under a single tools[0].functionDeclarations list."""
    if not tools:
        return None
    decls = []
    for t in tools:
        fn = t.get("function") if isinstance(t, dict) else None
        if fn:
            decls.append({
                "name": fn.get("name"),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object"}),
            })
    return [{"functionDeclarations": decls}] if decls else None


def _to_gemini_contents(messages):
    """OpenAI-style messages -> (system_text, contents[]).

    System turns are concatenated into systemInstruction; everything
    else becomes a contents[] entry with the right role + part kind."""
    system_chunks = []
    contents = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            if m.get("content"):
                system_chunks.append(m["content"])
        elif role == "user":
            contents.append(
                {"role": "user", "parts": [{"text": m.get("content") or ""}]})
        elif role == "assistant":
            tcs = m.get("tool_calls") or []
            if tcs:
                parts = []
                for tc in tcs:
                    fn = tc.get("function") or {}
                    args_raw = fn.get("arguments") or "{}"
                    try:
                        args = (json.loads(args_raw)
                                if isinstance(args_raw, str) else args_raw)
                    except json.JSONDecodeError:
                        args = {}
                    parts.append({"functionCall": {
                        "name": fn.get("name") or "",
                        "args": args if isinstance(args, dict) else {},
                    }})
                contents.append({"role": "model", "parts": parts})
            else:
                contents.append(
                    {"role": "model",
                     "parts": [{"text": m.get("content") or ""}]})
        elif role == "tool":
            # Gemini carries tool results as a functionResponse part in a
            # user-role content; matched back to the call by ``name``.
            try:
                payload = json.loads(m.get("content") or "{}")
            except json.JSONDecodeError:
                payload = {"result": m.get("content") or ""}
            contents.append({"role": "user", "parts": [{"functionResponse": {
                "name": m.get("name") or "",
                "response": payload if isinstance(payload, dict)
                else {"result": payload},
            }}]})
    system_text = "\n\n".join(system_chunks).strip()
    return system_text, contents


class GeminiChatAdapter:
    """Stateless adapter; constructed with a neon.dashboard.ai.provider
    record whose provider_key == 'google'. Same surface as
    GroqChatAdapter so get_chat_adapter() can return either."""

    def __init__(self, provider_record):
        self.provider = provider_record

    def _endpoint(self, action="generateContent"):
        base = (self.provider.endpoint_url or "").rstrip("/")
        model = self.provider.model_id or "gemini-2.5-flash"
        return f"{base}/models/{model}:{action}"

    def chat(self, messages, tools=None):
        """One generateContent round-trip. NEVER raises -- returns
        ChatTurnResult(success=False, ...) on any failure."""
        start = time.time()
        try:
            api_key = self.provider._get_decrypted_api_key()
        except Exception as exc:  # noqa: BLE001
            return ChatTurnResult(
                success=False, is_fallback=True,
                error_message=f"Gemini API key lookup failed: {exc}",
                latency_ms=int((time.time() - start) * 1000))
        if not api_key:
            return ChatTurnResult(
                success=False, is_fallback=True,
                error_message="Gemini API key not configured.",
                latency_ms=int((time.time() - start) * 1000))
        system_text, contents = _to_gemini_contents(messages)
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.provider.temperature,
                "maxOutputTokens": self.provider.max_tokens or 800,
            },
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}
        gem_tools = _to_gemini_tools(tools)
        if gem_tools:
            payload["tools"] = gem_tools
            payload["toolConfig"] = {
                "functionCallingConfig": {"mode": "AUTO"}}
        try:
            response = requests.post(
                self._endpoint(),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
                json=payload,
                timeout=_TIMEOUT_SECONDS,
            )
            if not response.ok:
                err = ""
                try:
                    err = (response.json() if response.content
                           else {}).get("error", {})
                except Exception:  # noqa: BLE001
                    err = (response.text or "")[:1000]
                return ChatTurnResult(
                    success=False, is_fallback=True,
                    error_message=(
                        f"Gemini HTTP {response.status_code}: {err}"),
                    request_body_snapshot=_snapshot_request(payload),
                    latency_ms=int((time.time() - start) * 1000))
            data = response.json()
            candidates = data.get("candidates") or [{}]
            parts = (((candidates[0] or {}).get("content") or {})
                     .get("parts") or [])
            text_chunks = []
            parsed_tool_calls = []
            for i, part in enumerate(parts):
                if "text" in part:
                    text_chunks.append(part.get("text") or "")
                elif "functionCall" in part:
                    fc = part["functionCall"] or {}
                    args = fc.get("args") or {}
                    parsed_tool_calls.append({
                        # Gemini gives no call id; synthesise a stable one.
                        "tool_call_id": f"gem_{i}_{fc.get('name', '')}",
                        "tool_name": fc.get("name") or "",
                        "params": args if isinstance(args, dict) else {},
                    })
            usage = data.get("usageMetadata") or {}
            return ChatTurnResult(
                success=True,
                assistant_message="".join(text_chunks),
                tool_calls=parsed_tool_calls,
                raw_response=json.dumps(candidates[0] if candidates else {}),
                prompt_tokens=int(usage.get("promptTokenCount") or 0),
                completion_tokens=int(usage.get("candidatesTokenCount") or 0),
                latency_ms=int((time.time() - start) * 1000))
        except requests.exceptions.Timeout:
            return ChatTurnResult(
                success=False, is_fallback=True,
                error_message=f"Gemini request timed out (>{_TIMEOUT_SECONDS}s).",
                latency_ms=int((time.time() - start) * 1000))
        except requests.exceptions.RequestException as exc:
            return ChatTurnResult(
                success=False, is_fallback=True,
                error_message=f"Gemini HTTP error: {exc}",
                latency_ms=int((time.time() - start) * 1000))
        except Exception as exc:  # noqa: BLE001
            return ChatTurnResult(
                success=False, is_fallback=True,
                error_message=f"Gemini adapter error: {exc}",
                latency_ms=int((time.time() - start) * 1000))

    def health_check(self):
        try:
            api_key = self.provider._get_decrypted_api_key()
        except Exception:  # noqa: BLE001
            return False
        if not api_key:
            return False
        try:
            response = requests.post(
                self._endpoint(),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
                json={
                    "contents": [
                        {"role": "user", "parts": [{"text": "ping"}]}],
                    "generationConfig": {"maxOutputTokens": 5},
                },
                timeout=_HEALTH_TIMEOUT_SECONDS,
            )
            return bool(response.ok)
        except Exception:  # noqa: BLE001
            return False
