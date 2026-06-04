# -*- coding: utf-8 -*-
"""Phase 8A.M11 -- AI Insight provider catalog (INSIGHT half).

B11 / PRE-WA-0: the generic provider machinery (config fields, API-key
management, exactly-one-default constraint, superuser guard,
action_set_default) moved to neon_ai_core.models.ai_provider. This file
now EXTENDS that model via _inherit and re-adds the insight-generation
entry points that are coupled to neon_dashboard:

  * daily_call_count (reads neon.dashboard.ai.insight)
  * action_test_connection (uses the insight adapters that stay here)
  * action_generate_now + the cron + the OWL rpc_* entry points
  * _check_manual_refresh_rate + insight payload serialisers

These reference neon.dashboard / neon.dashboard.ai.insight /
InsightOrchestrator / GroqAdapter / RuleBasedAdapter -- all of which
stay in neon_dashboard. Keeping them here (not in core) preserves core
neutrality: neon_ai_core never imports neon_dashboard.

⚠️ DECISION (M11, carried): exactly-one-default constraint + key
management live in core now (neon_ai_core.models.ai_provider).
"""
import logging
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .ai.insight_orchestrator import InsightOrchestrator


_logger = logging.getLogger(__name__)


_MANUAL_REFRESH_RATE_LIMIT_SECONDS = 300  # 5 minutes per user


# Module-level in-memory rate-limit map -- the orchestrator side
# doesn't need persistence; a redis-style table would be overkill.
# Restart clears it (acceptable; superuser-only path, low volume).
_MANUAL_REFRESH_LAST_BY_USER = {}


class NeonDashboardAiProvider(models.Model):
    _inherit = "neon.dashboard.ai.provider"

    daily_call_count = fields.Integer(
        compute="_compute_daily_call_count",
        store=False,
    )

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
