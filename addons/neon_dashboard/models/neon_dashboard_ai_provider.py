# -*- coding: utf-8 -*-
"""Phase 8A.M11 -- AI Insight provider catalog.

One row per provider. Holds config + usage stats; thin
@api.model wrappers expose cron + manual trigger entry points
that instantiate the orchestrator from the plain-python `ai/`
submodule.

⚠️ DECISION (M11, marker inline): API key NEVER stored in
`api_key_encrypted` field as plaintext. Field holds a reference
string (e.g. 'groq:v1'); the actual secret lives in
ir.config_parameter under 'neon_dashboard.ai_keys_<provider_key>'
which is sudo-only readable. Per addendum §11.

⚠️ DECISION (M11, marker inline): exactly-one-default constraint
enforced via @api.constrains, not SQL UNIQUE WHERE (Odoo 17 ORM
doesn't reliably support partial unique). The constraint runs
on every write of is_default; cheap query.
"""
import logging
from datetime import datetime, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .ai.insight_orchestrator import InsightOrchestrator


_logger = logging.getLogger(__name__)


_PROVIDER_KEYS = [
    ("groq", "Groq (OpenAI-compatible)"),
    ("rule_based", "Rule-based fallback"),
    # M11.1 will add: ('anthropic', 'Anthropic Claude'),
    #                 ('google', 'Google Gemini'),
    #                 ('ollama', 'Ollama (local)'),
]

_HEALTH_STATUSES = [
    ("untested", "Untested"),
    ("ok", "OK"),
    ("error", "Error"),
]

_CONFIG_KEY_PREFIX = "neon_dashboard.ai_keys_"

_MANUAL_REFRESH_RATE_LIMIT_SECONDS = 300  # 5 minutes per user


# Module-level in-memory rate-limit map -- the orchestrator side
# doesn't need persistence; a redis-style table would be overkill.
# Restart clears it (acceptable; superuser-only path, low volume).
_MANUAL_REFRESH_LAST_BY_USER = {}


class NeonDashboardAiProvider(models.Model):
    _name = "neon.dashboard.ai.provider"
    _description = "AI Insight Provider Catalog"
    _order = "is_default desc, sequence, id"
    _rec_name = "name"

    name = fields.Char(required=True, translate=False)
    provider_key = fields.Selection(
        _PROVIDER_KEYS, required=True, index=True,
        help="Stable adapter identifier. Maps to a Python class "
             "in models/ai/*.py.",
    )
    endpoint_url = fields.Char(
        help="API endpoint. Empty for rule-based.",
    )
    api_key_encrypted = fields.Char(
        string="API Key Reference",
        help="Reference identifier only; the actual secret lives "
             "in ir.config_parameter under "
             "'neon_dashboard.ai_keys_<provider_key>'. "
             "Never store plaintext keys in this field.",
    )
    model_id = fields.Char(
        string="Model",
        help="Provider-specific model name. For Groq: "
             "'llama-3.3-70b-versatile' (default, GPT-4o-class) or "
             "'llama-3.1-8b-instant' (max throughput).",
    )
    is_enabled = fields.Boolean(default=True)
    is_default = fields.Boolean(default=False)
    sequence = fields.Integer(default=10)
    max_tokens = fields.Integer(default=800)
    temperature = fields.Float(default=0.3)
    system_prompt_template = fields.Text(
        help="Override the default per-adapter system prompt. "
             "Leave blank to use the adapter's built-in default.",
    )
    daily_call_limit = fields.Integer(
        default=1000,
        help="Free-tier daily quota (Groq 1000 for llama-3.3-70b; "
             "rule-based ignored).",
    )
    daily_call_count = fields.Integer(
        compute="_compute_daily_call_count",
        store=False,
    )
    last_health_check = fields.Datetime(readonly=True)
    last_health_status = fields.Selection(
        _HEALTH_STATUSES,
        default="untested",
        readonly=True,
    )

    # --------------------------------------------------------------
    # Constraints
    # --------------------------------------------------------------
    @api.constrains("is_default", "is_enabled")
    def _check_one_default(self):
        """Exactly one provider can be default at any time. We
        permit zero defaults briefly during a swap (the UI toggles
        old -> new in two writes); enforce 'at most one' here."""
        defaults = self.search([("is_default", "=", True)])
        if len(defaults) > 1:
            raise ValidationError(_(
                "Only one AI provider can be marked default. "
                "Currently: %s"
            ) % ", ".join(defaults.mapped("name")))

    # --------------------------------------------------------------
    # Computed -- usage stats
    # --------------------------------------------------------------
    def _compute_daily_call_count(self):
        Insight = self.env["neon.dashboard.ai.insight"].sudo()
        Dashboard = self.env["neon.dashboard"]
        today = Dashboard._today_harare()
        start = fields.Datetime.to_string(
            datetime.combine(today, datetime.min.time()))
        for rec in self:
            rec.daily_call_count = Insight.search_count([
                ("provider_id", "=", rec.id),
                ("create_date", ">=", start),
            ])

    # --------------------------------------------------------------
    # API-key encryption helpers
    # --------------------------------------------------------------
    def _config_key(self):
        self.ensure_one()
        return _CONFIG_KEY_PREFIX + (self.provider_key or "")

    def _get_decrypted_api_key(self):
        """Return the actual API key from ir.config_parameter.
        Returns empty string if no key set or rule-based provider."""
        self.ensure_one()
        if self.provider_key == "rule_based":
            return ""
        Config = self.env["ir.config_parameter"].sudo()
        return Config.get_param(self._config_key(), "") or ""

    def _set_api_key(self, plaintext):
        """Stash the plaintext key in ir.config_parameter; stamp
        the reference field with a non-secret marker."""
        self.ensure_one()
        if self.provider_key == "rule_based":
            raise UserError(_(
                "Rule-based provider does not require an API key."))
        Config = self.env["ir.config_parameter"].sudo()
        Config.set_param(self._config_key(), plaintext or "")
        marker = ((self.provider_key or "?") + ":v1") if plaintext else ""
        self.sudo().write({"api_key_encrypted": marker})

    # --------------------------------------------------------------
    # Public actions (called from settings UI buttons)
    # --------------------------------------------------------------
    def action_test_connection(self):
        """Run the adapter's health_check, stamp result."""
        self.ensure_one()
        self._check_superuser()
        from .ai.groq_adapter import GroqAdapter  # noqa: PLC0415
        from .ai.rule_based_adapter import RuleBasedAdapter  # noqa: PLC0415

        ok = False
        try:
            if self.provider_key == "groq":
                ok = GroqAdapter(self).health_check()
            elif self.provider_key == "rule_based":
                ok = RuleBasedAdapter(
                    self, env=self.env).health_check()
            else:
                ok = False
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Provider %s health_check raised: %s",
                self.name, exc,
            )
            ok = False
        self.sudo().write({
            "last_health_check": fields.Datetime.now(),
            "last_health_status": "ok" if ok else "error",
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Provider Health"),
                "message": _("Provider %s: %s") % (
                    self.name, "OK" if ok else "Error"),
                "type": "success" if ok else "danger",
                "sticky": False,
            },
        }

    def action_set_default(self):
        """Mark this provider as the active default. Clears the
        flag on every other provider first."""
        self.ensure_one()
        self._check_superuser()
        if self.provider_key == "rule_based":
            raise UserError(_(
                "Rule-based provider cannot be the default. It is "
                "always available as a fallback when the AI "
                "provider fails."))
        others = self.search([
            ("id", "!=", self.id),
            ("is_default", "=", True),
        ])
        others.sudo().write({"is_default": False})
        self.sudo().write({"is_default": True, "is_enabled": True})
        return True

    def action_generate_now(self):
        """Manual refresh trigger from settings page. Rate-limited
        per user."""
        self.ensure_one()
        self._check_superuser()
        self._check_manual_refresh_rate()
        dashboard = self.env["neon.dashboard"].sudo().search(
            [("user_id", "=", self.env.user.id)], limit=1)
        if not dashboard:
            dashboard = self.env["neon.dashboard"].sudo()\
                .get_or_create_for_user(self.env.user.id)
        insight = InsightOrchestrator(self.env)\
            .generate_for_dashboard(dashboard)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("AI Insights Refreshed"),
                "message": _(
                    "%(count)d insights generated "
                    "(provider: %(provider)s%(fallback)s, "
                    "latency: %(latency)dms)"
                ) % {
                    "count": len(insight.parsed_insights),
                    "provider": (insight.provider_id.name
                                 if insight.provider_id else "?"),
                    "fallback": " - FALLBACK" if insight.is_fallback else "",
                    "latency": insight.latency_ms or 0,
                },
                "type": "success",
                "sticky": False,
            },
        }

    # --------------------------------------------------------------
    # @api.model entry points (cron + RPC from OWL)
    # --------------------------------------------------------------
    @api.model
    def cron_refresh_ai_insights(self):
        """Daily cron entry. Internal guard fires the actual
        generation only at hours 6, 12, 18 in Africa/Harare.
        Pattern matches M9 weekly digest's daily-cron-internal-
        guard. Never re-raises; cron must keep running."""
        Dashboard = self.env["neon.dashboard"].sudo()
        now_harare = Dashboard._now_harare()
        if now_harare.hour not in (6, 12, 18):
            _logger.info(
                "M11 AI cron: hour %d Harare not in (6,12,18); "
                "skipping.", now_harare.hour,
            )
            return
        # Find all dashboards (one per user) and refresh each.
        # In Phase 8A only the director uses this widget; M11
        # generates for every dashboard regardless of tier so
        # bookkeeper/sales/etc. can opt-in later via layout flip.
        try:
            dashboards = Dashboard.search([])
            orchestrator = InsightOrchestrator(self.env)
            for dashboard in dashboards:
                try:
                    orchestrator.generate_for_dashboard(dashboard)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "M11 AI cron: dashboard %s failed: %s",
                        dashboard.id, exc,
                    )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "M11 AI cron: top-level failure (not re-raised): %s",
                exc, exc_info=True,
            )

    @api.model
    def rpc_refresh_for_current_user(self):
        """OWL manual-refresh entry point. Rate-limited per user
        + superuser-only (see _check_manual_refresh_rate +
        _check_superuser)."""
        self._check_superuser()
        self._check_manual_refresh_rate()
        Dashboard = self.env["neon.dashboard"].sudo()
        dashboard = Dashboard.search(
            [("user_id", "=", self.env.user.id)], limit=1)
        if not dashboard:
            dashboard = Dashboard.get_or_create_for_user(
                self.env.user.id)
        insight = InsightOrchestrator(self.env)\
            .generate_for_dashboard(dashboard)
        return self._serialize_insight_for_rpc(insight)

    @api.model
    def rpc_latest_insight_for_current_user(self):
        """OWL initial-render entry point. Returns the latest
        insight as a dict suitable for the widget."""
        Insight = self.env["neon.dashboard.ai.insight"].sudo()
        Dashboard = self.env["neon.dashboard"].sudo()
        dashboard = Dashboard.search(
            [("user_id", "=", self.env.user.id)], limit=1)
        latest = Insight.search(
            [("dashboard_id", "=", dashboard.id if dashboard else 0)],
            limit=1, order="generated_on desc, id desc",
        )
        if not latest:
            return self._empty_widget_payload()
        return self._serialize_insight_for_rpc(latest)

    # --------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------
    def _check_superuser(self):
        if not self.env.user.has_group("neon_core.group_neon_superuser"):
            raise AccessError(_(
                "AI Insights configuration is restricted to "
                "Neon Superuser."))

    def _check_manual_refresh_rate(self):
        uid = self.env.user.id
        last = _MANUAL_REFRESH_LAST_BY_USER.get(uid)
        now = fields.Datetime.now()
        if last is not None:
            gap = (now - last).total_seconds()
            if gap < _MANUAL_REFRESH_RATE_LIMIT_SECONDS:
                wait = int(_MANUAL_REFRESH_RATE_LIMIT_SECONDS - gap)
                raise UserError(_(
                    "Manual refresh rate-limited. Wait %d seconds "
                    "before refreshing again."
                ) % wait)
        _MANUAL_REFRESH_LAST_BY_USER[uid] = now

    def _serialize_insight_for_rpc(self, insight):
        return {
            "id": insight.id,
            "generated_on": fields.Datetime.to_string(
                insight.generated_on),
            "age_hours": insight.age_hours,
            "is_fallback": bool(insight.is_fallback),
            "provider_name": (insight.provider_id.name
                              if insight.provider_id else ""),
            "model_version": insight.model_version or "",
            "latency_ms": int(insight.latency_ms or 0),
            "error_message": insight.error_message or "",
            "insights": insight.parsed_insights,
        }

    def _empty_widget_payload(self):
        Config = self.env["ir.config_parameter"].sudo()
        groq_key = Config.get_param("neon_dashboard.ai_keys_groq", "")
        configured = bool(groq_key)
        return {
            "id": False,
            "empty": True,
            "configured": configured,
            "empty_message": (
                _("Insights will appear after first refresh.")
                if configured else
                _("AI provider not configured. Settings -> Neon "
                  "-> AI Insights.")
            ),
            "insights": [],
        }
