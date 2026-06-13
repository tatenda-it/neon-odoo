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
import re

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
    "WhatsApp. You KNOW this user: they are {name}, {role} at Neon Events "
    "Elements (resolved from their registered WhatsApp number) -- if they "
    "ask whether you know them or who they are, answer with their name "
    "and role; NEVER say you have no information about them. Neon Events "
    "Elements is an event-production company in "
    "Harare, Zimbabwe. Keep replies short (1-3 sentences) and "
    "professional -- this is a phone chat. Use tools to answer factual "
    "questions; never invent numbers, names, or dates. Currency: USD or "
    "ZiG; VAT 15.5%. You can prepare reversible actions (log a lead, move a "
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
# A bare GREETING is basic navigation -- it must NOT depend on the LLM (a
# quoting bot can't go dark on an AI blip). Tight EQUALS on a small set (after
# strip/lower/trailing-punctuation): "hello can you quote X" is a real request,
# not a greeting, and still routes to the Copilot / WA-12. Mirrors the
# wants_menu discipline.
_GREETINGS = {"hi", "hii", "hie", "hey", "yo", "hello", "helo", "hallo",
              "hi there", "hello there", "hey there", "greetings",
              "good morning", "good afternoon", "good evening", "good day",
              "morning", "afternoon", "evening", "start", "/start"}

# ======================================================================
# WA-4 -- dual-role lens routing constants
# ======================================================================
# A user's tier groups -> the variants ("lenses") they hold. Mirrors
# neon.dashboard._default_dashboard_type_for_user, but collected as a SET
# (not a precedence pick). superuser short-circuits to director-only (they
# already get all tools; never narrow them). 'hr'/'tech' have no Copilot
# TOOLS_BY_VARIANT entry, so their lens = all-entitled (the ["*"] fallback)
# -- WA-4 does NOT change that (Gate-1 decision 2).
_LENS_GROUP_MAP = [
    # (variant, [group xmlids that grant it])
    ("hr", ["neon_hr.group_neon_hr_admin", "hr.group_hr_manager"]),
    ("bookkeeper", ["neon_core.group_neon_bookkeeper"]),
    ("lead_tech", ["neon_core.group_neon_lead_tech"]),
    ("tech", ["neon_core.group_neon_crew"]),
    ("sales", ["neon_core.group_neon_sales_rep"]),
]
_LENS_SUPERUSER_GROUP = "neon_core.group_neon_superuser"

# Display labels for the lens (system-prompt persona + the "as ..."
# surface). Nicer than variant.title() (e.g. 'hr' -> 'HR', not 'Hr').
LENS_LABEL = {
    "director": "Director", "sales": "Sales", "bookkeeper": "Bookkeeper",
    "lead_tech": "Lead Tech", "tech": "Tech", "hr": "HR",
}

# Intent -> lens. v1 distinguishes the only live dual-role (finance vs HR).
_INTENT_LENS = {"finance": "bookkeeper", "hr": "hr"}

# Rule-based intent keywords (EDITABLE -- tune from real
# misclassifications). Matched as whole-word, case-insensitive.
FINANCE_KEYWORDS = {
    "invoice", "invoices", "vat", "payment", "payments", "pay", "paid",
    "cost", "costs", "quote", "quotes", "quotation", "expense", "expenses",
    "reconcile", "reconciliation", "deposit", "deposits", "budget",
    "budgets", "zig", "rate", "overdue", "billing", "bill", "ledger",
    "credit", "debit", "refund", "tax", "receivable", "payable", "usd",
}
HR_KEYWORDS = {
    "leave", "payroll", "employee", "employees", "attendance", "contract",
    "contracts", "salary", "salaries", "wage", "wages", "staff", "hire",
    "hiring", "sick", "absence", "roster", "appraisal", "disciplinary",
    "nssa", "loan", "loans", "timesheet", "onboarding", "hr",
}

# Explicit-override prefixes (case-insensitive, at message start). Her
# word beats the classifier. Maps prefix -> lens.
_OVERRIDE_PREFIXES = [
    ("as bookkeeper", "bookkeeper"), ("as finance", "bookkeeper"),
    ("bookkeeper:", "bookkeeper"), ("finance:", "bookkeeper"),
    ("as hr admin", "hr"), ("as hr", "hr"), ("hr:", "hr"),
]


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

    # ------------------------------------------------------------------
    # WA-4 -- dual-role lens routing
    # ------------------------------------------------------------------
    def _held_lenses(self, user):
        """The SET of variants ("lenses") the user's tier groups grant.
        Superuser -> {director} (already all-tools; never narrow them).
        < 2 lenses => single-role => NO routing (today's behaviour)."""
        if user.has_group(_LENS_SUPERUSER_GROUP):
            return {"director"}
        held = set()
        for variant, groups in _LENS_GROUP_MAP:
            if any(user.has_group(g) for g in groups
                   if self.env.ref(g, raise_if_not_found=False)):
                held.add(variant)
        return held

    @staticmethod
    def classify_intent(text):
        """Rule-based, deterministic: 'finance' | 'hr' | None. None when
        BOTH or NEITHER keyword set matches (ambiguous -> ask)."""
        words = set(re.findall(r"[a-z]+", (text or "").lower()))
        fin = bool(words & FINANCE_KEYWORDS)
        hr = bool(words & HR_KEYWORDS)
        if fin and not hr:
            return "finance"
        if hr and not fin:
            return "hr"
        return None

    @staticmethod
    def _explicit_override(text):
        """Leading 'as bookkeeper' / 'finance:' / 'as hr' ... -> (lens,
        stripped_text). Her word beats the classifier. Else None."""
        low = (text or "").lstrip().lower()
        for prefix, lens in _OVERRIDE_PREFIXES:
            if low.startswith(prefix):
                stripped = (text or "").lstrip()[len(prefix):].lstrip(" :,-")
                return (lens, stripped or (text or ""))
        return None

    def resolve_lens(self, bot_user, text, inbound_msg_id):
        """Pick the per-turn lens for a multi-role user. Returns a dict:
        {variant, ask, routed, text}. Single-role -> today's variant_for,
        no routing. Override wins; clear intent -> that lens; ambiguous /
        intent-for-an-unheld-lens -> a 2-button ask (reuses the WA-1
        renderer). NEVER picks a lens the user doesn't hold."""
        user = bot_user.user_id
        held = self._held_lenses(user)
        if len(held) < 2:
            return {"variant": self.variant_for(user), "ask": None,
                    "routed": False, "text": text}
        # explicit override (only if the user holds that lens)
        ov = self._explicit_override(text)
        if ov and ov[0] in held:
            return {"variant": ov[0], "ask": None, "routed": True,
                    "text": ov[1]}
        # rule-based intent -> lens, only if held
        lens = _INTENT_LENS.get(self.classify_intent(text))
        if lens and lens in held:
            return {"variant": lens, "ask": None, "routed": True,
                    "text": text}
        # ambiguous -> ask among the lenses she holds
        return {"variant": None, "ask": self._build_lens_ask(held,
                inbound_msg_id), "routed": True, "text": text}

    def _build_lens_ask(self, held, inbound_msg_id):
        """A pick among the user's held lenses, carrying
        lens:<variant>:<inbound_msg_id> so the tap re-runs the original
        message under the chosen lens. <=3 -> buttons, else list."""
        opts = [(v, LENS_LABEL.get(v, v.title())) for v in sorted(held)]
        body = "Quick check — should I answer as " + " or ".join(
            lbl for _, lbl in opts) + "?"
        if len(opts) <= 3:
            buttons = [{"id": self._payload("lens", v, inbound_msg_id),
                        "title": lbl[:20]} for v, lbl in opts]
            interactive = {"kind": "buttons", "body": body[:1024],
                           "buttons": buttons}
        else:
            rows = [{"id": self._payload("lens", v, inbound_msg_id),
                     "title": lbl[:24], "description": ""}
                    for v, lbl in opts]
            interactive = {"kind": "list", "body": body[:1024],
                           "button_text": "Pick a lens",
                           "sections": [{"title": "Answer as", "rows": rows}]}
        fallback = body + "\n" + " / ".join(lbl for _, lbl in opts)
        return {"text": body, "cta_url": None, "interactive": interactive,
                "text_fallback": fallback, "error": None,
                "provider_key": None}

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
    def run_turn(self, bot_user, inbound_text, exclude_message_id=None,
                 variant=None, lens_routed=False):
        """Drive one privileged inbound turn through the full tool-use
        loop: model -> tool_call -> dispatch -> append tool result ->
        model again -> return the model's NATURAL-LANGUAGE text. Capped at
        _MAX_TOOL_ITERATIONS. A raw tool/JSON payload is NEVER sent to the
        user -- tool results go BACK to the model, not to WhatsApp.
        ``exclude_message_id`` is the just-created inbound row, excluded
        from its own history (WA-1 double-count fix).

        WA-4: ``variant`` overrides the default lens for THIS turn (None =
        today's variant_for resolution; all pre-WA-4 callers pass nothing,
        so single-role behaviour is byte-identical). ``lens_routed`` flags
        a multi-role routed turn so the reply surfaces the chosen lens.
        Returns {"text", "cta_url", "error", "provider_key"}."""
        user = bot_user.user_id
        env_u = self.env(user=user.id)
        variant = variant or self.variant_for(user)
        # WA-4: surface the routed lens on the reply ("🔖 as Bookkeeper").
        lens_prefix = (("🔖 as %s\n" % LENS_LABEL.get(variant, variant))
                       if lens_routed else "")
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
                err = (result.error_message if result is not None
                       else "no_provider")
                _logger.warning(
                    "WA: all providers failed for %s; err=%s", user.login, err)
                # DON'T dead-end (a quoting bot can't go dark on an LLM blip).
                # Degrade to the DETERMINISTIC capability menu -- the Quote /
                # crew / availability commands are deterministic interceptors
                # that work without the LLM; only the free-form AI chat is
                # down. Basic navigation stays alive. Thread the routed lens so
                # a multi-role user keeps that lens's tools + marker.
                return self._degraded_menu(
                    bot_user, variant, err, lens_routed=lens_routed)

            # Final natural-language turn (text, no tool calls).
            if not result.tool_calls:
                _logger.info("WA: turn served by %s (%dms, iters=%d)",
                             served_by, result.latency_ms or 0, iteration + 1)
                return {"text": lens_prefix
                        + (result.assistant_message or "Done."),
                        "cta_url": None, "error": None,
                        "variant": variant, "provider_key": served_by}

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
                # WA-4 audit fidelity: stamp the lens actually applied.
                terminal.setdefault("variant", variant)
                return terminal
            # else: loop -- model receives the tool results, replies in NL.

        # Iteration cap -- graceful, NEVER raw JSON / tool output.
        _logger.info("WA: tool-loop cap (%d) reached for %s",
                     _MAX_TOOL_ITERATIONS, user.login)
        return {"text": lens_prefix + (last.assistant_message if last
                         and last.assistant_message else
                         "I've gathered the details - could you rephrase "
                         "what you'd like?"),
                "cta_url": None, "error": "tool_loop_exhausted",
                "variant": variant, "provider_key": served_by}

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

    def _wa_role_from_groups(self, user):
        """A human role label for the greeting when the partner has no Job
        Position. Resolved from the user's GROUPS by XML id (never numeric ids
        -- install-order drift), most-senior first; the first held group wins.
        Returns '' if none match (caller then falls to the lens label). NEVER
        returns 'Director' for a plain sales user (the M-E finding)."""
        # (xmlid, label) ordered by JOB role, NOT technical privilege: a user
        # whose function is blank but who works in sales must greet as "Sales",
        # even though they ALSO hold superuser (Tatenda, the dev). So the
        # functional roles lead and group_neon_superuser is the LAST resort
        # (only a pure-superuser with no job group lands on "Director"). XML ids
        # verified live; has_group raises ValueError on an absent ref -> skip.
        ladder = [
            ("neon_finance.group_neon_finance_sales", "Sales"),
            ("neon_finance.group_neon_finance_bookkeeper", "Bookkeeper"),
            ("neon_finance.group_neon_finance_approver", "Finance"),
            ("neon_jobs.group_neon_jobs_crew_leader", "Lead Tech"),
            ("neon_jobs.group_neon_jobs_manager", "Operations Manager"),
            ("neon_core.group_neon_superuser", "Director"),
        ]
        for xmlid, label in ladder:
            try:
                if user.has_group(xmlid):
                    return label
            except ValueError:
                continue  # group ref absent in this install -> skip
        return ""

    def _build_messages(self, user, variant, text, phone,
                        exclude_message_id=None):
        from odoo import fields  # noqa: PLC0415
        # M2/M-E identity: prefer the partner's Job Position (exact org titles --
        # e.g. "Operational Director" / "Managing Director"); when it's EMPTY,
        # resolve the role from the user's groups (so Tatenda, function blank +
        # in Sales, greets as "Sales", NOT the lens-default "Director" -- the
        # live-wire M-E finding). The lens label is the last resort.
        role = ((user.partner_id.function or "").strip()
                or self._wa_role_from_groups(user)
                or LENS_LABEL.get(
                    variant, (variant or "sales").replace("_", " ").title()))
        sys_prompt = _SYSTEM_PROMPT.format(
            role=role,
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

    def is_greeting(self, text):
        """A bare greeting (deterministic, LLM-independent). Tight EQUALS on
        _GREETINGS after strip/lower/trailing-punctuation -- a greeting glued to
        a real request ('hello can you quote X') is NOT a greeting and routes on
        to the Copilot / WA-12 as before."""
        t = (text or "").strip().lower().rstrip(" ?!.,")
        return t in {x.rstrip(" ?!.,") for x in _GREETINGS}

    def build_menu_result(self, bot_user, prefix="", variant=None):
        """``prefix`` (optional) is prepended to the body + text fallback: a
        warm greeting for the greeting fast-path, or the 'AI briefly
        unavailable' note for the LLM-down degrade. ``variant`` (optional) keeps
        the lens the turn was running under (the degrade path threads the ROUTED
        lens so a multi-role user sees that lens's tools, not the default);
        greeting callers pass nothing and keep variant_for. The menu itself is
        DETERMINISTIC (tool registry, no LLM)."""
        user = bot_user.user_id
        variant = variant or self.variant_for(user)
        tools = self.whatsapp_tools(user, variant)
        opts = [(t.name, _MENU_LABELS.get(
            t.name, t.name.replace("get_", "").replace("_", " ").title()))
            for t in tools]
        if not opts:
            return self._safe(
                (prefix or "") +
                "You can ask me about your work and I'll help where I can.")
        body = (prefix + "Here's what I can help with, %s. Tap an option:"
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

    def _degraded_menu(self, bot_user, variant, error_msg=None,
                       lens_routed=False):
        """LLM (Groq) unreachable -> DON'T dead-end. The AI is OPTIONAL: degrade
        to the DETERMINISTIC capability menu so the bot stays useful. The Quote /
        crew / availability / feedback faces are all deterministic interceptors
        that run WITHOUT the LLM; only the free-form AI chat is down. Threads the
        turn's ROUTED ``variant`` so a multi-role user keeps that lens's tools
        (not the default), re-surfaces the lens marker, and carries the provider
        error for the outbound audit row. NOTE: no trailing 'Tap an option:' in
        the prefix -- build_menu_result adds it when there ARE options, and the
        no-tools branch then reads cleanly (no 'tap' with nothing to tap)."""
        marker = (("🔖 as %s\n" % LENS_LABEL.get(variant, variant))
                  if lens_routed else "")
        res = self.build_menu_result(
            bot_user, variant=variant,
            prefix=marker + "⚠️ My AI assistant is briefly unavailable — but I "
                   "can still help you directly.\n\n")
        res["error"] = error_msg or "llm_unavailable"
        res["provider_key"] = None
        res["variant"] = variant
        return res

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
            if intent == "lens":
                return self._tap_lens(bot_user, parts)
            if intent in ("assign_open", "assign_pick", "assignee_decline",
                          "assignee_chat", "assignee_odoo",
                          "escalation_chat", "escalation_odoo"):
                # WA-5 client-lead assignment loop. The actors are MAPPED
                # staff, so they arrive here; the logic lives on the model
                # (next to the client lane). Role-gate + two-factor are
                # enforced inside _wa5_handle_assign_tap.
                return self.env["neon.whatsapp.message"].sudo() \
                    ._wa5_handle_assign_tap(bot_user, intent, parts,
                                            reply_title)
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

    def _tap_lens(self, bot_user, parts):
        """WA-4: the ambiguous-intent lens pick. parts = [variant, msgid].
        GUARDRAIL: the chosen lens must be one the user actually holds
        (re-checked here, not trusted from the payload). Reloads the
        original inbound message and re-runs it under the chosen lens."""
        user = bot_user.user_id
        variant = parts[0] if parts else ""
        msgid = parts[1] if len(parts) > 1 else ""
        if variant not in self._held_lenses(user):
            return self._safe(
                "That view isn't available for your role -- please retype "
                "your question.")
        # WA-4 review fix: enforce the owner check IN the query (the msgid
        # must belong to THIS bot_user) rather than browse + post-hoc.
        msg = (self.env["neon.whatsapp.message"].sudo().search(
            [("id", "=", int(msgid)), ("bot_user_id", "=", bot_user.id)],
            limit=1) if str(msgid).isdigit() else None)
        if not msg:
            return self._safe(
                "I lost the original message -- please retype your question "
                "and I'll answer as %s." % LENS_LABEL.get(variant, variant))
        return self.run_turn(bot_user, msg.message_body or "",
                             variant=variant, lens_routed=True)
