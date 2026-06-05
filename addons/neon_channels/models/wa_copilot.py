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
from .phone_utils import to_e164  # WA-1: single-source phone normalization


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

# WA-1 conversation memory window (locked): last 10 messages within the
# last 30 min, oldest-first, both inbound + outbound. Bounds free-tier
# token cost + keeps context recent. Configurable.
_HISTORY_LIMIT = 10
_HISTORY_WINDOW_MIN = 30

# WA-0 tool-use loop: model -> tool_call -> dispatch -> tool result ->
# model again -> NL text. Capped so a tool-calling model can't loop
# forever. Up to this many model calls per inbound turn (only when tools
# are used); each call still has Gemini retry + Groq fallback.
_MAX_TOOL_ITERATIONS = 3

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
        """phone_number -> active neon.bot.user via canonical E.164 match.

        ⚠️ DECISION (WA-1): normalise both sides through the shared
        to_e164 helper (single source of truth, replacing the WA-0 ad-hoc
        digits-only re.sub). With WA-1 boundary normalization the stored
        data is canonical too, but resolve() still normalises defensively
        so it's correct regardless of caller / stored formatting.

        ⚠️ DECISION (WA-0 fix, RBAC safety): this resolver IS the
        privilege gate. >1 normalised match -> UNRESOLVED (treat as
        raw-lead) rather than guess -- a mis-resolution would be a
        privilege mis-attribution. Never pick one of several.
        """
        target = to_e164(phone or "")
        if not target:
            return self.env["neon.bot.user"]
        candidates = self.env["neon.bot.user"].sudo().search(
            [("active", "=", True)])
        matches = candidates.filtered(
            lambda r: to_e164(r.phone_number or "") == target)
        if len(matches) != 1:
            if len(matches) > 1:
                _logger.warning(
                    "WA resolve: %d active bot.users share E.164 %s -- "
                    "treating as UNRESOLVED (RBAC safety).",
                    len(matches), target)
            return self.env["neon.bot.user"]
        return matches

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
    def run_turn(self, bot_user, inbound_text, exclude_message_id=None):
        """Drive one privileged inbound turn through the full tool-use
        loop: model -> tool_call -> dispatch -> append tool result ->
        model again -> return the model's NATURAL-LANGUAGE text. Capped at
        _MAX_TOOL_ITERATIONS. A raw tool/JSON payload is NEVER sent to the
        user -- tool results go BACK to the model, not to WhatsApp.
        ``exclude_message_id`` is the just-created inbound row, excluded
        from its own history (WA-1 double-count fix).
        Returns {"text", "cta_url", "error", "provider_key"}."""
        user = bot_user.user_id
        env_u = self.env(user=user.id)
        variant = self.variant_for(user)
        schemas = tool_registry.groq_tool_schemas(
            tools=self.whatsapp_tools(user, variant))
        messages = self._build_messages(
            user, variant, inbound_text, bot_user.phone_number,
            exclude_message_id=exclude_message_id)

        served_by = None
        last = None
        for iteration in range(_MAX_TOOL_ITERATIONS):
            result, served_by = self._provider_chat(messages, schemas)
            last = result
            if result is None or not result.success:
                _logger.warning(
                    "WA: all providers failed for %s; err=%s", user.login,
                    (result.error_message if result is not None else "n/a"))
                return {"text": "Sorry -- I can't reach the assistant right "
                                "now. Please try again shortly.",
                        "cta_url": None, "provider_key": served_by,
                        "error": (result.error_message
                                  if result is not None else "no_provider")}

            # Final natural-language turn (text, no tool calls).
            if not result.tool_calls:
                _logger.info("WA: turn served by %s (%dms, iters=%d)",
                             served_by, result.latency_ms or 0, iteration + 1)
                return {"text": result.assistant_message or "Done.",
                        "cta_url": None, "error": None,
                        "provider_key": served_by}

            # Record the assistant tool-call turn (OpenAI shape; both
            # adapters consume it -- Gemini functionCall, Groq tool_calls).
            messages.append({
                "role": "assistant",
                "content": result.assistant_message or "",
                "tool_calls": [{
                    "id": tc["tool_call_id"], "type": "function",
                    "function": {"name": tc["tool_name"],
                                 "arguments": json.dumps(tc["params"])},
                } for tc in result.tool_calls],
            })

            # Dispatch each call; append its result as a tool-role message
            # fed BACK to the model (never to the user). A write proposal
            # is TERMINAL -- ends the turn with a confirm-in-Odoo cta_url.
            saw_proposal = False
            cta_url = None
            steer = None
            for tc in result.tool_calls:
                name = tc.get("tool_name") or ""
                params = tc.get("params") or {}
                tool = tool_registry.get_tool(name)
                if tool is not None and tool.category == "write":
                    if name not in _WA_SAFE_WRITES:
                        tool_result = {"ok": False,
                                       "error": "not available over WhatsApp"}
                    else:
                        disp = tool_registry.dispatch(
                            name, env_u, user, params)
                        if disp.get("is_proposal"):
                            prop = self.env[
                                "neon.finance.ai.chat.write.log"].sudo(
                            ).propose(self._session(user), user, disp)
                            if prop.get("ok"):
                                rec = prop["record"]
                                cta_url = self._cta_url(rec)
                                steer = ((rec.human_summary or "Action ready")
                                         + " - review & confirm in Odoo.")
                                saw_proposal = True
                                tool_result = {"ok": True, "proposed": True,
                                               "summary": rec.human_summary}
                            else:
                                tool_result = {"ok": False, "error": prop.get(
                                    "error", "could not queue action")}
                        else:
                            tool_result = disp
                else:
                    # Read tool (dispatch enforces user_can_call defensively).
                    tool_result = tool_registry.dispatch(
                        name, env_u, user, params)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("tool_call_id") or "",
                    "name": name,
                    "content": json.dumps(tool_result, default=str),
                })

            if saw_proposal:
                # Confirm-in-Odoo: terminal, do NOT loop back to the model.
                return {"text": steer or ("I have an action ready - please "
                                          "confirm it in Odoo."),
                        "cta_url": cta_url, "error": None,
                        "provider_key": served_by}
            # else: loop -- model receives the tool results, replies in NL.

        # Iteration cap -- graceful, NEVER raw JSON / tool output.
        _logger.info("WA: tool-loop cap (%d) reached for %s",
                     _MAX_TOOL_ITERATIONS, user.login)
        return {"text": (last.assistant_message if last
                         and last.assistant_message else
                         "I've gathered the details - could you rephrase "
                         "what you'd like?"),
                "cta_url": None, "error": "tool_loop_exhausted",
                "provider_key": served_by}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _fallback_adapter(self, exclude=None):
        """Resilience fallback provider (Groq) for when the WhatsApp
        primary (Gemini) fails after its retries. Returns (adapter, key)
        or None. Groq is enabled + keyed (the dashboard Copilot default);
        this does NOT change the Copilot's provider. Skipped if Groq is
        already the primary (``exclude``)."""
        prov = self.env["neon.dashboard.ai.provider"].sudo().search([
            ("provider_key", "=", "groq"),
            ("is_enabled", "=", True),
        ], limit=1)
        if prov and prov.provider_key != exclude:
            adapter = get_chat_adapter(prov)
            if adapter:
                return adapter, prov.provider_key
        return None

    def _provider_chat(self, messages, schemas):
        """One model call with Groq fallback. Returns (result, served_by).
        Gemini self-retries 503/429; if it still fails (or is
        unconfigured), fall back to Groq. Called once per tool-loop
        iteration; messages are OpenAI-shaped so either provider consumes
        the same array."""
        provider = self._wa_provider()
        adapter = get_chat_adapter(provider) if provider else None
        served_by = provider.provider_key if provider else None
        result = adapter.chat(messages, tools=schemas) if adapter else None
        if result is None or not result.success:
            primary_err = (result.error_message if result is not None
                           else "no WhatsApp provider configured")
            fb = self._fallback_adapter(exclude=served_by)
            if fb:
                fb_adapter, fb_key = fb
                _logger.warning(
                    "WA: provider %s failed (%s) -- falling back to %s",
                    served_by or "none", primary_err, fb_key)
                result = fb_adapter.chat(messages, tools=schemas)
                served_by = fb_key
        return result, served_by

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

    def _build_messages(self, user, variant, text, phone,
                        exclude_message_id=None):
        from odoo import fields  # noqa: PLC0415
        sys_prompt = _SYSTEM_PROMPT.format(
            role=(variant or "sales").replace("_", " ").title(),
            name=user.name or "",
            today=fields.Date.context_today(user).isoformat(),
        )
        messages = [{"role": "system", "content": sys_prompt}]
        # WA-1 conversation memory: last _HISTORY_LIMIT messages within
        # _HISTORY_WINDOW_MIN minutes for THIS sender (canonical E.164),
        # oldest-first, inbound + outbound. Exclude the just-created
        # inbound row so the current turn isn't double-counted (it's
        # appended below). Matches now that the stored phone is canonical.
        canon = to_e164(phone or "")
        domain = [("phone_number", "=", canon)]
        if exclude_message_id:
            domain.append(("id", "!=", exclude_message_id))
        cutoff = fields.Datetime.subtract(
            fields.Datetime.now(), minutes=_HISTORY_WINDOW_MIN)
        domain.append(("create_date", ">=", cutoff))
        rows = self.env["neon.whatsapp.message"].sudo().search(
            domain, order="create_date desc, id desc", limit=_HISTORY_LIMIT)
        for m in reversed(rows):
            role = "user" if m.direction == "inbound" else "assistant"
            if m.message_body:
                messages.append({"role": role, "content": m.message_body})
        messages.append({"role": "user", "content": text or ""})
        return messages
