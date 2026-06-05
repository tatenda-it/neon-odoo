# -*- coding: utf-8 -*-
"""B11 / WA-0 -- WhatsApp Copilot service (resolution + scope + guardrail).

Net-new THIN wiring over the existing neon_ai_core engine -- NOT a
parallel build. One inbound privileged turn:

  phone -> neon.bot.user.user_id -> res.users groups -> variant
       (REUSE _stored_variant_for, the ex-chat_orchestrator resolver)
  tools = filter_tools_for_variant_and_user(user, variant)  (REUSE)
          ∩ WhatsApp allow-list  (reads + 3 reversible CRM writes; NO money)
  ONE provider call (Gemini default for WA; free-tier, no fan-out)
       reads  -> tool_registry.dispatch(user)   (user-scoped; intersection
                 ACL enforced defensively even if the model emits an
                 off-scope tool)
       writes -> write.log.propose() -> cta_url deep-link ("confirm in Odoo")
  reply -> text [+ cta_url]; turn persisted to neon.whatsapp.message

Authority is the resolved USER's identity intersected with their group
scope -- never the bot's, never elevated. Money tools are NEVER in the
WhatsApp allow-list for ANY variant (incl. director / OD superuser):
even Robin cannot move money or single-tap an irreversible commit here.
"""
import json
import logging

from odoo.addons.neon_ai_core.models.ai import tool_registry
from odoo.addons.neon_ai_core.models.ai.chat_adapter_factory import (
    get_chat_adapter,
)
from odoo.addons.neon_ai_core.models.ai.chat_orchestrator import (
    _stored_variant_for,
)


_logger = logging.getLogger(__name__)

# Which catalog provider WhatsApp uses. SEPARATE from the dashboard
# Copilot's is_default (Groq) so activating Gemini here never touches it.
_WA_PROVIDER_PARAM = "neon_channels.whatsapp_provider_key"

# ⚠️ DECISION (WA-0, locked #2): the ONLY write tools exposed over
# WhatsApp. All reversible CRM writes, delivered via cta_url confirm-in-
# Odoo. update_deal_value is EXCLUDED (money-adjacent £ field) and every
# finance/money tool is excluded by omission -- a write tool not in this
# set is structurally unreachable over WhatsApp, for every variant.
_WA_SAFE_WRITES = {"log_lead", "move_stage", "post_chatter_note"}

_HISTORY_LIMIT = 6

_SYSTEM_PROMPT = (
    "You are the Neon Events {role} assistant, replying to {name} over "
    "WhatsApp. Neon Events Elements is an event-production company in "
    "Harare, Zimbabwe. Keep replies short (1-3 sentences) and "
    "professional -- this is a phone chat. Use tools to answer factual "
    "questions; never invent numbers, names, or dates. Currency: USD or "
    "ZiG; VAT 15%. You can prepare reversible actions (log a lead, move a "
    "deal stage, post a note) but they are NEVER done over WhatsApp -- you "
    "return a confirmation link the user opens in Odoo. You cannot move "
    "money, send invoices, or take payments here. Today is {today}."
)


class WhatsAppCopilotService:
    """One instance per inbound turn. Pure Python; reuses the engine."""

    def __init__(self, env):
        self.env = env

    # ------------------------------------------------------------------
    # Resolution + scope  (piece a)
    # ------------------------------------------------------------------
    def resolve(self, phone):
        """phone_number -> active neon.bot.user (or empty recordset)."""
        return self.env["neon.bot.user"].sudo().search([
            ("phone_number", "=", phone),
            ("active", "=", True),
        ], limit=1)

    def variant_for(self, user):
        """REUSE the core group->variant resolver under the user's env."""
        return _stored_variant_for(self.env(user=user.id), user)

    def whatsapp_tools(self, user, variant):
        """Intersection of (variant scope ∩ user groups) THEN the
        WhatsApp policy: all read tools + only the WA-safe writes. Any
        money/finance write is absent by omission, for every variant."""
        base = tool_registry.filter_tools_for_variant_and_user(
            user, variant, category=None)
        return [t for t in base
                if t.category == "read" or t.name in _WA_SAFE_WRITES]

    # ------------------------------------------------------------------
    # Turn  (pieces a + b + c)
    # ------------------------------------------------------------------
    def run_turn(self, bot_user, inbound_text):
        """Drive one privileged inbound turn. Returns
        {"text": str, "cta_url": str|None, "error": str|None}."""
        user = bot_user.user_id
        env_u = self.env(user=user.id)
        variant = self.variant_for(user)
        tools = self.whatsapp_tools(user, variant)
        schemas = tool_registry.groq_tool_schemas(tools=tools)

        provider = self._wa_provider()
        adapter = get_chat_adapter(provider) if provider else None
        if not adapter:
            return {"text": "The assistant is not configured yet. Please "
                            "contact an administrator.",
                    "cta_url": None, "error": "no_provider"}

        messages = self._build_messages(
            user, variant, inbound_text, bot_user.phone_number)

        # SINGLE provider call per inbound turn -- no fan-out, no
        # iterate-after-tools loop (free-tier guard, locked).
        result = adapter.chat(messages, tools=schemas)
        if not result.success:
            return {"text": "Sorry -- I can't reach the assistant right "
                            "now. Please try again shortly.",
                    "cta_url": None, "error": result.error_message}

        if not result.tool_calls:
            return {"text": result.assistant_message or "...",
                    "cta_url": None, "error": None}

        # Execute tool calls in ONE pass (no second LLM call). Reads
        # return data; writes become a cta_url confirm-in-Odoo link.
        lines = []
        cta_url = None
        for tc in result.tool_calls:
            name = tc.get("tool_name") or ""
            params = tc.get("params") or {}
            tool = tool_registry.get_tool(name)
            if tool is not None and tool.category == "write":
                if name not in _WA_SAFE_WRITES:
                    # Structural money/irreversible block.
                    lines.append(
                        "That action isn't available over WhatsApp.")
                    continue
                disp = tool_registry.dispatch(name, env_u, user, params)
                if disp.get("is_proposal"):
                    prop = self.env[
                        "neon.finance.ai.chat.write.log"].sudo().propose(
                            self._session(user), user, disp)
                    if prop.get("ok"):
                        rec = prop["record"]
                        cta_url = self._cta_url(rec)
                        lines.append(
                            (rec.human_summary or "Action ready")
                            + " - review & confirm in Odoo:")
                    else:
                        lines.append(prop.get(
                            "error", "Could not queue that action."))
                else:
                    lines.append(disp.get(
                        "error", "That action could not be prepared."))
            else:
                # Read tool (or unknown -> dispatch returns access/unknown
                # error). dispatch enforces user_can_call defensively.
                disp = tool_registry.dispatch(name, env_u, user, params)
                if disp.get("error"):
                    lines.append(disp["error"])
                else:
                    lines.append(self._format_read(name, disp))

        head = (result.assistant_message + "\n"
                if result.assistant_message else "")
        text = (head + "\n".join(lines)).strip() or "Done."
        return {"text": text, "cta_url": cta_url, "error": None}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _wa_provider(self):
        key = self.env["ir.config_parameter"].sudo().get_param(
            _WA_PROVIDER_PARAM, "google")
        return self.env["neon.dashboard.ai.provider"].sudo().search([
            ("provider_key", "=", key),
            ("is_enabled", "=", True),
        ], limit=1)

    def _session(self, user):
        """REUSE the user's existing chat.session purely as the write.log
        FK anchor (locked #1 -- no per-channel session, no core schema
        migration). WhatsApp conversation history lives in
        neon.whatsapp.message, not here."""
        return self.env[
            "neon.finance.ai.chat.session"].sudo().get_or_create_for_user(
                user.id)

    def _cta_url(self, rec):
        base = (self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url") or "").rstrip("/")
        action = self.env.ref(
            "neon_channels.action_wa_pending_writes",
            raise_if_not_found=False)
        suffix = f"&action={action.id}" if action else ""
        return (f"{base}/web#id={rec.id}"
                f"&model=neon.finance.ai.chat.write.log"
                f"&view_type=form{suffix}")

    def _build_messages(self, user, variant, text, phone):
        from odoo import fields  # noqa: PLC0415
        sys_prompt = _SYSTEM_PROMPT.format(
            role=(variant or "sales").replace("_", " ").title(),
            name=user.name or "",
            today=fields.Date.context_today(user).isoformat(),
        )
        messages = [{"role": "system", "content": sys_prompt}]
        rows = self.env["neon.whatsapp.message"].sudo().search(
            [("phone_number", "=", phone)],
            order="create_date desc, id desc", limit=_HISTORY_LIMIT)
        for m in reversed(rows):
            role = "user" if m.direction == "inbound" else "assistant"
            if m.message_body:
                messages.append({"role": role, "content": m.message_body})
        messages.append({"role": "user", "content": text or ""})
        return messages

    def _format_read(self, name, disp):
        """Compact text rendering of a read-tool result for WhatsApp.
        WA-1 can pretty-format per tool; WA-0 keeps it short + factual."""
        data = {k: v for k, v in disp.items()
                if k not in ("ok", "tool", "is_proposal")}
        if not data:
            return "No results."
        try:
            blob = json.dumps(data, default=str)
        except Exception:  # noqa: BLE001
            blob = str(data)
        return blob if len(blob) <= 600 else blob[:600] + "..."
