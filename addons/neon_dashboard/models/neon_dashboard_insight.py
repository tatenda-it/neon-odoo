# -*- coding: utf-8 -*-
"""Phase 8A.M11 -- AI Insight history.

Append-only audit log. One row per generation attempt (success
or fallback). Stores the JSON content + provider attribution +
token / latency metrics.

⚠️ DECISION (M11, marker inline): content stored as JSON string
in a Text field, not a structured JSONB column. Odoo 17's
ir.model field types don't include native JSON; Char/Text +
json.loads is the project convention.

⚠️ DECISION (M11, marker inline): perm_unlink=0 for all tiers
including superuser per audit-trail standing rule (CLAUDE.md
'audit-trail discipline'). Corrections happen via new rows with
later generated_on, never deletion. (See related: M7
neon.dashboard.alert.dismissal append-only pattern.)
"""
import json
import logging

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class NeonDashboardAiInsight(models.Model):
    _name = "neon.dashboard.ai.insight"
    _description = "AI Insight Generation History"
    _order = "generated_on desc, id desc"

    dashboard_id = fields.Many2one(
        "neon.dashboard", ondelete="cascade", index=True,
    )
    provider_id = fields.Many2one(
        "neon.dashboard.ai.provider", ondelete="restrict",
    )
    generated_on = fields.Datetime(
        default=fields.Datetime.now, readonly=True, required=True,
        index=True,
    )
    content_json = fields.Text(
        readonly=True,
        help="Serialised list of InsightItem dicts.",
    )
    model_version = fields.Char(readonly=True)
    prompt_tokens = fields.Integer(readonly=True, default=0)
    completion_tokens = fields.Integer(readonly=True, default=0)
    latency_ms = fields.Integer(readonly=True, default=0)
    is_fallback = fields.Boolean(
        readonly=True, default=False, index=True,
        help="True when rule-based fallback fired (AI provider "
             "failed or was unconfigured).",
    )
    error_message = fields.Text(readonly=True)

    # Display helpers
    parsed_insights = fields.Json(
        compute="_compute_parsed_insights",
        help="Decoded JSON list for the OWL widget.",
    )
    age_hours = fields.Integer(
        compute="_compute_age_hours",
        help="Hours since generation (Africa/Harare).",
    )
    age_display = fields.Char(
        compute="_compute_age_hours",
        help="'2 hours ago' / '6 hours ago' label.",
    )

    @api.depends("content_json")
    def _compute_parsed_insights(self):
        for rec in self:
            if not rec.content_json:
                rec.parsed_insights = []
                continue
            try:
                parsed = json.loads(rec.content_json)
            except (json.JSONDecodeError, TypeError):
                _logger.warning(
                    "Insight %s: malformed content_json", rec.id)
                parsed = []
            rec.parsed_insights = (parsed if isinstance(parsed, list)
                                   else [])

    @api.depends("generated_on")
    def _compute_age_hours(self):
        Dashboard = self.env["neon.dashboard"].sudo()
        now_harare = Dashboard._now_harare().replace(tzinfo=None)
        for rec in self:
            if not rec.generated_on:
                rec.age_hours = 0
                rec.age_display = ""
                continue
            delta = now_harare - rec.generated_on
            hours = max(0, int(delta.total_seconds() // 3600))
            rec.age_hours = hours
            if hours <= 0:
                rec.age_display = "just now"
            elif hours == 1:
                rec.age_display = "1 hour ago"
            elif hours < 24:
                rec.age_display = f"{hours} hours ago"
            else:
                days = hours // 24
                rec.age_display = (
                    f"{days} day{'s' if days != 1 else ''} ago")
