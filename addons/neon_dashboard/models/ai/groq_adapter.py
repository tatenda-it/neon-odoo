# -*- coding: utf-8 -*-
"""Phase 8A.M11 -- GroqAdapter (default AI provider).

Calls https://api.groq.com/openai/v1/chat/completions via
`requests`. OpenAI-compatible chat completions endpoint;
response_format=json_object yields strict JSON output.

⚠️ DECISION (M11, marker inline): direct `requests.post` + no
SDK. The Groq Python SDK is a thin wrapper over the
OpenAI-compatible API; direct HTTP keeps dependencies thin and
makes tests trivial (mock requests.post).

⚠️ DECISION (M11, marker inline): 15-second hard timeout per
addendum §11. Longer than that, treat as failure and let the
orchestrator fall back. Groq usually responds in 1-2s; 15s is
the panic budget.
"""
import json
import logging
import time

import requests

from .base_adapter import AdapterResult, BaseAdapter, InsightItem


_logger = logging.getLogger(__name__)


# ⚠️ DECISION (M11, marker inline): default system prompt per
# addendum §6.1. Stored as a module constant for easy tuning;
# admin override path is provider.system_prompt_template field.
DEFAULT_SYSTEM_PROMPT = """\
You are the AI assistant for Neon Events Elements, a premium event \
production company in Harare, Zimbabwe. You analyse the operations \
dashboard and produce daily priority insights for the Operational \
Director.

Your output must be:
- Specific: name the client, the job, the number, the deadline
- Actionable: every insight tells the director what to DO, not just \
  what is happening
- Prioritised: most urgent or highest-value action first
- Brief: each insight under 50 words

Avoid:
- Generic statements ("review your dashboard", "check the pipeline")
- Restating data without interpretation
- Speculation beyond what the data shows
- Corporate jargon ("synergies", "leverage", "optimise")

Focus areas, in priority order:
1. Risks materialising in the next 7 days (crew gaps, cert expiries, \
   deadlines)
2. Overdue invoices and cash flow timing
3. Sales pipeline against monthly target
4. Trends vs last week / last month worth noting

Output strictly as JSON in this format:
{
  "insights": [
    {
      "priority": 1,
      "title": "TelOne AGM Sat -- 5-crew gap with 6 days notice",
      "detail": "Job confirmed but only 2 of 7 crew assigned. \
Recommend freelancer outreach today; previous gaps closed in 4-5 \
days.",
      "source_ref": {"model": "commercial.event.job", "res_id": 142}
    }
  ]
}

Today is: {today_date}. Currency in USD unless noted ZiG. Use \
British/Zimbabwean English.\
"""


_TIMEOUT_SECONDS = 15
_HEALTH_TIMEOUT_SECONDS = 5


class GroqAdapter(BaseAdapter):

    def generate_insights(self, dashboard_context):
        start = time.time()
        try:
            api_key = self.provider._get_decrypted_api_key()
        except Exception as exc:  # noqa: BLE001
            return AdapterResult(
                success=False, error_message=f"API key lookup failed: {exc}",
                latency_ms=int((time.time() - start) * 1000),
            )

        if not api_key:
            return AdapterResult(
                success=False,
                error_message="Groq API key not configured.",
                latency_ms=int((time.time() - start) * 1000),
            )

        try:
            system_prompt = self._system_prompt(dashboard_context)
            user_prompt = self._build_user_prompt(dashboard_context)

            payload = {
                "model": self.provider.model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": self.provider.temperature,
                "max_tokens": self.provider.max_tokens,
                "response_format": {"type": "json_object"},
            }
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
            content = data["choices"][0]["message"]["content"]
            insights = self._parse_insights(content)
            usage = data.get("usage") or {}

            return AdapterResult(
                success=True,
                insights=insights,
                raw_response=content,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                latency_ms=int((time.time() - start) * 1000),
            )
        except requests.exceptions.Timeout:
            return AdapterResult(
                success=False,
                error_message=f"Groq request timed out (>{_TIMEOUT_SECONDS}s).",
                latency_ms=int((time.time() - start) * 1000),
            )
        except requests.exceptions.RequestException as exc:
            return AdapterResult(
                success=False,
                error_message=f"Groq HTTP error: {exc}",
                latency_ms=int((time.time() - start) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            return AdapterResult(
                success=False,
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

    # --------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------
    def _system_prompt(self, dashboard_context):
        template = (self.provider.system_prompt_template
                    or DEFAULT_SYSTEM_PROMPT)
        return template.replace(
            "{today_date}", str(dashboard_context.get("today_date") or ""))

    def _build_user_prompt(self, dashboard_context):
        ctx = dict(dashboard_context)
        ctx.pop("today_date", None)
        return (
            "DASHBOARD STATE:\n"
            + json.dumps(ctx, indent=2, default=str)
            + "\n\nProduce 3-5 insights as JSON in the format "
              "described above."
        )

    def _parse_insights(self, raw_content):
        """Defensive JSON parse with regex fallback if the model
        wrapped the payload in markdown fences or extra text."""
        if not raw_content:
            return []
        # Try clean parse first
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            parsed = self._extract_json_fallback(raw_content)
            if parsed is None:
                _logger.warning(
                    "GroqAdapter: malformed JSON response; "
                    "raw_content[:200]=%r", raw_content[:200])
                return []
        items_raw = parsed.get("insights") if isinstance(parsed, dict) else None
        if not isinstance(items_raw, list):
            return []
        items = []
        for it in items_raw[:5]:  # max 5 per addendum §6
            if not isinstance(it, dict):
                continue
            try:
                items.append(InsightItem(
                    priority=int(it.get("priority") or 99),
                    title=str(it.get("title") or "")[:200],
                    detail=str(it.get("detail") or "")[:600],
                    source_ref=(it.get("source_ref")
                                if isinstance(it.get("source_ref"), dict)
                                else None),
                ))
            except (TypeError, ValueError):
                continue
        return items

    def _extract_json_fallback(self, text):
        import re  # noqa: PLC0415 - only needed on rare malformed-output path
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
