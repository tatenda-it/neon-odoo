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

# WA-0 503-resilience: gemini-2.5-flash free-tier returns 503 "high
# demand" intermittently (200s land ms later). Retry these transient
# statuses with short backoff before giving up (the orchestrator then
# falls back to Groq if even the retries fail).
_RETRY_STATUSES = (429, 503)
_RETRY_BACKOFFS = (0.3, 0.8)  # seconds; len => number of retries


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

    def _fail(self, start, msg, snapshot=None):
        """Build a failure ChatTurnResult AND log it (WA-0: failures were
        previously invisible in the app log)."""
        _logger.warning("Gemini chat failed: %s", msg)
        return ChatTurnResult(
            success=False, is_fallback=True, error_message=msg,
            request_body_snapshot=(
                _snapshot_request(snapshot) if snapshot else ""),
            latency_ms=int((time.time() - start) * 1000))

    def _parse_ok(self, response, start):
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

    def chat(self, messages, tools=None, temperature=None, model=None):
        """generateContent with retry on transient 503/429. NEVER raises
        -- returns ChatTurnResult(success=False, ...) on any failure.
        gemini-2.5-flash free-tier returns 503 'high demand' ~half the
        time; a short retry resolves the large majority (200s land ms
        after the 503). If even the retries fail, the orchestrator
        (run_turn) falls back to Groq.

        ``temperature`` (WA-12.2): per-call override (extraction runs at 0);
        ``model`` accepted for signature parity with the Groq adapter (the
        Gemini endpoint is provider-row-bound; the override is ignored)."""
        start = time.time()
        try:
            api_key = self.provider._get_decrypted_api_key()
        except Exception as exc:  # noqa: BLE001
            return self._fail(start, f"Gemini API key lookup failed: {exc}")
        if not api_key:
            return self._fail(start, "Gemini API key not configured.")
        system_text, contents = _to_gemini_contents(messages)
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": (self.provider.temperature
                                if temperature is None else temperature),
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

        attempts = len(_RETRY_BACKOFFS) + 1
        for attempt in range(attempts):
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
            except requests.exceptions.Timeout:
                return self._fail(
                    start,
                    f"Gemini request timed out (>{_TIMEOUT_SECONDS}s).",
                    snapshot=payload)
            except requests.exceptions.RequestException as exc:
                return self._fail(
                    start, f"Gemini HTTP error: {exc}", snapshot=payload)
            except Exception as exc:  # noqa: BLE001
                return self._fail(
                    start, f"Gemini adapter error: {exc}", snapshot=payload)

            if response.ok:
                try:
                    return self._parse_ok(response, start)
                except Exception as exc:  # noqa: BLE001
                    return self._fail(
                        start, f"Gemini parse error: {exc}", snapshot=payload)

            status = response.status_code
            err = ""
            try:
                err = (response.json() if response.content
                       else {}).get("error", {})
            except Exception:  # noqa: BLE001
                err = (response.text or "")[:1000]
            if status in _RETRY_STATUSES and attempt < attempts - 1:
                _logger.warning(
                    "Gemini HTTP %s (attempt %d/%d) -- retrying in %.1fs",
                    status, attempt + 1, attempts, _RETRY_BACKOFFS[attempt])
                time.sleep(_RETRY_BACKOFFS[attempt])
                continue
            return self._fail(
                start, f"Gemini HTTP {status}: {err}", snapshot=payload)
        # Defensive -- the loop always returns above.
        return self._fail(start, "Gemini retries exhausted.", snapshot=payload)

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
