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
    ChatOrchestrator,
    _stored_variant_for,
)
from . import wa_payload  # WA-1: tap-back payload-id scheme
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
    "deal stage, post a note); the user confirms each one with a single "
    "tap here on WhatsApp, or by opening the link in Odoo -- it is never "
    "done without that explicit confirm. You cannot move money, send "
    "invoices, or take payments here. Today is {today}."
)

# ⚠️ DECISION (WA-1): WhatsApp moves from read+propose to
# read+propose+execute-on-tap, for REVERSIBLE CRM writes ONLY. A Confirm
# tap drives the IDENTICAL write.log propose->confirm->execute path the
# Odoo deep-link uses (consume_token: TTL + single-use + user-binding;
# execute under the user's identity so ACL fires). What makes this
# acceptable is unchanged + STRUCTURAL: money/irreversible tools are
# absent from _WA_SAFE_WRITES for every variant, so no tap can reach
# them. A tap is the confirm, never a bypass of the gate.

# WA-1 Slice 2 -- designated list-producing READ tools. VERIFIED output
# shapes (the dict-where-list bug class): get_my_pipeline nests leads
# under stages[].leads[]; get_jobs_this_week is flat rows[]. Each
# extractor returns a normalised [{id, title, description}]. (Equipment
# has NO list-shaped tool -- check_stock_availability is a category
# summary, not a pick-list -- so it is intentionally excluded.)
def _extract_pipeline_leads(res):
    out = []
    for st in (res.get("stages") or []):
        sname = st.get("stage") or ""
        for ld in (st.get("leads") or []):
            if not ld.get("id"):
                continue
            desc = " - ".join(x for x in [ld.get("partner_name") or "",
                                          sname] if x)
            out.append({"id": ld["id"], "title": ld.get("name") or "",
                        "description": desc})
    return out


def _extract_jobs(res):
    out = []
    for row in (res.get("rows") or []):
        if not row.get("event_job_id"):
            continue
        desc = " - ".join(x for x in [row.get("partner_name") or "",
                                      row.get("event_date") or "",
                                      row.get("state_label") or ""] if x)
        out.append({"id": row["event_job_id"], "title": row.get("ref") or "",
                    "description": desc})
    return out


_LIST_TOOLS = {
    "get_my_pipeline": {"extract": _extract_pipeline_leads,
                        "pick": "pick_lead", "label": "leads",
                        "button": "View leads"},
    "get_jobs_this_week": {"extract": _extract_jobs,
                           "pick": "pick_job", "label": "jobs",
                           "button": "View jobs"},
}

# WA-1 Slice 3 -- capability menu. Friendly label per tool (default
# humanises the name) + a canned invocation phrase routed through
# run_turn when the option is tapped. Built from whatsapp_tools(), so
# contents are already variant ∩ groups scoped -- money tools never
# appear because they are not in that set.
_MENU_LABELS = {
    "get_my_pipeline": "My pipeline",
    "get_open_quotes": "Open quotes",
    "get_quote_details": "Quote details",
    "get_overdue_invoices": "Overdue invoices",
    "get_pending_deposits": "Pending deposits",
    "get_jobs_this_week": "Jobs this week",
    "get_readiness_gates": "Job readiness",
    "get_crew_availability": "Crew availability",
    "get_cert_expiry": "Cert expiry",
    "check_stock_availability": "Stock availability",
    "get_budget_status": "Budget status",
    "get_partner_history": "Customer history",
    "get_dashboard_summary": "Dashboard summary",
    "get_zig_rate": "ZiG rate",
    "log_lead": "Log a lead",
    "move_stage": "Move a deal stage",
    "post_chatter_note": "Post a note",
}
_MENU_PHRASES = {
    "get_my_pipeline": "Show me my pipeline.",
    "get_open_quotes": "Show my open quotes.",
    "get_overdue_invoices": "Which invoices are overdue?",
    "get_pending_deposits": "Show pending deposits.",
    "get_jobs_this_week": "What jobs are on this week?",
    "get_readiness_gates": "Show job readiness.",
    "get_crew_availability": "Who's available in the crew?",
    "get_cert_expiry": "Which certifications are expiring?",
    "get_budget_status": "Show budget status.",
    "get_dashboard_summary": "Give me a dashboard summary.",
    "get_zig_rate": "What's the current ZiG rate?",
    "log_lead": "I'd like to log a new lead.",
    "move_stage": "I'd like to move a deal to another stage.",
    "post_chatter_note": "I'd like to post a note on a record.",
}
_MENU_TRIGGERS = {"menu", "help", "/menu", "/help", "what can you do",
                  "what can i do", "options", "commands",
                  "what can you help with"}


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
            # fed BACK to the model (never to the user). Some situations
            # are TERMINAL -- they end the turn with a structured
            # (interactive) reply instead of looping back to the model:
            #   * a reversible write proposal -> Confirm/Cancel buttons
            #   * a move_stage missing its target stage -> stage picker
            #     (the <=3-button quick-choice)
            #   * a list-producing read tool with >=2 rows -> pick list
            # All triggers are CODE-decided (not model-chosen) this round.
            terminal = None
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
                            t, tool_result = self._proposal_terminal(
                                user, disp, served_by)
                            if t and terminal is None:
                                terminal = t
                        else:
                            # Failed propose. A move_stage that just needs
                            # its target stage -> deterministic stage picker.
                            t = self._maybe_stage_picker(
                                env_u, user, name, params, disp, served_by)
                            if t and terminal is None:
                                terminal = t
                            tool_result = disp
                else:
                    # Read tool (dispatch enforces user_can_call defensively).
                    tool_result = tool_registry.dispatch(
                        name, env_u, user, params)
                    t = self._maybe_pick_list(name, tool_result, served_by)
                    if t and terminal is None:
                        terminal = t
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("tool_call_id") or "",
                    "name": name,
                    "content": json.dumps(tool_result, default=str),
                })

            if terminal is not None:
                # Structured reply: terminal, do NOT loop back to the model.
                return terminal
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

    # ==================================================================
    # WA-1 -- interactive renderer directives (Piece A, code-driven)
    # ==================================================================
    def _secret(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "database.secret") or ""

    def _payload(self, intent, *parts):
        return wa_payload.encode(self._secret(), intent, *parts)

    def _safe(self, text):
        """A graceful, structured-free reply (used for fallbacks + the
        fail-safe tap routes). NOT an error to the user."""
        return {"text": text, "cta_url": None, "interactive": None,
                "text_fallback": text, "error": None, "provider_key": None}

    def _confirm_result(self, rec, cta_url, served_by):
        """Confirm/Cancel reply buttons for a reversible write proposal.
        The cta_url 'open in Odoo' link rides in the body (an option the
        user can still take) AND is the text fallback (Piece C)."""
        summary = rec.human_summary or "Action ready"
        body = ("%s\n\nTap Confirm to action it now, or open in Odoo:\n%s"
                % (summary, cta_url))
        interactive = {
            "kind": "buttons",
            "body": body[:1024],
            "buttons": [
                {"id": self._payload("confirm", rec.confirmation_token),
                 "title": "✅ Confirm"},
                {"id": self._payload("cancel", rec.confirmation_token),
                 "title": "❌ Cancel"},
            ],
        }
        text_fallback = ("%s -- review & confirm in Odoo: %s"
                         % (summary, cta_url))
        return {"text": summary + " - confirm below.", "cta_url": cta_url,
                "interactive": interactive, "text_fallback": text_fallback,
                "error": None, "provider_key": served_by}

    def _proposal_terminal(self, user, disp, served_by):
        """Persist a write proposal to write.log and return
        (terminal_result_or_None, tool_result_for_model)."""
        prop = self.env["neon.finance.ai.chat.write.log"].sudo().propose(
            self._session(user), user, disp)
        if not prop.get("ok"):
            return (None, {"ok": False, "error": prop.get(
                "error", "could not queue action")})
        rec = prop["record"]
        terminal = self._confirm_result(rec, self._cta_url(rec), served_by)
        return (terminal, {"ok": True, "proposed": True,
                           "summary": rec.human_summary})

    def _stage_label(self, stage):
        if not stage:
            return ""
        name = stage.name or ""
        if isinstance(name, dict):  # crm.stage.name is a JSONB translation
            return name.get("en_US") or next(iter(name.values()), "")
        return str(name)

    def _resolve_one_lead(self, env_u, ident):
        ident = (ident or "").strip()
        if not ident:
            return None
        Lead = env_u["crm.lead"]
        if ident.isdigit():
            rec = Lead.browse(int(ident))
            return rec if rec.exists() else None
        matches = Lead.search(
            [("name", "ilike", ident), ("active", "=", True)], limit=2)
        return matches if len(matches) == 1 else None

    def _forward_stages(self, env_u, lead):
        cur = lead.stage_id.sequence if lead.stage_id else -1
        return env_u["crm.stage"].search(
            [("sequence", ">", cur)], order="sequence, id", limit=3)

    def _maybe_stage_picker(self, env_u, user, name, params, disp,
                            served_by):
        """move_stage failed because the target stage was missing /
        ambiguous, but the lead resolved uniquely with 2-3 forward
        stages -> emit the <=3-button stage picker."""
        if name != "move_stage" or disp.get("ok"):
            return None
        if "stage" not in (disp.get("error") or "").lower():
            return None
        lead = self._resolve_one_lead(env_u, params.get("lead_identifier"))
        if not lead:
            return None
        stages = self._forward_stages(env_u, lead)
        if not (2 <= len(stages) <= 3):
            return None
        buttons = [{"id": self._payload("stage", lead.id, s.id),
                    "title": self._stage_label(s)[:20]} for s in stages]
        interactive = {
            "kind": "buttons",
            "body": ("Which stage should '%s' move to?" % lead.name)[:1024],
            "buttons": buttons,
        }
        fallback = ("Reply with the target stage for '%s': %s"
                    % (lead.name, ", ".join(
                        self._stage_label(s) for s in stages)))
        return {"text": "Pick a stage:", "cta_url": None,
                "interactive": interactive, "text_fallback": fallback,
                "error": None, "provider_key": served_by}

    def _maybe_pick_list(self, name, tool_result, served_by):
        """A designated list-producing read tool returned >=2 rows ->
        emit a pick-list. >10 -> first 10 + an explicit note (no silent
        truncation). <=1 -> None (let the model answer normally)."""
        spec = _LIST_TOOLS.get(name)
        if not spec or not isinstance(tool_result, dict) \
                or not tool_result.get("ok"):
            return None
        rows = spec["extract"](tool_result)
        if len(rows) < 2:
            return None
        truncated = len(rows) > 10
        capped = rows[:10]
        if truncated:
            _logger.info(
                "WA pick-list %s: %d rows, showing first 10 (refine in "
                "Odoo) -- no silent truncation.", name, len(rows))
        pick = spec["pick"]
        list_rows = [{"id": self._payload(pick, r["id"]),
                      "title": (r["title"] or str(r["id"]))[:24],
                      "description": (r.get("description") or "")[:72]}
                     for r in capped]
        body = ("Found %d %s%s. Tap to choose one:"
                % (len(rows), spec["label"],
                   " (showing first 10)" if truncated else ""))
        interactive = {
            "kind": "list", "body": body[:1024],
            "button_text": spec["button"][:20],
            "sections": [{"title": spec["label"][:24], "rows": list_rows}],
        }
        lines = ["%d. %s%s" % (
            i + 1, r["title"],
            (" - " + r["description"]) if r.get("description") else "")
            for i, r in enumerate(capped)]
        fallback = body + "\n" + "\n".join(lines) + "\nReply with the name."
        return {"text": body, "cta_url": None, "interactive": interactive,
                "text_fallback": fallback, "error": None,
                "provider_key": served_by}

    # ==================================================================
    # WA-1 -- capability menu (Piece A / Slice 3)
    # ==================================================================
    def wants_menu(self, text):
        t = (text or "").strip().lower().rstrip(" ?!.")
        return t in {x.rstrip(" ?!.") for x in _MENU_TRIGGERS}

    def build_menu_result(self, bot_user):
        user = bot_user.user_id
        variant = self.variant_for(user)
        tools = self.whatsapp_tools(user, variant)
        opts = [(t.name, _MENU_LABELS.get(
            t.name, t.name.replace("get_", "").replace("_", " ").title()))
            for t in tools]
        if not opts:
            return self._safe(
                "You can ask me about your work and I'll help where I can.")
        body = ("Here's what I can help with, %s. Tap an option:"
                % (user.name or "there"))
        if len(opts) <= 3:
            buttons = [{"id": self._payload("menu", k), "title": lbl[:20]}
                       for k, lbl in opts[:3]]
            interactive = {"kind": "buttons", "body": body[:1024],
                           "buttons": buttons}
        else:
            shown = opts[:10]
            rows = [{"id": self._payload("menu", k), "title": lbl[:24],
                     "description": ""} for k, lbl in shown]
            if len(opts) > 10:
                body += " (and more -- just ask)"
            interactive = {"kind": "list", "body": body[:1024],
                           "button_text": "Options",
                           "sections": [{"title": "What I can do",
                                         "rows": rows}]}
        fallback = body + "\n" + "\n".join(
            "- %s" % lbl for _, lbl in opts[:10])
        return {"text": body, "cta_url": None, "interactive": interactive,
                "text_fallback": fallback, "error": None,
                "provider_key": None}

    # ==================================================================
    # WA-1 -- tap-back inbound router (Piece B, THE real risk)
    # ==================================================================
    def handle_tap(self, bot_user, reply_id, reply_title=None):
        """Route a tapped button/list reply id back to the right action.
        Unknown/expired/tampered id -> safe fallback, never a crash or a
        mis-route (same fail-safe discipline as the resolver)."""
        user = bot_user.user_id
        decoded = wa_payload.decode(self._secret(), reply_id)
        if not decoded:
            return self._safe(
                "I couldn't read that selection -- please type your "
                "request and I'll help.")
        intent, parts = decoded
        try:
            if intent in ("confirm", "cancel"):
                return self._tap_confirm(user, intent, parts)
            if intent == "stage":
                return self._tap_stage(bot_user, parts)
            if intent in ("pick_lead", "pick_job"):
                return self._tap_pick(bot_user, intent, parts, reply_title)
            if intent == "menu":
                return self._tap_menu(bot_user, parts)
        except Exception as e:  # noqa: BLE001 -- a tap must never 500
            _logger.error("WA tap routing failed (intent=%s): %s",
                          intent, e, exc_info=True)
            return self._safe(
                "Sorry -- something went wrong with that. Please try again.")
        return self._safe(
            "I couldn't route that selection -- please type your request.")

    def _tap_confirm(self, user, intent, parts):
        token = parts[0] if parts else ""
        # Execute under the RESOLVED USER's identity (not the sudo webhook
        # env) so the write's ACL fires at execute time -- same guarantee
        # as the WA-0 'confirm in Odoo' deep-link path.
        orch = ChatOrchestrator(self.env(user=user.id))
        if intent == "cancel":
            res = orch.cancel_pending_action(user, token)
        else:
            res = orch.confirm_pending_action(user, token)
        return self._safe(self._confirm_reply_text(intent, res))

    def _confirm_reply_text(self, intent, res):
        code = res.get("error_code")
        status = res.get("status")
        summ = (res.get("result") or {}).get("human_summary") or ""
        if res.get("ok") and status == "executed":
            return "✅ Done%s." % ((" -- " + summ) if summ else "")
        if res.get("ok") and status == "cancelled":
            return "❌ Cancelled%s." % ((" -- " + summ) if summ else "")
        if res.get("ok") and res.get("replay"):
            return "That action was already %s." % (status or "handled")
        if code == "expired":
            return ("⏳ That action expired -- just ask again and I'll "
                    "re-prepare it.")
        if code == "not_found":
            return ("I couldn't find that action -- it may already have "
                    "been handled.")
        if code == "forbidden":
            return "That action belongs to a different user."
        return ("Sorry -- I couldn't complete that: %s"
                % (res.get("error") or "unknown error"))

    def _propose_and_confirm(self, user, env_u, tool_name, params):
        """Dispatch a WA-safe write tool -> propose -> Confirm/Cancel
        buttons. Reused by the stage tap (a tap can only PROPOSE; the
        confirm gate still fires)."""
        if tool_name not in _WA_SAFE_WRITES:
            return self._safe("That action isn't available over WhatsApp.")
        disp = tool_registry.dispatch(tool_name, env_u, user, params)
        if not disp.get("is_proposal"):
            return self._safe(
                disp.get("error") or "I couldn't prepare that action.")
        terminal, _ = self._proposal_terminal(user, disp, None)
        return terminal or self._safe(
            "I couldn't queue that action -- please try again.")

    def _tap_stage(self, bot_user, parts):
        user = bot_user.user_id
        env_u = self.env(user=user.id)
        if len(parts) < 2:
            return self._safe(
                "That stage selection was incomplete -- please try again.")
        lead_id, stage_id = parts[0], parts[1]
        stage = (env_u["crm.stage"].browse(int(stage_id))
                 if str(stage_id).isdigit() else None)
        if not (stage and stage.exists()):
            return self._safe(
                "That stage is no longer available -- please try again.")
        return self._propose_and_confirm(
            user, env_u, "move_stage",
            {"lead_identifier": str(lead_id),
             "target_stage": self._stage_label(stage)})

    def _tap_pick(self, bot_user, intent, parts, reply_title):
        """List selection -> feed the chosen record id back into a
        steered turn (no name-typing). The model continues with WA-1
        history + the explicit selection."""
        user = bot_user.user_id
        env_u = self.env(user=user.id)
        rid = parts[0] if parts else ""
        if not str(rid).isdigit():
            return self._safe(
                "That selection was invalid -- please type your request.")
        model = "crm.lead" if intent == "pick_lead" \
            else "commercial.event.job"
        label = "lead" if intent == "pick_lead" else "job"
        try:
            rec = env_u[model].browse(int(rid))
            if not rec.exists():
                raise ValueError("gone")
            name = reply_title or rec.name or ("#%s" % rid)
        except Exception:  # noqa: BLE001 -- ACL or gone -> safe fallback
            return self._safe(
                "That item is no longer available -- please type your "
                "request.")
        steer = "Let's work with %s '%s' (id %s)." % (label, name, rid)
        return self.run_turn(bot_user, steer)

    def _tap_menu(self, bot_user, parts):
        user = bot_user.user_id
        variant = self.variant_for(user)
        key = parts[0] if parts else ""
        allowed = {t.name for t in self.whatsapp_tools(user, variant)}
        if key not in allowed:
            return self._safe("That option isn't available for your role.")
        phrase = _MENU_PHRASES.get(
            key, "Please help me with: %s" % key.replace("_", " "))
        return self.run_turn(bot_user, phrase)
