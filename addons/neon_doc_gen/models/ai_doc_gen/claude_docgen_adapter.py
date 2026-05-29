# -*- coding: utf-8 -*-
"""P-B13 -- ClaudeDocGenAdapter.

Single-shot Anthropic Messages API caller with strict-JSON
enforcement. Used by B3 (deployment plans), B4 (sub-hire drafts),
and B5 (reconciliation) to turn a structured `facts` dict into a
parsed JSON document.

⚠️ DECISION (B13, D2): direct ``requests.post`` to
``https://api.anthropic.com/v1/messages`` -- no anthropic SDK.
Mirrors the Phase 8A GroqAdapter pattern.

⚠️ DECISION (B13, D3+D4): the interface is
``generate(system_prompt, facts, json_schema=None) -> dict``.
Strict-JSON enforcement: one re-prompt on parse failure before
``DocGenJSONError`` is raised. System prompt suffix locked at
"Respond with ONLY a single JSON object."

⚠️ DECISION (B13, D5): six typed exceptions inherit a single
base (``DocGenError``) so callers can catch the family with one
``except``. They surface to the user as the doc-gen feature's
failure card; never silent.

⚠️ DECISION (B13, D9): per-call usage is returned in the result
dict (``usage`` key) so the caller decides whether to persist.
The provider record also stamps ``last_call_prompt_tokens`` /
``last_call_completion_tokens`` / ``last_call_at`` -- a snapshot
of the latest call for the config-page health view.
"""
import json
import logging
import re
import time

import requests


_logger = logging.getLogger(__name__)


_ANTHROPIC_VERSION_HEADER = "2023-06-01"
_JSON_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE | re.MULTILINE)

_STRICT_JSON_SUFFIX = (
    "\n\nRespond with ONLY a single JSON object. "
    "No prose. No markdown. No code fences. Just the JSON."
)

_REPROMPT_USER_MSG = (
    "Your last response was not valid JSON. "
    "Return ONLY the JSON object, no prose, no markdown, no fences."
)


# ============================================================
# Typed exceptions
# ============================================================
class DocGenError(Exception):
    """Base class -- callers (B3/B4/B5) catch this to render
    a single failure UX without needing to know the subtype."""


class DocGenConfigError(DocGenError):
    """Missing/blank API key, missing model, disabled provider."""


class DocGenAPIError(DocGenError):
    """4xx error other than rate-limit. e.g. malformed payload,
    auth error, content policy."""


class DocGenRateLimitError(DocGenError):
    """HTTP 429 from Anthropic. Caller may retry with backoff,
    surface to the user, or schedule for later."""


class DocGenTimeoutError(DocGenError):
    """requests.Timeout or socket-level timeout."""


class DocGenServerError(DocGenError):
    """HTTP 5xx from Anthropic. Caller may retry or fall back."""


class DocGenJSONError(DocGenError):
    """Response was not valid JSON after one re-prompt cycle."""


# ============================================================
# Adapter
# ============================================================
class ClaudeDocGenAdapter:
    """One instance per generate() call. Stateless on the wire;
    the provider record carries config + usage snapshot."""

    def __init__(self, provider):
        """``provider`` is a ``neon.doc.gen.provider`` recordset
        (singleton). Read-only on the provider config; the only
        write is the post-call usage snapshot."""
        if not provider or not provider.exists():
            raise DocGenConfigError(
                "No doc-gen provider configured.")
        provider.ensure_one()
        self.provider = provider

    # --- public API -------------------------------------------------

    def generate(self, system_prompt, facts, json_schema=None):
        """Generate a single JSON document.

        Args:
            system_prompt: instruction to the model. Caller is
                responsible for prompt engineering; this adapter
                appends a strict-JSON suffix.
            facts: dict serialized to JSON and passed as the user
                message. Keys describe the input context.
            json_schema: optional dict (JSON Schema-style) used as
                guidance text in the system prompt. NOT enforced
                via tool-use -- the model is asked to comply via
                the strict-JSON suffix.

        Returns:
            dict: {"result": <parsed JSON object>,
                   "usage": {"prompt_tokens": N,
                              "completion_tokens": N},
                   "model": str, "latency_ms": int}

        Raises:
            DocGenConfigError / DocGenAPIError / DocGenRateLimitError
            / DocGenTimeoutError / DocGenServerError /
            DocGenJSONError -- all inherit DocGenError.
        """
        api_key = self.provider._get_decrypted_api_key()
        if not api_key:
            raise DocGenConfigError(
                "Claude API key not configured for doc-gen.")
        if not self.provider.is_enabled:
            raise DocGenConfigError(
                "Doc-gen provider is disabled.")
        model = (self.provider.model or "").strip()
        if not model:
            raise DocGenConfigError(
                "Doc-gen provider model is not set.")

        full_system_prompt = self._build_system_prompt(
            system_prompt, json_schema)
        user_msg = self._build_user_message(facts)
        messages = [{"role": "user", "content": user_msg}]

        # First attempt + one re-prompt on JSON parse failure.
        for attempt in range(2):
            data, usage, latency = self._call_anthropic(
                api_key=api_key,
                model=model,
                system_prompt=full_system_prompt,
                messages=messages,
            )
            raw_text = self._extract_text(data)
            try:
                result = self._parse_strict_json(raw_text)
            except DocGenJSONError:
                if attempt == 0:
                    # Append the bad response + a corrective user
                    # turn; retry once.
                    messages.append({
                        "role": "assistant", "content": raw_text})
                    messages.append({
                        "role": "user", "content": _REPROMPT_USER_MSG})
                    continue
                raise
            else:
                self._record_usage(usage)
                return {
                    "result": result,
                    "usage": usage,
                    "model": model,
                    "latency_ms": latency,
                }
        # unreachable -- the loop either returns or raises
        raise DocGenJSONError(
            "Strict-JSON enforcement loop terminated unexpectedly.")

    def health_check(self):
        """Minimal connectivity test. Sends a trivial prompt that
        must echo {"ok": true} back. Returns bool, never raises
        (errors are caught and logged + stamped on the provider).
        The test-connection button calls this."""
        try:
            out = self.generate(
                system_prompt=(
                    "You are a connectivity test. Reply exactly "
                    "{\"ok\": true} and nothing else."),
                facts={"ping": True},
            )
            return bool(out.get("result", {}).get("ok") is True)
        except DocGenError as exc:
            _logger.warning(
                "Doc-gen health_check failed: %s: %s",
                type(exc).__name__, exc)
            return False

    # --- HTTP -------------------------------------------------------

    def _call_anthropic(self, api_key, model, system_prompt,
                        messages):
        """Single Anthropic Messages API round-trip. Returns
        (response_json, usage_dict, latency_ms). Raises one of
        the typed errors on failure -- never returns None."""
        endpoint = (self.provider.endpoint_url
                     or "https://api.anthropic.com/v1/messages")
        timeout = self.provider.timeout_seconds or 30
        max_tokens = self.provider.max_tokens or 4096
        payload = {
            "model": model,
            "max_tokens": int(max_tokens),
            "system": system_prompt,
            "messages": messages,
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION_HEADER,
            "content-type": "application/json",
        }
        start = time.time()
        try:
            response = requests.post(
                endpoint, headers=headers, json=payload,
                timeout=timeout)
        except requests.Timeout as exc:
            raise DocGenTimeoutError(
                "Anthropic API timeout after "
                "{}s.".format(timeout)) from exc
        except requests.RequestException as exc:
            # Network failure, DNS, conn refused, etc. Mapped to
            # API error so callers see a uniform DocGenError.
            raise DocGenAPIError(
                "Anthropic API connection failed: "
                "{}".format(type(exc).__name__)) from exc
        latency_ms = int((time.time() - start) * 1000)

        if response.status_code == 429:
            raise DocGenRateLimitError(
                "Anthropic API rate limit hit (HTTP 429).")
        if 500 <= response.status_code < 600:
            raise DocGenServerError(
                "Anthropic API server error (HTTP "
                "{}).".format(response.status_code))
        if not response.ok:
            # 4xx other than 429 -- e.g. invalid API key, payload
            # too large, content policy. Surface body fragment but
            # never the API key.
            err = self._safe_error_body(response)
            raise DocGenAPIError(
                "Anthropic API error (HTTP {}): {}".format(
                    response.status_code, err))

        try:
            data = response.json()
        except ValueError as exc:
            raise DocGenAPIError(
                "Anthropic API returned non-JSON response.") from exc

        usage = self._extract_usage(data)
        return data, usage, latency_ms

    @staticmethod
    def _safe_error_body(response):
        """Pull a SHORT error fragment from the response body.
        Capped + key-stripped so accidental echo of headers can't
        leak the api key (it's in headers, not body, but defense
        in depth)."""
        try:
            body = response.text or ""
        except Exception:  # noqa: BLE001
            return "(unreadable body)"
        # Truncate + scrub any "api_key": "...." pattern just in
        # case Anthropic ever echoes the key in error responses.
        body = re.sub(
            r'("?api[_-]?key"?\s*[:=]\s*"?)[^",\s]+',
            r'\1<REDACTED>', body, flags=re.IGNORECASE)
        return body[:500]

    @staticmethod
    def _extract_text(data):
        """Anthropic Messages API returns:
            {'content': [{'type': 'text', 'text': '...'}], ...}
        Pull the first text block. Empty if no text content
        (e.g. tool_use only -- not used here)."""
        for block in data.get("content") or []:
            if block.get("type") == "text":
                return block.get("text", "")
        return ""

    @staticmethod
    def _extract_usage(data):
        """Pull token counts from the Anthropic response."""
        usage = data.get("usage") or {}
        return {
            "prompt_tokens": int(usage.get("input_tokens", 0) or 0),
            "completion_tokens": int(
                usage.get("output_tokens", 0) or 0),
        }

    # --- prompt assembly --------------------------------------------

    @staticmethod
    def _build_system_prompt(base, json_schema):
        """Locked system-prompt template. Concatenates the
        caller's prompt + optional schema guidance + the
        strict-JSON suffix."""
        parts = [base or ""]
        if json_schema:
            parts.append(
                "\n\nThe JSON object you return MUST conform to "
                "this schema (informational guidance):\n"
                + json.dumps(json_schema, indent=2, sort_keys=True))
        parts.append(_STRICT_JSON_SUFFIX)
        return "".join(parts).strip()

    @staticmethod
    def _build_user_message(facts):
        """Serialize the facts dict as the user turn. Caller must
        not put secrets in facts; the adapter ships them as-is."""
        if facts is None:
            facts = {}
        try:
            return json.dumps(facts, sort_keys=True, default=str)
        except Exception as exc:  # noqa: BLE001
            raise DocGenAPIError(
                "Facts dict is not JSON-serialisable: "
                "{}".format(exc))

    # --- JSON parsing -----------------------------------------------

    @staticmethod
    def _parse_strict_json(raw):
        """Strip fences + whitespace, json.loads. Raise
        DocGenJSONError on parse failure (caller retries once
        before propagating)."""
        cleaned = _JSON_FENCE_RE.sub("", (raw or "").strip()).strip()
        if not cleaned:
            raise DocGenJSONError(
                "Empty response body (no JSON returned).")
        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise DocGenJSONError(
                "Response was not valid JSON: {}".format(exc.msg)
            ) from exc
        if not isinstance(obj, dict):
            raise DocGenJSONError(
                "Response was valid JSON but not an object "
                "(got {}).".format(type(obj).__name__))
        return obj

    # --- usage snapshot ---------------------------------------------

    def _record_usage(self, usage):
        """Stamp the latest usage on the provider record.
        Best-effort -- failure here MUST NOT block the caller."""
        try:
            from odoo import fields as ofields
            self.provider.sudo().write({
                "last_call_prompt_tokens": int(
                    usage.get("prompt_tokens", 0) or 0),
                "last_call_completion_tokens": int(
                    usage.get("completion_tokens", 0) or 0),
                "last_call_at": ofields.Datetime.now(),
            })
        except Exception:  # noqa: BLE001
            _logger.exception(
                "Doc-gen provider usage snapshot write failed "
                "(non-fatal).")
