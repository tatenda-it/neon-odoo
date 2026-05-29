# -*- coding: utf-8 -*-
"""P-B13 -- Claude doc-gen provider config.

One row per doc-gen provider (B13 ships exactly one: anthropic).
Holds endpoint + model + token caps + the encrypted key reference.

⚠️ DECISION (B13, D1, locked at gate-1 Q2): standalone module
neon_doc_gen. The Phase 8A encryption helper (which lives in
neon_dashboard.neon.dashboard.ai.provider only) is COPIED inline
here rather than pulled via depends -- pulling neon_dashboard
into this module would create a circular dependency once B3/B4/B5
in neon_jobs + neon_finance start calling the adapter.

⚠️ DECISION (B13, D7, locked at gate-1 Q3): ACL restricted to
neon_core.group_neon_superuser. The api_key_encrypted field is a
non-secret reference marker; the actual key lives in
ir.config_parameter under 'neon_doc_gen.api_key_<provider_key>'
which is sudo-only readable. A wizard (neon.doc.gen.set.key.wizard)
provides a non-echoing input dialog -- never logged, never echoed,
never displayed back.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


_logger = logging.getLogger(__name__)


_PROVIDER_KEYS = [
    ("anthropic", "Anthropic Claude (doc-gen)"),
]

_HEALTH_STATUSES = [
    ("untested", "Untested"),
    ("ok", "OK"),
    ("error", "Error"),
]


# B13 D1 -- key prefix is namespaced to neon_doc_gen so it cannot
# collide with neon_dashboard.ai_keys_anthropic if the dashboard
# ever gains an anthropic insight provider too.
_CONFIG_KEY_PREFIX = "neon_doc_gen.api_key_"

_SUPERUSER_GROUP = "neon_core.group_neon_superuser"


class NeonDocGenProvider(models.Model):
    _name = "neon.doc.gen.provider"
    _description = "Doc-Gen Provider (B13)"
    _order = "sequence, id"
    _rec_name = "name"

    name = fields.Char(required=True, translate=False)
    provider_key = fields.Selection(
        _PROVIDER_KEYS, required=True, index=True,
        help="Stable adapter identifier. Maps to a Python class "
             "in models/ai_doc_gen/*.py.",
    )
    endpoint_url = fields.Char(
        default="https://api.anthropic.com/v1/messages",
        help="Anthropic Messages API endpoint. Overrideable for "
             "proxy / staging routes.",
    )
    # B13 D6 -- default 'claude-sonnet-4-6' per gate-1 Q4.
    # Configurable so callers (B3/B4/B5) can override per doc type
    # by passing a different provider record.
    model = fields.Char(
        default="claude-sonnet-4-6",
        required=True,
        help="Claude model identifier. Default 'claude-sonnet-4-6' "
             "(Sonnet 4.6 -- best cost/quality for doc-gen). Other "
             "valid values: 'claude-opus-4-8' (top quality, ~5x "
             "cost), 'claude-haiku-4-5-20251001' (fastest, lowest "
             "cost).",
    )
    api_key_encrypted = fields.Char(
        string="API Key Reference",
        readonly=True,
        help="Reference marker only (e.g. 'anthropic:v1'). The "
             "actual key lives in ir.config_parameter at "
             "'neon_doc_gen.api_key_anthropic' which is sudo-only "
             "readable. Use the 'Set API Key' button to paste a "
             "key -- the input dialog never logs or echoes the "
             "value.",
    )
    has_api_key = fields.Boolean(
        compute="_compute_has_api_key", store=False,
        help="True when an API key has been pasted via the wizard. "
             "Used by the form view to enable the Test button.",
    )
    is_enabled = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    max_tokens = fields.Integer(
        default=4096,
        help="Per-call output cap. Anthropic Messages API requires "
             "this; raising it lets the model produce longer "
             "documents but adds latency.",
    )
    timeout_seconds = fields.Integer(
        default=30,
        help="HTTP timeout for the Messages API call. Doc-gen takes "
             "longer than chat (Phase 8A Groq adapter uses 15s); "
             "30s is the panic budget for a single document.",
    )

    # B13 D9 -- per-call usage snapshot (latest only). Per-call
    # history persistence is left to callers (B3/B4/B5).
    last_call_prompt_tokens = fields.Integer(readonly=True)
    last_call_completion_tokens = fields.Integer(readonly=True)
    last_call_at = fields.Datetime(readonly=True)

    last_health_check = fields.Datetime(readonly=True)
    last_health_status = fields.Selection(
        _HEALTH_STATUSES,
        default="untested",
        readonly=True,
    )

    _sql_constraints = [
        ("provider_key_unique",
         "UNIQUE (provider_key)",
         "Each doc-gen provider key must be unique."),
        ("max_tokens_positive",
         "CHECK (max_tokens > 0)",
         "max_tokens must be > 0."),
        ("timeout_positive",
         "CHECK (timeout_seconds > 0)",
         "timeout_seconds must be > 0."),
    ]

    # ============================================================
    # Computed
    # ============================================================
    @api.depends("api_key_encrypted")
    def _compute_has_api_key(self):
        for rec in self:
            rec.has_api_key = bool(
                rec._get_decrypted_api_key()) if rec.id else False

    # ============================================================
    # Encryption helpers (copied from Phase 8A pattern, per D1)
    # ============================================================
    def _config_key(self):
        self.ensure_one()
        return _CONFIG_KEY_PREFIX + (self.provider_key or "")

    def _get_decrypted_api_key(self):
        """Return the actual API key from ir.config_parameter.
        Returns empty string if no key set. Always wrapped in sudo
        -- the calling user does NOT need read access on
        ir.config_parameter (it's a config table)."""
        self.ensure_one()
        Config = self.env["ir.config_parameter"].sudo()
        return Config.get_param(self._config_key(), "") or ""

    def _set_api_key(self, plaintext):
        """Stash the plaintext key in ir.config_parameter; stamp
        the reference field with a non-secret marker.

        ACL: this is a helper -- the calling code (the wizard
        action_save_key, the smoke setup, programmatic post-deploy
        scripts) is responsible for the superuser check. Mirrors
        the Phase 8A pattern where _set_api_key is helper-only and
        the wizard / action layer guards the entry point.
        """
        self.ensure_one()
        Config = self.env["ir.config_parameter"].sudo()
        Config.set_param(self._config_key(), plaintext or "")
        marker = ((self.provider_key or "?") + ":v1") if plaintext else ""
        self.sudo().write({"api_key_encrypted": marker})

    # ============================================================
    # ACL helper
    # ============================================================
    def _check_superuser(self):
        """Raise AccessError if the current user is not a Neon
        superuser. All provider config + test-connection actions
        require this."""
        if not self.env.user.has_group(_SUPERUSER_GROUP):
            raise AccessError(_(
                "Only Neon Superusers (OD/MD) can manage doc-gen "
                "provider configuration."))

    # ============================================================
    # Public actions (called from form view buttons)
    # ============================================================
    def action_open_set_key_wizard(self):
        """Spawn the non-echoing key-entry wizard."""
        self.ensure_one()
        self._check_superuser()
        return {
            "type": "ir.actions.act_window",
            "name": _("Set Doc-Gen API Key"),
            "res_model": "neon.doc.gen.set.key.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_provider_id": self.id},
        }

    def action_test_connection(self):
        """Run the adapter's health_check + stamp result. Returns
        a green/red toast notification."""
        self.ensure_one()
        self._check_superuser()
        from .ai_doc_gen.claude_docgen_adapter import (
            ClaudeDocGenAdapter, DocGenError)

        ok = False
        detail = ""
        try:
            adapter = ClaudeDocGenAdapter(self)
            ok = adapter.health_check()
            if not ok:
                detail = "Health check returned False."
        except DocGenError as exc:
            ok = False
            detail = "{}: {}".format(type(exc).__name__, exc)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Doc-gen provider %s health_check raised "
                "unexpected exception: %s", self.name, exc)
            ok = False
            detail = "Unexpected: {}".format(type(exc).__name__)

        self.sudo().write({
            "last_health_check": fields.Datetime.now(),
            "last_health_status": "ok" if ok else "error",
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Doc-Gen Provider Health"),
                "message": (
                    _("Provider %s: OK") % self.name
                    if ok else
                    _("Provider %s: ERROR -- %s") % (
                        self.name, detail or "see server log")),
                "type": "success" if ok else "danger",
                "sticky": not ok,
            },
        }
