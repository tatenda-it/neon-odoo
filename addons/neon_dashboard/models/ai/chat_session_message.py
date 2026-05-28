# -*- coding: utf-8 -*-
"""Phase 12.1 — AI Sales Copilot chat session + message audit log.

Two append-only models backing the chat panel:

- ``neon.finance.ai.chat.session``: one row per user (unique).
  Holds the persistent thread anchor; messages cascade off it.
- ``neon.finance.ai.chat.message``: append-only per-turn audit log.
  Captures role (user/assistant/tool/system), content, tool_calls
  JSON, token + latency metrics, fallback flag, error_message.

⚠️ DECISION (M12.1, marker inline): perm_unlink=0 for every group
on both models. Audit-trail rule (CLAUDE.md). Manual corrections
happen via new appended rows, never deletion. The cascade ondelete
on message.session_id is reachable only via SQL TRUNCATE (Odoo ORM
unlink is ACL-blocked on session for every role).

⚠️ DECISION (M12.1, marker inline): role uses Odoo Selection rather
than free-text Char. Groq tool-call protocol enumerates exactly the
four values we accept; Selection catches injection attempts at the
ORM layer.
"""
from odoo import api, fields, models


_ROLE_CHOICES = [
    ("user", "User"),
    ("assistant", "Assistant"),
    ("tool", "Tool"),
    ("system", "System"),
]


class NeonFinanceAiChatSession(models.Model):
    _name = "neon.finance.ai.chat.session"
    _description = "AI Sales Copilot Chat Session"
    _order = "last_activity_at desc, id desc"
    # NB: do NOT inherit mail.thread here. mail.thread reserves
    # `message_ids` as the o2m to mail.message; if we mounted it,
    # our own chat-message o2m would clash with the inherited one
    # at _update_inverses time. The audit trail on chat sessions is
    # carried by the chat-message rows directly + their created_at.

    user_id = fields.Many2one(
        "res.users", required=True, index=True, ondelete="cascade",
        string="User",
    )
    name = fields.Char(
        compute="_compute_name", store=False,
    )
    created_at = fields.Datetime(
        default=fields.Datetime.now, readonly=True, required=True,
    )
    last_activity_at = fields.Datetime(
        default=fields.Datetime.now, readonly=True, index=True,
    )
    chat_message_ids = fields.One2many(
        "neon.finance.ai.chat.message", "session_id",
        string="Chat Messages",
    )
    message_count = fields.Integer(
        compute="_compute_message_count",
    )

    _sql_constraints = [
        (
            "session_user_unique",
            "unique(user_id)",
            "Each user has exactly one AI chat session.",
        ),
    ]

    @api.depends("user_id")
    def _compute_name(self):
        for rec in self:
            rec.name = (rec.user_id.name or "?") + " — chat"

    @api.depends("chat_message_ids")
    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.chat_message_ids)

    @api.model
    def get_or_create_for_user(self, user_id=None):
        """Return the chat session for ``user_id`` (env.user.id by
        default), creating a fresh one on first use."""
        uid = user_id or self.env.user.id
        session = self.sudo().search([("user_id", "=", uid)], limit=1)
        if session:
            return session
        return self.sudo().create({"user_id": uid})

    def touch(self):
        """Stamp last_activity_at to now. Called on every message
        append from the orchestrator."""
        self.ensure_one()
        self.sudo().write({"last_activity_at": fields.Datetime.now()})


class NeonFinanceAiChatMessage(models.Model):
    _name = "neon.finance.ai.chat.message"
    _description = "AI Sales Copilot Chat Message"
    _order = "created_at, id"

    session_id = fields.Many2one(
        "neon.finance.ai.chat.session",
        required=True, ondelete="cascade", index=True,
    )
    role = fields.Selection(
        _ROLE_CHOICES, required=True, index=True,
    )
    content = fields.Text(
        help="Body of the message. May be empty for an assistant "
        "turn that only emits tool_calls.",
    )
    tool_calls_json = fields.Text(
        help="JSON array of tool calls emitted by an assistant "
        "turn. Each entry: {tool_call_id, tool_name, params}.",
    )
    tool_call_id = fields.Char(
        index=True,
        help="On role='tool', links back to the assistant turn's "
        "tool_calls entry that triggered this response.",
    )
    tool_name = fields.Char(
        help="Redundant index for the audit log so a search by "
        "tool_name doesn't need a JSON parse.",
    )
    provider_key = fields.Char(
        help="Adapter that produced this turn (groq / rule_based / "
        "etc). Empty on role='user' + role='system'.",
    )
    model_version = fields.Char()
    prompt_tokens = fields.Integer(default=0)
    completion_tokens = fields.Integer(default=0)
    latency_ms = fields.Integer(default=0)
    is_fallback = fields.Boolean(
        default=False, index=True,
        help="True when the rule-based or error-fallback path "
        "produced the turn instead of the live AI provider.",
    )
    error_message = fields.Text()
    created_at = fields.Datetime(
        default=fields.Datetime.now, readonly=True, required=True,
        index=True,
    )

    # ⚠️ DECISION (M12.1, marker inline): a composite index on
    # (session_id, created_at) supports the "load last N turns"
    # query pattern. _order already uses it but Postgres needs the
    # explicit index for large session histories.
    def init(self):
        super().init()  # noqa: F841
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS "
            "neon_finance_ai_chat_message_session_created_idx "
            "ON neon_finance_ai_chat_message (session_id, created_at)"
        )
