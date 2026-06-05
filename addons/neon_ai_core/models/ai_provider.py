# -*- coding: utf-8 -*-
"""B11 / PRE-WA-0 -- AI provider catalog (generic half).

Extracted from neon_dashboard.models.neon_dashboard_ai_provider. Holds
the provider-agnostic machinery: config fields, API-key management,
exactly-one-default constraint, superuser guard, set-default action.

The INSIGHT-generation entry points (cron_refresh_ai_insights,
rpc_*_for_current_user, action_generate_now, action_test_connection,
daily_call_count) are added back by neon_dashboard via _inherit -- they
reference neon.dashboard / neon.dashboard.ai.insight / InsightOrchestrator
and the insight adapters, which stay in neon_dashboard.

Model _name kept IDENTICAL (neon.dashboard.ai.provider) -- definition-
ownership shift only, no table rename. See neon_ai_core manifest.

⚠️ DECISION (M11, carried): API key NEVER stored as plaintext in
`api_key_encrypted`. Field holds a reference string (e.g. 'groq:v1');
the actual secret lives in ir.config_parameter under
'neon_dashboard.ai_keys_<provider_key>' (sudo-only readable).

⚠️ DECISION (B11 ai-core extraction): _CONFIG_KEY_PREFIX stays
'neon_dashboard.ai_keys_' -- the LIVE Groq key is stored under
'neon_dashboard.ai_keys_groq'. Changing the prefix would orphan the
live key. The prefix is a stable storage contract, not a namespace.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


_logger = logging.getLogger(__name__)


_PROVIDER_KEYS = [
    ("groq", "Groq (OpenAI-compatible)"),
    # WA-0: activated -- GeminiChatAdapter (chat_adapter_factory) routes
    # this key. Default chat provider for the WhatsApp rails; the
    # dashboard Copilot keeps Groq as is_default.
    ("google", "Google Gemini"),
    ("rule_based", "Rule-based fallback"),
    # Future: ('anthropic', 'Anthropic Claude'), ('ollama', 'Ollama').
]

_HEALTH_STATUSES = [
    ("untested", "Untested"),
    ("ok", "OK"),
    ("error", "Error"),
]

_CONFIG_KEY_PREFIX = "neon_dashboard.ai_keys_"


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
    # Generic actions + guards
    # --------------------------------------------------------------
    def _check_superuser(self):
        if not self.env.user.has_group("neon_core.group_neon_superuser"):
            raise AccessError(_(
                "AI provider configuration is restricted to "
                "Neon Superuser."))

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
