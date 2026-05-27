# -*- coding: utf-8 -*-
"""Phase 8A.M11 -- InsightOrchestrator (routes + fallback).

Plain Python class (not an Odoo model) per addendum §5.3.
Constructed with `env`; called by:
* thin @api.model wrapper on neon.dashboard.ai.provider
  (cron + manual trigger paths)
* the dashboard widget's stale-auto-refresh path

Always returns a neon.dashboard.ai.insight record; never raises
to caller. Failures persist as ``is_fallback=True`` rows with
the rule-based output and an error_message field.

⚠️ DECISION (M11, marker inline): _logger.warning for failure
logging, NOT self.env['ir.logging'].create(). Project convention
(zero ir.logging.create calls across all neon_* modules; M9 +
M10 + Phase 7 all use _logger). Addendum §5.3 sample code uses
ir.logging.create -- diverged from convention; we follow
convention.

⚠️ DECISION (M11, marker inline): token-budget truncation lives
here (single source of truth) rather than in each adapter.
MAX_INPUT_TOKENS module constant. Drop fields in priority order:
deep history -> low-priority tasks -> old completed jobs.
"""
import json
import logging

from .base_adapter import AdapterResult
from .groq_adapter import GroqAdapter
from .rule_based_adapter import RuleBasedAdapter


_logger = logging.getLogger(__name__)


# Per addendum §11 + prompt D10. Conservative for Groq's
# typical 6,000 TPM free-tier cap. One char ≈ 1/4 token for
# English; we use char-based heuristics since tiktoken isn't
# available in Odoo's base image.
MAX_INPUT_TOKENS = 2500
_CHARS_PER_TOKEN = 4
_MAX_INPUT_CHARS = MAX_INPUT_TOKENS * _CHARS_PER_TOKEN


_ADAPTER_BY_KEY = {
    "groq": GroqAdapter,
    "rule_based": RuleBasedAdapter,
    # M11.1 will add: 'anthropic', 'google', 'ollama'
}


class InsightOrchestrator:
    """Routes generation calls to the active provider; falls
    back to rule-based on failure. Persists every result."""

    def __init__(self, env):
        self.env = env

    # ==============================================================
    # Public entry point
    # ==============================================================
    def generate_for_dashboard(self, dashboard):
        """Build the dashboard context, pick the active provider,
        try it, fall back on failure. Return the persisted
        neon.dashboard.ai.insight record."""
        context = self._build_context(dashboard)

        active = self.env["neon.dashboard.ai.provider"].sudo().search([
            ("is_default", "=", True),
            ("is_enabled", "=", True),
            ("provider_key", "!=", "rule_based"),
        ], limit=1)

        if not active:
            return self._call_rule_based(
                dashboard, context,
                error="No active AI provider configured.",
            )

        adapter_cls = _ADAPTER_BY_KEY.get(active.provider_key)
        if adapter_cls is None:
            return self._call_rule_based(
                dashboard, context,
                error=f"No adapter class for provider_key={active.provider_key!r}",
            )

        adapter = adapter_cls(active)
        result = adapter.generate_insights(context)

        if not result.success:
            _logger.warning(
                "AI provider %s failed: %s (latency=%dms)",
                active.name, result.error_message, result.latency_ms,
            )
            return self._call_rule_based(
                dashboard, context,
                error=result.error_message or "Adapter returned success=False",
            )

        return self._persist_insight(
            dashboard, active, result, is_fallback=False)

    # ==============================================================
    # Adapter dispatch helpers
    # ==============================================================
    def _call_rule_based(self, dashboard, context, error=None):
        adapter = RuleBasedAdapter(provider_record=None, env=self.env)
        result = adapter.generate_insights(context)
        provider = self.env["neon.dashboard.ai.provider"].sudo().search(
            [("provider_key", "=", "rule_based")], limit=1)
        return self._persist_insight(
            dashboard, provider, result,
            is_fallback=True, error_message=error,
        )

    def _persist_insight(self, dashboard, provider, result: AdapterResult,
                         is_fallback=False, error_message=None):
        Insight = self.env["neon.dashboard.ai.insight"].sudo()
        payload_dicts = result.insights_as_dicts()
        return Insight.create({
            "dashboard_id": dashboard.id if dashboard else False,
            "provider_id": provider.id if provider else False,
            "content_json": json.dumps(payload_dicts),
            "model_version": (
                provider.model_id if provider
                and provider.provider_key != "rule_based" else ""
            ),
            "prompt_tokens": int(result.prompt_tokens or 0),
            "completion_tokens": int(result.completion_tokens or 0),
            "latency_ms": int(result.latency_ms or 0),
            "is_fallback": bool(is_fallback),
            "error_message": error_message or result.error_message or "",
        })

    # ==============================================================
    # Context build + token-budget truncation
    # ==============================================================
    def _build_context(self, dashboard):
        """Build the dict the adapter feeds to the LLM.

        P8B: scopes the snapshot to the dashboard's OWN type (not a
        hardcoded 'director') so a Sales / Bookkeeper / Lead Tech
        dashboard's AI sees the data that variant actually shows. The
        dashboard_type also flows into the context so the Groq system
        prompt + rule-based fallback can frame insights for the right
        audience (D6)."""
        Dashboard = self.env["neon.dashboard"].sudo()
        dashboard_type = (dashboard.dashboard_type
                          if dashboard and dashboard.dashboard_type
                          else "director")
        payload = Dashboard._build_snapshot_payload(
            dashboard_type, "all")
        today = Dashboard._today_harare()
        context = {
            "today_date": today.isoformat(),
            "dashboard_type": dashboard_type,
            "user_name": (dashboard.user_id.name
                          if dashboard and dashboard.user_id else ""),
            "business_currency": "USD",
            **payload,
        }
        return self._truncate_context(context)

    def _truncate_context(self, context):
        """Char-budget the context. Drop in priority order until
        the JSON serialisation is within MAX_INPUT_CHARS."""
        # Always-included keys (cheap):
        priority_drops = [
            "tasks_block",            # low-priority delegated tasks
            "crew_equipment_block",   # detail-heavy
            "sales_block",            # pipeline-by-stage details
            "alerts_block",           # alerts
            "jobs_block",             # last to drop -- usually highest signal
        ]
        ctx = dict(context)
        for drop_key in priority_drops:
            size = len(json.dumps(ctx, default=str))
            if size <= _MAX_INPUT_CHARS:
                return ctx
            if drop_key in ctx:
                ctx.pop(drop_key)
        # Final fallback -- if even after dropping, still too big,
        # truncate the value strings of every remaining dict.
        if len(json.dumps(ctx, default=str)) > _MAX_INPUT_CHARS:
            self._coarse_truncate(ctx)
        return ctx

    def _coarse_truncate(self, ctx):
        for key, value in list(ctx.items()):
            if isinstance(value, str) and len(value) > 400:
                ctx[key] = value[:400] + "..."
            elif isinstance(value, dict):
                self._coarse_truncate(value)
