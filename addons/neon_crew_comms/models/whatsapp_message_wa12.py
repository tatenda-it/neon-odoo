# -*- coding: utf-8 -*-
"""B11 / WA-12 — Quote-by-WhatsApp (FIRST money-adjacent WA face).

A sales-capable mapped staffer texts a tight command:

  Quote: <client> — <items[/dimensions]>[, <date>][ for N days]
      -> resolve the NAMED client (res.partner name search; NOT the sender's
         phone — that's the rep) -> provision a DRAFT booking chain via
         neon.finance.quote._wa12_provision_chain (Option 1: pending
         commercial.job + TBC venue -> provisional draft event.job -> quote)
         -> build quote lines from the matched catalogue items (unit_rate set
         from each product's per-product day rate; Robin ruling 1 -- no new
         engine, the existing qty x unit_rate x duration_days compute) ->
         recalc -> the no_rule GUARD (binding 1) blocks submit while ANY line
         is unpriced -> echo the draft summary -> requester confirms ->
         submit_for_approval -> approval ping to MD/OD (uids 7 + 21).

  Price: <item>
      -> read-only: the item's day rate + currency + a per-day note. No quote,
         no approval, no session. Same sales-capable gate.

APPROVAL DISPATCH (dual-payload, binding 3): the cold-window approval ping is
the Active `wa12_quote_approval` TEMPLATE whose quick-reply buttons return PLAIN
text ("Approve"/"Reject"/"View PDF" -- Meta strips emoji); the quote is then
resolved from the approver's PENDING context. In-window interactive buttons
(e.g. the requester's [Send to client], or a re-prompt) carry the HMAC
wa12_*:<quote_id> payload. BOTH forms route to the same handlers under the
first-tap-wins advisory lock (fresh ns 5593900, WA-10 dedupe shape).

ENTITLEMENT (binding 2): _wa12_can_quote = OD/superuser + neon_sales_rep +
jobs_manager (NOT the broad WA-8 any-mapped rail), shared by Quote: and Price:.
Face-2 invoice generation (WA-13) is finance-only -- not here. A MAPPED but
non-sales sender gets a TERSE, non-advertising refusal (never teach the command);
an UNMAPPED sender falls through silently (client lane / Copilot), exactly like
WA-6/7/8. Intercepted in handle_inbound AFTER WA-10, BEFORE WA-6; claims only
q_* sessions, wa12_* taps + the approval template buttons, and the tight
Quote:/Price: commands -- a mid-sentence "quote"/"price" never matches.

MONEY WALL: nothing here is live until Robin's sign-off + the pricing load + the
staged [TEST-WA12] proof. Test rates only. The quote DISPLAYS a total to the
internal approver (inherent to approving a price) -- the gated money surface.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.neon_channels.models.phone_utils import to_e164
from odoo.addons.neon_channels.models import wa_payload
# WA-12.3 family-term test reuses the matcher's stopword / generic-noun sets.
from odoo.addons.neon_crew_comms.models.whatsapp_message_wa6 import (
    _WA6_STOP, _WA6_GENERIC_NOUN)

_logger = logging.getLogger(__name__)

# Tight commands. The COLON form ("quote:") is the canonical Robin format and
# may PREFIX-match ("Quote: Acme -- ..."). The bare word ("quote") is allowed
# ONLY as a whole-message EQUALS (a lone "quote" -> show help) -- never as a
# startswith, or common openers like "price list please" / "quote me later"
# would steal a Copilot turn. Never substring.
_WA12_QUOTE_CMDS = ("quote:", "quote")
_WA12_PRICE_CMDS = ("price:", "price")

# Looser conversational TRIGGERS for the quote-create face (multi-word
# startswith phrases, no colon). The colon form + bare word stay in
# _WA12_QUOTE_CMDS. A misfire ("quote for the meeting") just yields an honest
# "send: Quote: <client> — <items>" reply (the turn is claimed, recoverable).
_WA12_QUOTE_TRIGGERS = (
    "make a quotation for", "i want a quote for", "quote for")

# q_confirm draft-session vocabulary (synonym-tolerant, whole-message equals).
_WA12_CANCEL_WORDS = ("cancel", "no", "stop", "delete", "scrap",
                      "cancel this", "delete this", "scrap this")
_WA12_SUBMIT_WORDS = ("yes", "submit", "y", "ok", "submit for approval",
                      "send for approval")

# New-client intake steps (guided capture when the resolver misses / is
# ambiguous). FSM: qc_pick -> qc_kind -> qc_name -> [qc_dupe] ->
# [qc_contact] -> qc_phone -> qc_email -> create + resume the quote.
_WA12_CAPTURE_STEPS = ("qc_pick", "qc_kind", "qc_name", "qc_dupe",
                       "qc_contact", "qc_phone", "qc_email")

# WA-12.2 conversational steps: q_items (confirm matched items BEFORE any
# draft exists -- M1 binding), q_client / q_itemreq (bare "I want a quote"
# slot-filling -- M5).
_WA12_CONVO_STEPS = ("q_items", "q_client", "q_itemreq")

# WA-12.6 STRUCTURED collection steps (the new deterministic spine): client
# (reuses q_client/qc_*) -> qs_event -> qs_item (one-at-a-time loop) -> q_confirm
# (review). The LLM is demoted to optional pre-fill suggestions; items are ALWAYS
# collected one-by-one fresh, never seeded from a dump.
_WA12_STRUCT_STEPS = ("qs_event", "qs_item")

# Quote session steps live on the shared equip-session. WA-12 claims q_confirm /
# q_reject + the new-client capture steps + the conversational + structured steps.
_WA12_STEPS = (("q_confirm", "q_reject") + _WA12_CAPTURE_STEPS
               + _WA12_CONVO_STEPS + _WA12_STRUCT_STEPS)

# Item-loop "done" / "next" vocab (the rep ends collection or moves on).
_WA12_DONE_WORDS = ("done", "that's all", "thats all", "finish", "finished",
                    "no more", "nothing else", "that's it", "thats it", "end")

# Complaint/correction language (M4): a repair prompt, never the syntax menu.
_WA12_COMPLAINT_TOKENS = ("wrong", "incorrect", "mistake", "not what i",
                          "that is not", "that's not", "fix this")

# F7: multi-word cancels ("cancel or delete", "scrap it"). A message cancels
# when it contains a cancel VERB and nothing beyond filler — "delete the JVC
# line" (a real noun) never cancels.
_WA12_CANCEL_VERBS = {"cancel", "delete", "scrap", "abort", "drop"}
_WA12_CANCEL_FILLER = {"or", "and", "it", "this", "that", "the", "quote",
                       "draft", "please", "everything", "all", "whole",
                       "thing", "no", "stop", "just"}

# F6: a greeting into a live session greets + offers resume/cancel, never the
# syntax card.
_WA12_GREETINGS = ("hi", "hello", "hey", "hie", "hesi", "makadii",
                   "good morning", "morning", "good afternoon",
                   "good evening", "gm", "hi there", "hello there")

# F3: "show me"-type messages are NOT a yes — nothing drafts until confirmed.
_WA12_SHOW_WORDS = ("show", "show me", "preview", "pdf", "let me see",
                    "let me see the draft", "show me the draft",
                    "can i see it", "see the draft")

# F6 (review FSM-1): the in-session "resume/continue" verbs. 'resume' is a
# Meta opt-in keyword (released to the WA-2 rail before any session claim), so
# it can NEVER be the ADVERTISED recovery word -- we advertise 'continue' and
# accept both as aliases where the turn actually reaches the handler.
_WA12_RESUME_WORDS = ("continue", "resume")

# WA-12.4 stepper. SKIP drops the current item (state='skipped'); CONFIRM
# accepts a confident card (state='confirmed'). 'next' is a CONFIRM (advance),
# never a drop (BUG-6). Q tokens route an unrecognised/question message to HELP
# + re-show, NEVER a catalogue match (the "where do I tap" regression).
_WA12_SKIP_WORDS = ("skip", "skip it", "skip this", "remove", "remove this",
                    "drop", "drop it", "drop this", "none of these", "none")
_WA12_CONFIRM_WORDS = ("ok", "okay", "correct", "yes that", "right", "next",
                       "looks good", "good", "confirm", "yep", "yeah", "ya")
_WA12_Q_TOKENS = ("where", "how", "what", "which", "why", "who", "when",
                  "help", "do i", "can i", "should i", "tap", "explain",
                  "confused", "i dont", "i don't", "huh")
_WA12_NUM = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤", 6: "⑥",
             7: "⑦", 8: "⑧", 9: "⑨", 10: "⑩"}

# Fresh advisory-lock namespace (NOT 5593500/600/700/800) -- first-tap-wins on
# the approver pair so only ONE of uids 7/21 wins a concurrent Approve/Reject.
_WA12_LOCK_NS = 5593900

# Soft session TTL: a quote draft-confirm is a quick step; idle past this falls
# through to the Copilot (a later message is never swallowed as a confirm).
_WA12_TTL_HOURS = 2

# A $1 (or lower) line rate is the catalogue PLACEHOLDER, never a real price.
_WA12_PLACEHOLDER_RATE = 1.0

# WA-12.2 conversational fallback: only invoke the LLM translator when the tight
# parsers missed AND the message is multi-word (a quote names a client + items;
# a 1-2 word message is never a quote -> skip the call, fall to the Copilot).
_WA12_LLM_MIN_WORDS = 3

# ⚠️ DECISION (WA-12): the proactive approval-ping AUDIENCE = the two MD/OD
# approver uids (Tatenda binding) -- who we cold-window TEMPLATE-ping. Resolved
# to live res.users at send time; an inactive / non-approver uid is skipped.
# The authorising GATE, by contrast, is the approver GROUP (below), never these
# numeric ids -- so who may actually approve tracks live group membership and
# matches the model's own has_group gate (no uid-drift -> no uncaught
# AccessError). The audience is a config hint; the group is the security gate.
_WA12_APPROVER_UIDS = (7, 21)

# The authorising approver capability -- the SAME XML group the finance model's
# action_approve/reject enforce. Gate on this (never the uid set) so the WA-12
# layer can never authorise someone the model will reject.
_WA12_APPROVER_GROUP = "neon_finance.group_neon_finance_approver"

_WA12_TEMPLATE = "wa12_quote_approval"

# Terse, NON-advertising refusal for a mapped non-sales sender (binding 2): it
# must NOT name the capability or teach the command.
_WA12_REFUSAL = (
    "Sorry — that isn't something I can action on your account.")

# The plain template-QR button texts (Meta strips emoji) -> intent.
_WA12_BTN_TEXT = {
    "approve": "wa12_approve",
    "reject": "wa12_reject",
    "view pdf": "wa12_view_pdf",
}


class WhatsAppMessageWA12(models.Model):
    _inherit = "neon.whatsapp.message"

    # ================================================================
    # Entitlement (binding 2): sales-capable ONLY -- narrower than WA-8.
    # ================================================================
    @api.model
    def _wa12_can_quote(self, user):
        """OD/superuser + Neon sales rep + jobs manager. Gated on XML group
        ids (never numeric). Shared by Quote: and Price:. (Org-map verified:
        Evrill's groups are a superset of Lisa's, so she is covered.)"""
        if not user or not user.id:
            return False
        if self._wa6_can_initiate(user):  # OD login / Neon Superuser
            return True
        for g in ("neon_core.group_neon_sales_rep",
                  "neon_jobs.group_neon_jobs_manager"):
            if user.has_group(g):
                return True
        return False

    @api.model
    def _wa12_is_approver(self, user):
        """May this user APPROVE/REJECT a quote? The authorising gate -- the
        exact approver GROUP the finance model enforces (never the numeric uid
        set), plus active. Matching the model gate guarantees the WA-12 layer
        never clears someone action_approve would reject with an AccessError."""
        return bool(user and user.id and user.active
                    and user.has_group(_WA12_APPROVER_GROUP))

    @api.model
    def _wa12_is_quote_cmd(self, body):
        norm = " ".join((body or "").strip().lower().split())
        # colon form prefix-matches; bare word only as a whole-message equals.
        if any(norm == c or (c.endswith(":") and norm.startswith(c))
               for c in _WA12_QUOTE_CMDS):
            return True
        # conversational triggers: a multi-word phrase at the START.
        return any(norm == t or norm.startswith(t + " ")
                   for t in _WA12_QUOTE_TRIGGERS)

    @api.model
    def _wa12_is_price_cmd(self, body):
        norm = " ".join((body or "").strip().lower().split())
        return any(norm == c or (c.endswith(":") and norm.startswith(c))
                   for c in _WA12_PRICE_CMDS)

    @api.model
    def _wa12_strip_cmd(self, body, cmds):
        """Remove the matched command prefix (longest-first); return the rest.
        Only the colon form prefix-strips; a lone bare/colon word -> ''."""
        norm = (body or "").strip()
        low = norm.lower()
        for c in sorted(cmds, key=len, reverse=True):
            if low == c or low == c.rstrip(":"):
                return ""
            if c.endswith(":") and low.startswith(c):
                return norm[len(c):].strip()
            # multi-word conversational trigger (no colon): prefix-strip.
            if " " in c and low.startswith(c + " "):
                return norm[len(c):].strip()
        return norm

    # ================================================================
    # Intercept entry (handle_inbound, after WA-10, before WA-6).
    # ================================================================
    @api.model
    def _wa12_maybe_intercept(self, message):
        """True if WA-12 handled this inbound, else None (fall through). Claims:
        an Approve/Reject/View-PDF tap (template-QR text OR interactive HMAC), a
        q_* session turn for this phone, or a tight Quote:/Price: command from a
        sales-capable sender. Everything else -> None (WA-6 / WA-5 / Copilot run
        unchanged)."""
        raw_from = message.get("from")
        from_e164 = to_e164(raw_from)
        if not from_e164:
            return None

        # 0) RELEASE the WA-2 opt-out keywords BEFORE any session claim so they
        #    fall through to super() -> _wa_maybe_opt_out_keyword (mirrors
        #    WA-6/7/8/10/13). Without this a 'STOP' typed mid-q_confirm matches
        #    the cancel words -> "Quote cancelled." and the opt-out NEVER
        #    registers (review: the WA13-1 bug class).
        if message.get("type") == "text":
            _kw = ((message.get("text") or {}).get("body") or "").strip().upper()
            if _kw in {"STOP", "START", "UNSUBSCRIBE", "STOPALL", "UNSTOP",
                       "RESUME"}:
                return None

        # 1) TAP (dual-payload). Template-QR -> type 'button' + button.payload
        #    /.text (plain "Approve"/...); interactive -> button_reply.id (HMAC).
        tap = self._wa12_extract_tap(message)
        if tap:
            intent, payload = tap
            # WA-12.3 pick sentinel -> the pick handler (payload is a parts
            # list, NOT a quote recordset; routing it to _wa12_handle_tap would
            # .exists() a list and crash).
            if isinstance(payload, tuple) and payload and payload[0] == "pick":
                return self._wa12_handle_pick_tap(
                    intent, payload[1], from_e164, raw_from, message)
            # menu "Quote a client" -> start the structured flow (re-checks entitlement).
            if isinstance(payload, tuple) and payload and payload[0] == "start":
                return self._wa12_handle_start_tap(from_e164, raw_from, message)
            return self._wa12_handle_tap(
                intent, payload, from_e164, raw_from, message)

        # 2) A live q_* session turn for this phone (confirm / reject comment).
        sess = self.env["neon.wa.equip.session"]._active_for_phone(from_e164)
        if sess and sess.step in _WA12_STEPS:
            if self._wa12_session_stale(sess):
                sess.sudo().write({"active": False})
                return None
            return self._wa12_handle_session(sess, message, from_e164, raw_from)
        if sess:
            # a live NON-WA-12 session (a WA-6 finalize, etc.) owns this
            # one-per-phone row -- never let the Quote:/Price: parser overrun it
            # (it would rebind the session via _start_quote). Mirrors the
            # WA-7/8/10 "a live session owns this phone" bail-out; WA-6 (the
            # next intercept) will handle the turn.
            return None

        # 3) A tight Quote:/Price: command (deterministic-first; zero cost/risk
        #    on exact commands). The WA-12.2 CONVERSATIONAL fallback is NOT here
        #    -- it runs from handle_inbound AFTER every deterministic interceptor
        #    misses (_wa12_llm_intake_maybe), so a WA-13 "send quote" / WA-6
        #    turn is never pre-empted by an LLM call.
        body = self._extract_body(message, message.get("type"))
        is_q, is_p = self._wa12_is_quote_cmd(body), self._wa12_is_price_cmd(body)
        if not (is_q or is_p):
            return None
        sender = self._wa6_resolve_user(from_e164)
        if not sender:
            return None  # UNMAPPED -> silent fall-through (client lane/Copilot)
        if not self._wa12_can_quote(sender):
            # MAPPED but non-sales -> terse, non-advertising refusal.
            self._wa6_audit_in(from_e164, message, "wa12-deny")
            return self._wa6_reply(raw_from, from_e164, _(_WA12_REFUSAL))
        if is_q:
            return self._wa12_run_quote(
                sender, body, from_e164, raw_from, message)
        return self._wa12_run_price(sender, body, from_e164, raw_from, message)

    @api.model
    def _wa12_extract_tap(self, message):
        """Return (intent, quote_recordset) for a WA-12 tap, else None.
        Dual-payload: an interactive button_reply.id is the HMAC
        wa12_*:<quote_id>; a template quick-reply is type 'button' whose
        payload/text is the PLAIN button label -> the quote is resolved from
        the sender's PENDING-approval context."""
        mtype = message.get("type")
        # interactive (in-window) -> HMAC id.
        if mtype == "interactive":
            inter = message.get("interactive") or {}
            # WA-12.3: a 4-10 candidate pick comes back as list_reply, not
            # button_reply -- read BOTH or the list tap dead-ends.
            payload = ((inter.get("button_reply") or {}).get("id")
                       or (inter.get("list_reply") or {}).get("id"))
            secret = self.env["ir.config_parameter"].sudo().get_param(
                "database.secret") or ""
            decoded = wa_payload.decode(secret, payload or "")
            # WA-12.3 pick intents: tested BEFORE the startswith("wa12_") block
            # (which browses parts[0] as a QUOTE id). Return a sentinel tuple
            # (intent, ("pick", parts)) so _wa12_maybe_intercept routes it to the
            # pick handler, NOT _wa12_handle_tap (which would .exists() a list).
            if decoded and decoded[0] in (
                    "wa12_pick", "wa12_pick_more", "wa12_pick_skip",
                    "wa12_ok", "wa12_change"):  # WA-12.4 stepper (R1 ship-block)
                return (decoded[0], ("pick", list(decoded[1])))
            # menu "Quote a client" -> a START sentinel (NOT a quote id; parts[0]
            # is the bot_user id). Routed to begin_structured, never browsed.
            if decoded and decoded[0] == "wa12_start":
                return ("wa12_start", ("start", list(decoded[1])))
            if decoded and decoded[0].startswith("wa12_"):
                intent, parts = decoded
                quote = self.env["neon.finance.quote"].sudo().browse(
                    int(parts[0])) if parts and parts[0].isdigit() else \
                    self.env["neon.finance.quote"].sudo().browse()
                return (intent, quote)
            return None
        # template quick-reply -> type 'button', plain text payload.
        if mtype == "button":
            btn = message.get("button") or {}
            text = (btn.get("text") or btn.get("payload") or "").strip().lower()
            intent = _WA12_BTN_TEXT.get(text)
            if not intent:
                return None
            from_e164 = to_e164(message.get("from"))
            sender = self._wa6_resolve_user(from_e164)
            quote = self._wa12_pending_for_approver(sender)
            return (intent, quote)
        return None

    def _wa12_handle_start_tap(self, from_e164, raw_from, message):
        """The deterministic Hello/menu 'Quote a client' row -> start the WA-12
        structured flow. The menu only DISPLAYS this row for quote-capable lenses;
        this re-checks _wa12_can_quote as the real gate (a forwarded payload from
        a non-sales sender is refused, never silently quoting)."""
        sender = self._wa6_resolve_user(from_e164)
        if not sender:
            return None  # unmapped -> fall through (client lane / Copilot)
        if not self._wa12_can_quote(sender):
            self._wa6_audit_in(from_e164, message, "wa12-start-deny")
            return self._wa6_reply(raw_from, from_e164, _(_WA12_REFUSAL))
        # begin_structured resets to step 1 (client); an empty dump means no
        # pre-fill, just the clean "which client?" opener.
        return self._wa12_begin_structured(
            sender, "", from_e164, raw_from, message=message)

    @api.model
    def _wa12_pending_for_approver(self, user):
        """Quote(s) awaiting THIS approver's decision (state pending_approval).
        Empty if the sender isn't an approver. Returns the FULL set (NO limit):
        a payload-less template-QR tap carries no quote_id, so the caller must
        REFUSE when >1 is pending rather than guess 'most recent' -- guessing
        could approve the WRONG quote at the WRONG total (a real money-surface
        bug with two reps' quotes pending at once). The in-window HMAC tap is
        unambiguous (it carries the id) and never routes through here."""
        empty = self.env["neon.finance.quote"].sudo().browse()
        if not self._wa12_is_approver(user):
            return empty
        return self.env["neon.finance.quote"].sudo().search(
            [("state", "=", "pending_approval")], order="write_date desc")

    def _wa12_session_stale(self, sess):
        if not sess.last_inbound:
            return False
        return (fields.Datetime.now() - sess.last_inbound).total_seconds() \
            > _WA12_TTL_HOURS * 3600

    # ================================================================
    # Quote: flow — parse -> resolve client -> provision -> lines -> guard.
    # ================================================================
    def _wa12_run_quote(self, sender, body, from_e164, raw_from, message):
        """WA-12.6: a 'Quote:' command no longer bulk-extracts the brief (the
        proven item-drop / wrong-client failure). It RESETS to the structured
        one-at-a-time collection (client -> event -> items -> review); the brief
        text only PRE-FILLS the client/date prompts as confirmable suggestions.
        Still claimed (the sender explicitly typed Quote:)."""
        rest = self._wa12_strip_cmd(body, _WA12_QUOTE_CMDS + _WA12_QUOTE_TRIGGERS)
        return self._wa12_begin_structured(
            sender, rest, from_e164, raw_from, message=message)

    def _wa12_quote_from_slots(self, sender, partner, matched, date_txt, days,
                               from_e164, raw_from, extras=None):
        """Provision + price a quote for a RESOLVED partner + matched items,
        open the q_confirm session, reply the draft summary. Shared by the
        direct Quote: path and the post-intake resume. ``extras`` (F5): brief
        slots beyond the core — event_name lands on the event job's client
        notes so the subject isn't dropped."""
        event_date, placeholder = self._wa12_resolve_date(date_txt)
        currency = (sender.company_id.currency_id
                    or self.env.ref("base.USD", raise_if_not_found=False))
        if not currency:
            return self._wa6_reply(raw_from, from_e164, _(
                "Can't quote — no currency is configured. Please set one up "
                "in Odoo first."))
        # A provisioning UserError (missing TBC venue, etc.) must reply cleanly,
        # not propagate to the webhook (rollback + Meta re-delivery loop).
        try:
            quote = self.env["neon.finance.quote"]._wa12_provision_chain(
                partner, event_date, currency, sender,
                date_is_placeholder=placeholder)
        except (UserError, AccessError) as e:
            return self._wa6_reply(raw_from, from_e164, str(e))
        self._wa12_build_lines(quote, matched, days or 1)
        quote.with_user(sender.id).sudo().action_recalculate_pricing()
        unpriced = self._wa12_unpriced_lines(quote)
        self._wa12_ensure_payment_term(quote, partner)
        # F5: the event subject from the brief lands on the event job (the
        # name fields are readonly sequence refs -> client_notes).
        ev_name = ((extras or {}).get("event_name") or "").strip()
        if ev_name and quote.event_job_id:
            ej = quote.event_job_id
            note = _("Event: %s (via WhatsApp quote)") % ev_name
            # actor-honest write (hard rule; review FSM-9): stamp the rep, not
            # the public webhook uid, on write_uid.
            ej.with_user(sender.id).sudo().write({"client_notes": (
                (ej.client_notes + "\n" + note)
                if ej.client_notes else note)})
        self.env["neon.wa.equip.session"]._start_quote(
            from_e164, sender, "q_confirm", {"quote_id": quote.id})
        summary = self._wa12_draft_summary(quote, unpriced)
        if unpriced:
            return self._wa6_reply(raw_from, from_e164, summary + "\n\n" + _(
                "⚠️ Can't submit yet — these have no rate set: %s. "
                "Pricing isn't loaded for them.") % ", ".join(unpriced))
        return self._wa6_reply(raw_from, from_e164, summary + "\n\n" + _(
            "Reply *yes* to submit for approval, or *cancel*."))

    @api.model
    def _wa12_client_candidates(self, name):
        """(exact/unique partner or empty, candidates). Mirrors
        _wa12_resolve_client's search but returns the candidate SET for
        list-then-pick / new-client intake instead of an ambiguity error."""
        P = self.env["res.partner"].sudo()
        hits = P.search([("name", "ilike", name), ("is_venue", "=", False)],
                        limit=8)
        exact = hits.filtered(
            lambda p: (p.name or "").strip().lower() == name.strip().lower())
        if len(exact) == 1:
            return exact, exact
        if len(hits) == 1:
            return hits, hits
        return P.browse(), hits

    def _wa12_start_client_intake(self, sender, client_txt, candidates, matched,
                                  date_txt, days, from_e164, raw_from,
                                  prefills=None, structured=False):
        """Open the qc_pick session: list any existing matches + offer *new*.
        Buffers the matched items + date so the quote resumes without re-entry.
        ``prefills`` (M3): phone/email/contact already present in the rep's
        brief — pre-fill the capture so only MISSING slots get asked.
        WA-12.6: ``structured`` -> on intake completion resume into the EVENT
        step (qs_event), not the old item path (Robin's briefs are often new
        clients; the exact-client path alone would dead-end them)."""
        buf = {"matched": matched, "date_txt": date_txt or "",
               "days": days or 1, "client_txt": client_txt,
               "candidate_ids": candidates.ids[:8],
               "prefills": prefills or {}, "structured": structured}
        self.env["neon.wa.equip.session"]._start_quote(
            from_e164, sender, "qc_pick", buf)
        if candidates:
            rows = "\n".join("%d) %s" % (i + 1, p.name)
                             for i, p in enumerate(candidates))
            return self._wa6_reply(raw_from, from_e164, _(
                "Found these for \"%s\":\n%s\n\nReply the number to use one, "
                "or *new* to add a new client.") % (client_txt, rows))
        return self._wa6_reply(raw_from, from_e164, _(
            "No existing client matches \"%s\". Reply *new* to add them, or "
            "send a different name.") % client_txt)

    def _wa12_handle_capture(self, sess, body, from_e164, raw_from):
        """New-client intake FSM (qc_*). Sales-capable gate re-checked; a
        'cancel'/'scrap' aborts. On completion (or an existing-client pick) the
        quote resumes via _wa12_quote_from_slots with the buffered items+date."""
        sender = sess.user_id
        if not (sender and sender.active and self._wa12_can_quote(sender)):
            sess.sudo().write({"active": False})
            return self._wa6_reply(raw_from, from_e164, _(_WA12_REFUSAL))
        raw = (body or "").strip()
        norm = " ".join(raw.lower().split())
        buf = sess._get_buffer()
        buf = buf if isinstance(buf, dict) else {}
        P = self.env["res.partner"].sudo()
        step = sess.step

        # 'no'/'n' at qc_dupe means "not the same client -> add new", never a
        # cancel (the dupe question is yes/no-shaped).
        # yes/no-shaped slots keep their own vocabulary (FSM-2): 'no' at
        # qc_dupe = "add new", 'no'/'none' at qc_email = "skip email" -- not a
        # cancel of the whole intake.
        if self._wa12_is_cancel(norm) and not (
                (step == "qc_dupe" and norm in ("no", "n"))
                or (step == "qc_email" and norm in ("no", "n", "none"))):
            sess.sudo().write({"step": "done", "active": False})
            return self._wa6_reply(raw_from, from_e164, _(
                "New-client setup cancelled."))

        def save(next_step, **kw):
            buf.update(kw)
            sess.sudo().write({"step": next_step})
            sess._set_buffer(buf)

        def resume(partner):
            sess.sudo().write({"step": "done", "active": False})
            # WA-12.6: a STRUCTURED intake resumes into the EVENT step (the
            # new spine: client -> event -> items), reusing the same session row.
            if buf.get("structured"):
                sbuf = {"v": 5, "structured": True, "client_txt": partner.name,
                        "partner_id": partner.id, "date_txt": "", "venue": "",
                        "note": "", "prefills": buf.get("prefills") or {},
                        "items": [], "pending_item": None, "qty_for": False,
                        "await_days": False}
                ns = self.env["neon.wa.equip.session"]._start_quote(
                    from_e164, sender, "q_client", sbuf)
                return self._wa12_struct_after_client(
                    ns, sbuf, partner, from_e164, raw_from)
            if not buf.get("matched"):
                # M5 bare-intent path: the client is set but no items were
                # captured yet -> ask for them (same lane, no re-entry).
                self.env["neon.wa.equip.session"]._start_quote(
                    from_e164, sender, "q_itemreq",
                    {"client_txt": partner.name, "partner_id": partner.id,
                     "date_txt": buf.get("date_txt") or "",
                     "prefills": buf.get("prefills") or {}})
                return self._wa6_reply(raw_from, from_e164, _(
                    "%s — what items?") % partner.name)
            # WA-12.4: client now resolved -> open the item STEPPER (not a direct
            # draft) so each buffered item is confirmed one at a time. The
            # buffered `matched` were extracted upstream; re-split into matched/
            # unmatched is unnecessary (they were confident) -> all matched.
            return self._wa12_open_items_confirm(
                sender, partner.name, buf.get("matched") or [], [],
                buf.get("date_txt") or "", buf.get("prefills") or {},
                from_e164, raw_from, partner_id=partner.id)

        def ask_after_name(ack=""):
            """Advance to the next MISSING slot (M3: brief-sourced phone/
            email/contact pre-fill -- only missing slots get asked)."""
            nm = buf.get("name") or _("the client")
            pf = buf.get("prefills") or {}
            if (buf.get("kind") == "company" and not buf.get("contact")):
                if pf.get("contact"):
                    buf["contact"] = pf["contact"]
                else:
                    save("qc_contact")
                    return self._wa6_reply(raw_from, from_e164, ack
                                           + _("Contact person at %s?") % nm)
            if not buf.get("phone"):
                if pf.get("phone"):
                    buf["phone"] = pf["phone"]
                    buf["phone_e164"] = to_e164(pf["phone"]) or ""
                else:
                    save("qc_phone")
                    sess._set_buffer(buf)
                    return self._wa6_reply(raw_from, from_e164, ack
                                           + _("Phone number for %s?") % nm)
            if pf.get("email"):
                sess._set_buffer(buf)
                partner = self._wa12_create_client(
                    sender.id, buf, pf["email"])
                return resume(partner)
            save("qc_email")
            return self._wa6_reply(raw_from, from_e164, ack + _(
                "Email? (needed to send quotes — or reply *skip*)"))

        if step == "qc_pick":
            ids = buf.get("candidate_ids") or []
            if norm in ("new", "n", "new client", "add", "add new"):
                save("qc_kind")
                return self._wa6_reply(raw_from, from_e164, _(
                    "New client — is it a *company* or an *individual*?"))
            if norm.isdigit() and 1 <= int(norm) <= len(ids):
                p = P.browse(ids[int(norm) - 1]).exists()
                if p:
                    return resume(p)
            # a re-typed name -> re-resolve
            partner, candidates = self._wa12_client_candidates(raw)
            if partner:
                return resume(partner)
            save("qc_pick", client_txt=raw, candidate_ids=candidates.ids[:8])
            if candidates:
                rows = "\n".join("%d) %s" % (i + 1, p.name)
                                 for i, p in enumerate(candidates))
                return self._wa6_reply(raw_from, from_e164, _(
                    "Found:\n%s\n\nReply the number, or *new* to add a new "
                    "client.") % rows)
            return self._wa6_reply(raw_from, from_e164, _(
                "Still no match for \"%s\". Reply *new* to add them, or send a "
                "different name.") % raw)

        if step == "qc_kind":
            if norm in ("company", "c", "business", "org", "organisation",
                        "organization"):
                save("qc_name", kind="company")
            elif norm in ("individual", "i", "person", "private"):
                save("qc_name", kind="individual")
            else:
                return self._wa6_reply(raw_from, from_e164, _(
                    "Reply *company* or *individual*."))
            seed = buf.get("client_txt") or ""
            return self._wa6_reply(
                raw_from, from_e164,
                (_("Client name? (or reply *ok* to use \"%s\")") % seed)
                if seed else _("What's the client's name?"))

        if step == "qc_name":
            name = ((buf.get("client_txt") or "") if norm in ("ok", "yes",
                    "same", "y") else raw)
            if not name:
                return self._wa6_reply(raw_from, from_e164, _(
                    "Please type the client's name."))
            # NEAR-DUPLICATE CHECK before any create (protect the partner table).
            dupes = P.search([("name", "ilike", name),
                              ("is_venue", "=", False)], limit=3)
            if dupes:
                save("qc_dupe", name=name, dupe_ids=dupes.ids)
                rows = "\n".join("%d) %s" % (i + 1, p.name)
                                 for i, p in enumerate(dupes))
                return self._wa6_reply(raw_from, from_e164, _(
                    "Found similar:\n%s\n\nSame client? Reply the number to use "
                    "it, or *new* to add \"%s\" as a new client.")
                    % (rows, name))
            buf["name"] = name
            sess._set_buffer(buf)
            return ask_after_name()

        if step == "qc_dupe":
            ids = buf.get("dupe_ids") or []
            if norm.isdigit() and 1 <= int(norm) <= len(ids):
                p = P.browse(ids[int(norm) - 1]).exists()
                if p:
                    return resume(p)
            if norm in ("new", "no", "n", "0", "add new"):
                return ask_after_name()
            return self._wa6_reply(raw_from, from_e164, _(
                "Reply the number to use an existing client, or *new* to add a "
                "new one."))

        if step == "qc_contact":
            buf["contact"] = raw
            sess._set_buffer(buf)
            return ask_after_name()

        if step == "qc_phone":
            buf["phone"], buf["phone_e164"] = raw, to_e164(raw) or ""
            sess._set_buffer(buf)
            # acknowledge the correction/entry (M3), then the next missing slot.
            return ask_after_name(ack=_("Got it — %s. ") % raw)

        if step == "qc_email":
            email = "" if norm in ("skip", "none", "no", "-", "n") else raw
            partner = self._wa12_create_client(sender.id, buf, email)
            return resume(partner)

        return None

    def _wa12_create_client(self, actor, buf, email):
        """Create the new client partner as the REP (create_uid honesty):
        E164 phone (joins the WA-9 phone_sanitized spine), email, ref source
        marker. A company also gets its contact person as a child."""
        P = self.env["res.partner"].with_user(actor).sudo()
        ph = buf.get("phone_e164") or buf.get("phone") or ""
        vals = {"name": buf.get("name") or _("(client)"),
                "is_company": buf.get("kind") == "company",
                "ref": "whatsapp_quote"}
        if ph:
            vals["phone"] = ph
        if email:
            vals["email"] = email
        # F5: a brief-supplied address lands on the new partner.
        addr = ((buf.get("prefills") or {}).get("address") or "").strip()
        if addr:
            vals["street"] = addr
        partner = P.create(vals)
        if buf.get("kind") == "company" and buf.get("contact"):
            P.create({"name": buf["contact"], "parent_id": partner.id,
                      "type": "contact", "phone": ph or False,
                      "email": email or False})
        return partner

    @api.model
    def _wa12_is_cancel(self, norm):
        """F7: True for 'cancel', 'scrap this', 'cancel or delete', 'delete
        it' — a cancel VERB plus only filler. 'delete the JVC line' (a real
        noun survives the filler strip) is NOT a cancel."""
        if norm in _WA12_CANCEL_WORDS:
            return True
        words = set(norm.split())
        if not (words & _WA12_CANCEL_VERBS):
            return False
        return not (words - _WA12_CANCEL_VERBS - _WA12_CANCEL_FILLER)

    def _wa12_repair_prompt(self, raw_from, from_e164):
        """M4: complaint/correction language gets a REPAIR prompt in PLAIN
        language -- no command syntax shown to the rep (user directive)."""
        return self._wa6_reply(raw_from, from_e164, _(
            "No problem — what should I change? You can tell me an item to "
            "swap, a quantity, a discount, the date, or the client, and I'll "
            "sort it."))

    def _wa12_draft_help(self, quote, from_e164, raw_from):
        """DEFECT-3: a QUESTION at the draft step gets a plain HELP answer and
        NEVER mutates the quote. No command grammar shown."""
        return self._wa6_reply(raw_from, from_e164, _(
            "That's the draft so far — nothing's changed. Tap *Submit for "
            "approval* to send it, *Preview* to see the PDF, *Edit* to change "
            "a line, or *Cancel*. Or just tell me what to change."))

    # ================================================================
    # WA-12.6 -- STRUCTURED one-at-a-time collection (the deterministic spine).
    # The bot drives the sequence: client -> event -> items (ONE at a time) ->
    # review. It NEVER bulk-processes a dump; the LLM is optional pre-fill
    # (client/date suggestions only -- items are always collected fresh). This
    # makes item-drop / wrong-client / mis-parse structurally impossible.
    # ================================================================
    def _wa12_begin_structured(self, sender, dump, from_e164, raw_from,
                               message=None):
        """Entry: reset to step 1 (client). A first-message dump is NOT bulk-
        extracted; a best-effort LLM read may PRE-FILL the client/date prompts
        as confirmable suggestions (degrades silently). Opens q_client."""
        if message is not None:
            self._wa6_audit_in(from_e164, message, "wa12-structured")
        prefills = {}
        try:
            data = self._wa12_llm_extract_quote(dump or "") or {}
            prefills = {"client": (data.get("client") or "").strip(),
                        "date": (data.get("date") or "").strip(),
                        "venue": (data.get("address") or "").strip(),
                        "note": (data.get("event_name") or "").strip()}
        except Exception:  # noqa: BLE001 -- pre-fill is best-effort only
            prefills = {}
        buf = {"v": 5, "structured": True, "client_txt": "",
               "partner_id": False, "date_txt": "", "venue": "", "note": "",
               "prefills": prefills, "items": [], "pending_item": None,
               "qty_for": False}
        self.env["neon.wa.equip.session"]._start_quote(
            from_e164, sender, "q_client", buf)
        hint = ""
        if prefills.get("client"):
            hint = _(" (you mentioned *%s* — reply the client name to use it)"
                     ) % prefills["client"]
        return self._wa6_reply(raw_from, from_e164, _(
            "Sure — I'll take this one step at a time so I get it right.\n\n"
            "First, which client is this quote for?%s") % hint)

    def _wa12_struct_after_client(self, sess, buf, partner, from_e164, raw_from):
        """Client resolved/created -> LOG it (locked; later steps never re-
        resolve) -> advance to the EVENT step. Shared by the q_client resolve
        and the qc_* intake resume."""
        buf["client_txt"] = partner.name
        buf["partner_id"] = partner.id
        buf["pending_item"] = None
        sess.sudo().write({"step": "qs_event"})
        sess._set_buffer(buf)
        pf = buf.get("prefills") or {}
        hint = (_(" (you mentioned *%s*)") % pf["date"]) if pf.get("date") else ""
        return self._wa6_reply(raw_from, from_e164, _(
            "Got it — *%s*.\n\nWhat's the event date?%s") % (partner.name, hint))

    def _wa12_handle_struct_event(self, sess, buf, body, from_e164, raw_from):
        """qs_event: capture the event DATE (required, day-first ZW), with an
        optional 'venue: ...' / 'note: ...' on the same or later line. On a
        valid date -> advance to the item loop (ask the first item)."""
        import re
        raw = (body or "").strip()
        norm = " ".join(raw.lower().split())
        # optional venue / note captured without leaving the step.
        m = re.match(r"(?:venue|location)\s*[:\-]\s*(.+)$", raw, re.I)
        if m:
            buf["venue"] = m.group(1).strip()
            sess._set_buffer(buf)
            return self._wa6_reply(raw_from, from_e164, _(
                "Venue noted. What's the event date?"))
        m = re.match(r"note\s*[:\-]\s*(.+)$", raw, re.I)
        if m:
            buf["note"] = m.group(1).strip()
            sess._set_buffer(buf)
            return self._wa6_reply(raw_from, from_e164, _(
                "Note saved. What's the event date?"))
        # AWAIT-DAYS: if we asked "how many chargeable days?" for a range, this
        # turn is the rep's number (Robin's convention: NEVER auto-assume a range
        # day-count -- always ask).
        if buf.get("await_days"):
            m = re.match(r"^\s*(\d+)\s*(?:days?|nights?)?\s*$", norm)
            if not m:
                return self._wa6_reply(raw_from, from_e164, _(
                    "How many chargeable days for this hire? (just a number)"))
            buf["days"] = max(1, int(m.group(1)))
            buf["await_days"] = False
            sess.sudo().write({"step": "qs_item"})
            sess._set_buffer(buf)
            return self._wa6_reply(raw_from, from_e164, _(
                "%d-day hire — got it.\n\nNow the equipment, one at a time. "
                "What's the first item?") % buf["days"])
        # Parse a single date / range / 'for N days'. A range must NOT be fed
        # whole to the single-date parser (it fails).
        ev_date, days, end_date, is_range = self._wa12_parse_event_dates(raw)
        if not ev_date:
            return self._wa6_reply(raw_from, from_e164, _(
                "I didn't catch a date there — send the event date "
                "(e.g. 25/09/2026, 25 Sept 2026, or 7–11 Aug)."))
        buf["date_txt"] = ev_date.isoformat()
        # MONEY (Robin's convention): a RANGE never auto-sets the day count --
        # ASK the rep (the inclusive count is offered only as a hint). A single
        # date -> 1; an explicit "for N days" -> N (the rep stated it). The
        # review 'days' edit can still override.
        if is_range:
            buf["await_days"] = True
            sess._set_buffer(buf)
            hint = (_(" (looks like %d if you count both days)") % days
                    if days > 1 else "")
            return self._wa6_reply(raw_from, from_e164, _(
                "📅 %s%s — got it. How many chargeable days for this hire?%s") % (
                ev_date.strftime("%d %b"),
                (_("–%s") % end_date.strftime("%d %b")) if end_date else "",
                hint))
        buf["days"] = days
        sess.sudo().write({"step": "qs_item"})
        sess._set_buffer(buf)
        span = (_("  (%d-day hire)") % days) if days > 1 else ""
        return self._wa6_reply(raw_from, from_e164, _(
            "📅 %s%s — got it.\n\nNow the equipment, one at a time. What's the "
            "first item?") % (ev_date.strftime("%d %b %Y"), span))

    def _wa12_parse_event_dates(self, raw):
        """(start_date|None, days, end_date|None, is_range). A date RANGE
        ('7th-11th August', '25/09-29/09') -> the inclusive count is returned as
        a HINT with is_range=True, so the caller ASKS the rep (Robin's
        convention: never auto-assume a range day-count). A single date + 'for N
        days' -> N (the rep stated it, is_range=False). A bare single date -> 1
        day. The review 'days' edit can still override."""
        import re
        from datetime import timedelta
        low = " ".join((raw or "").lower().split())
        # 1) a RANGE: two date-ish parts split by -/–/to/until/till/thru.
        m = re.search(
            r"(.+?)\s*(?:-|–|—|\bto\b|\buntil\b|\btill\b|\bthru\b)\s*(.+)$", low)
        if m:
            left, right = m.group(1).strip(), m.group(2).strip()
            r_date, r_ph = self._wa12_resolve_date(right)
            l_date, l_ph = self._wa12_resolve_date(left)
            # the END usually carries the month/year; borrow it for a bare-day
            # start ("7th - 11th of august" -> start "7 august").
            if l_ph and not r_ph:
                md = re.search(r"\d+", left)
                if md:
                    try:
                        l_date = r_date.replace(day=int(md.group()))
                        l_ph = False
                    except ValueError:
                        l_ph = True
            if not l_ph and not r_ph and r_date >= l_date:
                # inclusive count = HINT only; is_range=True -> caller asks.
                return l_date, (r_date - l_date).days + 1, r_date, True
        # 2) a single date (+ optional 'for N days' -> the rep stated it). Strip
        # the 'for N days' clause BEFORE resolving the date ("25 Sept 2026 for 3
        # days" must parse the date from "25 Sept 2026", not the whole string).
        m = re.search(r"\bfor\s+(\d+)\s*(?:day|days|nights?)\b", low)
        stated_n = max(1, int(m.group(1))) if m else None
        date_part = re.sub(r"\bfor\s+\d+\s*(?:day|days|nights?)\b", "", low
                           ).strip(" ,") if m else low
        s_date, s_ph = self._wa12_resolve_date(date_part)
        if s_ph:
            return None, 1, None, False
        if stated_n:
            return s_date, stated_n, (s_date + timedelta(days=stated_n - 1)), False
        return s_date, 1, None, False

    def _wa12_handle_struct_item(self, sess, buf, body, from_e164, raw_from):
        """qs_item: the one-at-a-time item loop. Holds ONE item in flight. The
        rep names ONE item -> category-scoped, packages-excluded LIST (or a
        confident card / a custom-line offer) -> tap/confirm -> logged -> 'next
        or done'. 'done' -> the review draft."""
        import re
        raw = (body or "").strip()
        norm = " ".join(raw.lower().split())

        if norm in _WA12_DONE_WORDS:
            return self._wa12_struct_finalize(sess, buf, from_e164, raw_from)
        # a pending qty reply for the just-bound item.
        if buf.get("qty_for"):
            m = re.match(r"^\s*(?:x\s*)?(\d+)\s*$", norm)
            qty = max(1, int(m.group(1))) if m else 1
            for it in buf["items"]:
                if it.get("product_id") == buf["qty_for"] and not it.get("_qtyset"):
                    it["qty"] = qty
                    it["_qtyset"] = True
                    break
            buf["qty_for"] = False
            sess._set_buffer(buf)
            return self._wa6_reply(raw_from, from_e164, _(
                "Added ×%d. What's the next item? (or *done*)") % qty)
        # NOT-IN-CATALOGUE custom line: "custom <desc> at <amt>" / "<desc> @ amt".
        m = re.match(r"(?:custom\s+)?(.+?)\s+(?:at|@)\s+([0-9]+(?:\.[0-9]+)?)\s*$",
                     raw, re.I)
        if m and not self._wa6_match_one(m.group(1)).get("product_id"):
            desc, amt = m.group(1).strip(), float(m.group(2))
            if amt <= _WA12_PLACEHOLDER_RATE:
                return self._wa6_reply(raw_from, from_e164, _(
                    "Give a real per-day price for \"%s\".") % desc)
            buf["items"].append({"product_id": False, "product_name": desc,
                                 "custom_desc": desc, "rep_price": amt,
                                 "qty": 1, "_qtyset": False})
            buf["qty_for"] = False
            sess._set_buffer(buf)
            return self._wa6_reply(raw_from, from_e164, _(
                "Added *%s* (custom, %s/day). How many? (or just say the next "
                "item)") % (desc, amt))
        # match ONE item (scoped, packages-excluded by the matcher).
        hit = self._wa6_match_one(raw)
        if (hit.get("status") == "matched"
                and hit.get("confidence") in ("exact", "strong")):
            return self._wa12_struct_offer_confirm(
                sess, buf, hit, from_e164, raw_from)
        # ambiguous / family -> the category-scoped LIST.
        fam = hit.get("family") or self._wa6_family_code(raw) or ""
        is_v = bool(fam and self._wa12_is_family_term(raw))
        cids = (self._wa12_family_candidate_ids(fam) if is_v
                else self._wa12_suggestion_ids(hit.get("suggestions") or []))
        if cids:
            buf["pending_item"] = {"raw": raw, "family": fam, "_variant": is_v,
                                   "_cand_ids": cids}
            sess._set_buffer(buf)
            return self._wa12_struct_send_item_list(
                sess, buf, raw, fam, is_v, cids, from_e164, raw_from)
        # nothing matched -> offer the custom-line route (never dead-end).
        return self._wa6_reply(raw_from, from_e164, _(
            "I couldn't find \"%s\" in the catalogue. Not listed? Type the "
            "item and its per-day price (e.g. *bespoke arch 250*). Or try "
            "another name.") % raw)

    def _wa12_struct_send_item_list(self, sess, buf, label, fam, is_v, cids,
                                    from_e164, raw_from):
        """Present the item candidate LIST (reuses the proven _wa12_send_pick
        rails). Tap -> wa12_pick routed to the structured bind."""
        kind = "variant" if is_v else "ambiguous"
        return self._wa12_send_pick(
            sess, "s0", kind, cids, label, fam, from_e164, raw_from,
            seq=(buf.get("v") or 0))

    def _wa12_struct_offer_confirm(self, sess, buf, hit, from_e164, raw_from):
        """A confident item -> ✅ + [✓ Correct][✗ Change] (the stepper card the
        rep likes). ✓ logs it + asks qty; ✗ re-opens the family list."""
        secret = self.env["ir.config_parameter"].sudo().get_param(
            "database.secret") or ""
        prod = self.env["product.template"].sudo().browse(hit["product_id"])
        rate, cur = self._wa12_price_lookup(prod)
        money = ("%s %.2f/day" % (cur, rate)
                 if rate and rate > _WA12_PLACEHOLDER_RATE
                 else _("rate set at review"))
        buf["pending_item"] = {"raw": hit.get("raw") or prod.name,
                               "confirm_pid": prod.id,
                               "family": hit.get("family") or ""}
        sess._set_buffer(buf)
        ok = wa_payload.encode(secret, "wa12_ok", sess.id, "s0", prod.id)
        chg = wa_payload.encode(secret, "wa12_change", sess.id, "s0", prod.id)
        return self._wa6_send_buttons(raw_from, from_e164, _(
            "✅ *%s* — %s") % (prod.name, money), [
            {"id": ok, "title": _("✓ Correct")[:self._WA12_BTN_TITLE]},
            {"id": chg, "title": _("✗ Change")[:self._WA12_BTN_TITLE]}])

    def _wa12_struct_log_item(self, sess, buf, prod, from_e164, raw_from):
        """LOG a confirmed item (qty defaults 1; ask the rep for a count) ->
        'next or done'."""
        buf["items"].append({"product_id": prod.id, "product_name": prod.name,
                             "qty": 1, "rep_price": None, "_qtyset": False})
        buf["pending_item"] = None
        buf["qty_for"] = prod.id
        sess._set_buffer(buf)
        return self._wa6_reply(raw_from, from_e164, _(
            "Added *%s*. How many? (a number, or just say the next item / "
            "*done*)") % prod.name)

    def _wa12_struct_finalize(self, sess, buf, from_e164, raw_from):
        """'done' -> build the draft from the LOGGED items + resolved client +
        date, hand to the UNCHANGED q_confirm review (totals/VAT/discount/edit/
        submit)."""
        items = [{"product_id": it["product_id"],
                  "product_name": it["product_name"], "qty": it.get("qty") or 1,
                  "rep_price": it.get("rep_price"),
                  "custom_desc": it.get("custom_desc")}
                 for it in (buf.get("items") or [])]
        if not items:
            return self._wa6_reply(raw_from, from_e164, _(
                "No items yet — name the first item, or *cancel*."))
        partner = self.env["res.partner"].sudo().browse(
            buf.get("partner_id") or 0).exists()
        if not partner:
            return self._wa6_reply(raw_from, from_e164, _(
                "I lost the client — please start the quote again."))
        extras = {}
        if buf.get("note"):
            extras["event_name"] = buf["note"]
        # MONEY: pass the computed hire DURATION so every line drafts at
        # rate × qty × days (the duration-not-applied fix).
        return self._wa12_quote_from_slots(
            sess.user_id, partner, items, buf.get("date_txt") or "",
            buf.get("days") or 1, from_e164, raw_from, extras=extras)

    def _wa12_handle_convo(self, sess, body, from_e164, raw_from):
        """WA-12.2 conversational steps. q_items = the M1 confirm-before-draft
        gate (NO quote exists until yes); q_client / q_itemreq = bare-intent
        slot fill (M5). Deterministic corrections first; complaint language ->
        the repair prompt (M4)."""
        import re
        sender = sess.user_id
        if not (sender and sender.active and self._wa12_can_quote(sender)):
            sess.sudo().write({"active": False})
            return self._wa6_reply(raw_from, from_e164, _(_WA12_REFUSAL))
        raw = (body or "").strip()
        norm = " ".join(raw.lower().split())
        buf = self._wa12_buf_migrate(sess._get_buffer())   # yields v4

        if self._wa12_is_cancel(norm):
            sess.sudo().write({"step": "done", "active": False})
            return self._wa6_reply(raw_from, from_e164, _("Quote cancelled."))

        # WA-12.4: the FOCUSED SUB-STATE owns the turn. Gated on step==q_items
        # AND focus (can never fire at q_confirm even with a dirty buffer). This
        # MUST precede greeting / discovery / submit / show-continue / complaint
        # below -- those call the legacy combined block and would re-create the
        # "where do I tap" confusion mid-step. Inside focus, greeting/continue/a
        # question all re-present the cursor; a re-typed item re-matches item N;
        # nothing here can spawn a new line except an explicit `add <item>`.
        if sess.step == "q_items" and buf.get("focus") and buf.get("cur"):
            return self._wa12_focus_dispatch(
                sess, buf, raw, norm, from_e164, raw_from)

        # F6: a greeting mid-session greets + offers continue/cancel, never the
        # syntax card. SKIPPED at q_client (FSM-8): there the whole message is a
        # client NAME slot, so a client literally named 'GM'/'Hello' must still
        # resolve. 'continue' is advertised (FSM-1: 'resume' is a Meta opt-in
        # keyword, released to the WA-2 rail before this handler ever runs).
        if norm in _WA12_GREETINGS and sess.step != "q_client":
            who = (sender.name or "").split(" ")[0]
            return self._wa6_reply(raw_from, from_e164, _(
                "Hi %s 👋 — we have an unconfirmed quote in progress for %s. "
                "Reply *continue* to see where we were, or *cancel* to drop it."
            ) % (who, buf.get("client_txt") or _("a client")))

        if sess.step == "q_client":
            partner, candidates = self._wa12_client_candidates(raw)
            if partner:
                # WA-12.6 structured: client resolved -> LOG + advance to the
                # EVENT step (the old path went straight to items).
                if buf.get("structured"):
                    return self._wa12_struct_after_client(
                        sess, buf, partner, from_e164, raw_from)
                buf.update({"client_txt": partner.name,
                            "partner_id": partner.id})
                sess.sudo().write({"step": "q_itemreq"})
                sess._set_buffer(buf)
                return self._wa6_reply(raw_from, from_e164, _(
                    "%s — what items?") % partner.name)
            return self._wa12_start_client_intake(
                sender, raw, candidates, buf.get("matched") or [],
                buf.get("date_txt") or "", buf.get("days") or 1,
                from_e164, raw_from, prefills=buf.get("prefills") or {},
                structured=bool(buf.get("structured")))

        # M-B: a catalogue-discovery question at either item step lists the
        # family by its EXACT catalogue names (the pick-list the rep chooses
        # from), instead of trying to match the question as an item.
        if sess.step in ("q_itemreq", "q_items"):
            disc = self._wa12_discovery_family(raw)
            if disc:
                names = self._wa12_family_names(disc)
                if names:
                    return self._wa6_reply(raw_from, from_e164, _(
                        "Our %s options:\n%s\n\nReply with one (name or size).")
                        % (disc, "\n".join("• %s" % n for n in names[:12])))

        if sess.step == "q_itemreq":
            # M-C: strip a correction lead-in ('no, it's an LED screen') so it
            # re-searches as the item, never 'none'.
            search = self._wa12_strip_correction(raw) or raw
            # F2 (review FSM-3): the confidence gate — weak hits become
            # unmatched picks in the confirm echo, never confident rows.
            matched, unmatched = self._wa12_match_text_items(search)
            if not matched and not unmatched:
                return self._wa6_reply(raw_from, from_e164, _(
                    "I couldn't match those in the catalogue — try item names "
                    "like on the rate card (e.g. `RGB LED CAN x5`)."))
            return self._wa12_open_items_confirm(
                sender, buf.get("client_txt") or "", matched, unmatched,
                buf.get("date_txt") or "", buf.get("prefills") or {},
                from_e164, raw_from, partner_id=buf.get("partner_id") or False)

        # ---- q_items: the confirm-before-draft gate (M1). ----
        if norm in _WA12_SUBMIT_WORDS:
            # WA-12.3 yes-projection: draft ONLY the matched lines (an unmatched/
            # pending line can't be drafted), stripped of transient keys. Same
            # contract _wa12_quote_from_slots expects.
            buf = self._wa12_buf_migrate(buf)
            matched = [{"product_id": ln["product_id"],
                        "product_name": ln["product_name"],
                        "qty": ln.get("qty") or 1,
                        "rep_price": ln.get("rep_price"),
                        "stated_price": ln.get("stated_price")}
                       for ln in buf["lines"] if ln.get("kind") == "matched"]
            pending_un = [ln for ln in buf["lines"]
                          if ln.get("kind") == "unmatched"]
            if not matched:
                return self._wa6_reply(raw_from, from_e164, _(
                    "Nothing matched to draft yet — re-type the items, or "
                    "*cancel*."))
            if pending_un:
                # don't silently drop unresolved lines on submit -- flag them.
                return self._wa6_reply(raw_from, from_e164, _(
                    "%d item(s) still need a pick before I draft: %s. "
                    "Resolve them (tap an option or `remove <n>`), then *yes*.")
                    % (len(pending_un),
                       ", ".join('"%s"' % (u.get("raw") or "")
                                 for u in pending_un)))
            sess.sudo().write({"step": "done", "active": False})
            partner = self.env["res.partner"].sudo().browse(
                buf.get("partner_id") or 0).exists()
            if not partner:
                partner, candidates = self._wa12_client_candidates(
                    buf.get("client_txt") or "")
            if not partner:
                return self._wa12_start_client_intake(
                    sender, buf.get("client_txt") or "", candidates, matched,
                    buf.get("date_txt") or "", buf.get("days") or 1,
                    from_e164, raw_from, prefills=buf.get("prefills") or {})
            return self._wa12_quote_from_slots(
                sender, partner, matched, buf.get("date_txt") or "",
                buf.get("days") or 1, from_e164, raw_from,
                extras=buf.get("prefills") or {})

        # F3: "show me"/"preview"/"continue" is NOT a yes — re-show the confirm
        # echo; nothing is drafted yet. (FSM-1: 'continue' is the advertised
        # recovery verb; 'resume' kept as an alias for anyone who types it with
        # filler so the deterministic parser doesn't bounce them.)
        if norm in _WA12_SHOW_WORDS or norm in _WA12_RESUME_WORDS:
            note = "" if norm in _WA12_RESUME_WORDS else _(
                "Nothing is drafted yet — there's no PDF until you confirm. ")
            sess._set_buffer(buf)
            return self._wa6_reply(raw_from, from_e164, "%s%s" % (
                note, self._wa12_items_confirm_text(buf)))

        # complaint -> repair (M4), before any command parsing.
        if any(t in norm for t in _WA12_COMPLAINT_TOKENS):
            return self._wa12_repair_prompt(raw_from, from_e164)

        # WA-12.3 precedence step 2: a NARROW follow-up (>10 overflow) re-targets
        # the remembered line, scoped to its family; OR a bare free-text reply to
        # a live `pending` pick narrows that line. Only when the text is not a
        # command/yes/cancel (those are handled above / below).
        nt = (buf.get("narrow_target") or {}) if isinstance(buf, dict) else {}
        if nt.get("lid"):
            narrowed = self._wa12_try_narrow(sess, buf, raw, from_e164, raw_from)
            if narrowed is not None:
                return narrowed

        # deterministic corrections first (free). C line-number commands resolve
        # here (number-aware find_one).
        handled = self._wa12_q_items_try(sess, buf, raw, from_e164, raw_from)
        if handled is not None:
            return handled

        # D: natural corrections -> a LIST of translated commands (one per line),
        # two-pass lid-resolved so a `remove` can't shift a later command's
        # number, then each re-run through the SAME deterministic parser. REPAIR
        # -> the repair prompt.
        cmds = self._wa12_llm_translate_items(raw, buf)
        if cmds:
            if any(c.upper().startswith("REPAIR") for c in cmds):
                return self._wa12_repair_prompt(raw_from, from_e164)
            # FSM-7: a translated 'cancel'/'yes' is handled here, never executed
            # as a state transition by the deterministic re-run.
            if any(self._wa12_is_cancel(" ".join(c.lower().split()))
                   for c in cmds):
                sess.sudo().write({"step": "done", "active": False})
                return self._wa6_reply(raw_from, from_e164, _("Quote cancelled."))
            real = [c for c in cmds
                    if " ".join(c.lower().split()) not in _WA12_SUBMIT_WORDS]
            if not real:
                return self._wa6_reply(raw_from, from_e164, _(
                    "Ready when you are — reply *yes* to draft the quote."))
            buf = self._wa12_buf_migrate(buf)
            resolved = self._wa12_batch_resolve_lids(buf, real)
            applied = 0
            for cmd in resolved:
                if self._wa12_q_items_try(sess, buf, cmd, from_e164, raw_from,
                                          batch=True) == "applied":
                    applied += 1
            if applied:
                sess._set_buffer(buf)
                # if the batch left a line needing a pick, offer the first one.
                pick_ln = next(
                    (ln for ln in buf["lines"]
                     if ln.get("kind") == "unmatched" and ln.get("_cand_ids")),
                    None)
                if pick_ln:
                    self._wa6_reply(raw_from, from_e164,
                                    self._wa12_items_confirm_text(buf))
                    return self._wa12_offer_pick_for_buffer(
                        sess, buf, pick_ln, from_e164, raw_from)
                return self._wa6_reply(raw_from, from_e164,
                                       self._wa12_items_confirm_text(buf))
        # MATCH-2/FSM-5: neither a command nor a translatable correction -> if
        # the raw text weak/near-matches catalogue items, SURFACE them as picks
        # in the confirm echo (never silently drop); else the syntax card.
        surfaced = self._wa12_surface_unmatched(sess, buf, raw, from_e164,
                                                raw_from)
        if surfaced is not None:
            return surfaced
        return self._wa6_reply(raw_from, from_e164, _(
            "Reply *yes* to draft, *cancel*, or correct me by line number — "
            "`2 = <item>` · `remove 3` · `qty 1 to 4` · `price 2 <amt>` · "
            "a date · `client <name>`."))

    def _wa12_surface_unmatched(self, sess, buf, raw, from_e164, raw_from):
        """MATCH-2/FSM-5: a re-typed item that only WEAK/near-matches is added
        to the confirm echo's unmatched bucket WITH its suggestions (a pick),
        never silently dropped. Returns the reshow, or None if the text yields
        no catalogue signal at all (-> the caller's syntax card)."""
        _adds, weak = self._wa12_match_text_items(raw)
        weak = [w for w in weak if w.get("suggestions")]
        if not weak:
            return None
        buf = self._wa12_buf_migrate(buf)
        seen = {(ln.get("raw") or "").lower() for ln in buf["lines"]
                if ln.get("kind") == "unmatched"}
        first_new = None
        for w in weak:
            nm = w.get("name") or ""
            if nm.lower() in seen:
                continue
            fam = w.get("family") or self._wa6_family_code(nm) or ""
            is_v = bool(fam and self._wa12_is_family_term(nm))
            cids = (self._wa12_family_candidate_ids(fam) if is_v
                    else self._wa12_suggestion_ids(w.get("suggestions") or []))
            ln = self._wa12_add_line(
                buf, kind="unmatched", raw=nm, qty=w.get("qty") or 1,
                suggestions=w.get("suggestions") or [], family=fam,
                _variant=is_v, _cand_ids=cids)
            first_new = first_new or (ln if cids else None)
        sess._set_buffer(buf)
        if first_new:
            self._wa6_reply(raw_from, from_e164,
                            self._wa12_items_confirm_text(buf))
            return self._wa12_offer_pick_for_buffer(
                sess, buf, first_new, from_e164, raw_from)
        return self._wa6_reply(raw_from, from_e164,
                               self._wa12_items_confirm_text(buf))

    # ================================================================
    # WA-12.3 -- pick/correct interaction layer (B tap-pick, C line-number,
    # D conversational). Buffer schema v3: ONE ordered `lines` list with a
    # stable `lid` per line + at-most-one `pending` pick slot. Design:
    # docs/phase-11/WA12_3_interaction_redesign_spec.md. The matcher
    # (_wa6_match_one) is byte-UNCHANGED; the variant-vs-unsure signal is
    # derived HERE from family + confidence + a family-term test.
    # ================================================================
    def _wa12_buf_migrate(self, buf):
        """Fold a legacy {matched,unmatched} buffer into v3 {lines,next_lid}.
        Idempotent: a v3 buffer returns unchanged. Called at the TOP of every
        q_items buffer consumer so a pre-deploy session degrades cleanly and no
        path leaves BOTH `lines` and the legacy keys."""
        if not isinstance(buf, dict):
            return {"v": 4, "next_lid": 1, "lines": [], "pending": None,
                    "cur": None, "focus": False, "seq": 0}
        if buf.get("v") == 4 and "lines" in buf:
            return buf
        if buf.get("v") == 3 and "lines" in buf:
            # v3 -> v4: stamp per-line state, add cursor fields, PRESERVE a live
            # `pending` (a pre-deploy mid-pick session keeps its disambiguation).
            for ln in buf.get("lines") or []:
                ln.setdefault("state", "pending")
            buf.setdefault("cur", None)
            buf.setdefault("focus", False)
            buf.setdefault("seq", 0)
            buf["v"] = 4
            return buf
        lines, lid = [], 1
        for it in (buf.get("matched") or []):
            lines.append({
                "lid": lid, "kind": "matched", "state": "pending",
                "product_id": it.get("product_id"),
                "product_name": it.get("product_name") or "",
                "qty": it.get("qty") or 1,
                "rep_price": it.get("rep_price"),
                "stated_price": it.get("stated_price")})
            lid += 1
        for um in (buf.get("unmatched") or []):
            lines.append({
                "lid": lid, "kind": "unmatched", "state": "pending",
                "raw": um.get("name") or "", "qty": um.get("qty") or 1,
                "stated_price": um.get("stated_price"),
                "suggestions": um.get("suggestions") or [],
                "family": um.get("family") or ""})
            lid += 1
        buf["lines"] = lines
        buf["next_lid"] = lid
        buf["v"] = 4
        buf.setdefault("cur", None)
        buf.setdefault("focus", False)
        buf.setdefault("seq", 0)
        buf.setdefault("pending", None)
        buf.pop("matched", None)
        buf.pop("unmatched", None)
        return buf

    def _wa12_add_line(self, buf, **vals):
        """Append a line, allocating a fresh never-reused lid. Returns it. New
        lines are born 'pending' (the cursor will reach them)."""
        lid = buf.get("next_lid") or 1
        ln = dict(vals)
        ln["lid"] = lid
        ln.setdefault("qty", 1)
        ln.setdefault("state", "pending")
        buf["next_lid"] = lid + 1
        buf.setdefault("lines", []).append(ln)
        return ln

    def _wa12_line_by_lid(self, buf, lid):
        for ln in buf.get("lines") or []:
            if ln.get("lid") == lid:
                return ln
        return None

    def _wa12_line_by_number(self, buf, n):
        """1-based display number -> the line dict, or None if out of range."""
        lines = buf.get("lines") or []
        if 1 <= n <= len(lines):
            return lines[n - 1]
        return None

    def _wa12_set_pending(self, buf, lid, kind, candidates, label, family,
                          overflow=False, seq=None):
        buf["pending"] = {"lid": lid, "kind": kind,
                          "candidates": list(candidates), "label": label,
                          "family": family or "", "overflow": overflow,
                          "seq": seq}

    def _wa12_clear_pending_for(self, buf, lid):
        p = buf.get("pending")
        if p and p.get("lid") == lid:
            buf["pending"] = None

    # ---- WA-12.4 stepper: cursor + focused sub-state over the v4 lines. ----
    def _wa12_first_unresolved(self, buf):
        return next((ln for ln in buf.get("lines") or []
                     if ln.get("state") == "pending"), None)

    def _wa12_assert_focus(self, buf):
        """Invariant: focus True <=> cur is a live pending line. Defensive; a
        violation re-anchors rather than raises (a stale buffer must degrade)."""
        cur = buf.get("cur")
        ln = self._wa12_line_by_lid(buf, cur) if cur else None
        if buf.get("focus") and not (ln and ln.get("state") == "pending"):
            nxt = self._wa12_first_unresolved(buf)
            buf["cur"] = nxt["lid"] if nxt else None
            buf["focus"] = bool(nxt)

    def _wa12_pos(self, buf, ln):
        try:
            return (buf.get("lines") or []).index(ln) + 1
        except ValueError:
            return 1

    def _wa12_counter(self, buf, ln):
        i, n = self._wa12_pos(buf, ln), len(buf.get("lines") or [])
        return _("%s of %d") % (_WA12_NUM.get(i, "(%d)" % i), n)

    def _wa12_family_word_for(self, label, fam):
        """Alias-aware family word: prefer the term-alias expansion of `label`
        ('blinders' -> 'molefays') over the generic family word ('lights')."""
        kind, val, _exp = self._r2_alias_expand(label or "")
        if kind == "term" and val:
            w = val.strip()
            return w if w.endswith("s") else (w + "s")
        return self._wa12_family_word(fam)

    def _wa12_advance_cursor(self, sess, buf, from_e164, raw_from):
        """Resolved one item -> move the cursor to the next pending line and
        present it; when none remain, finalize to the draft. The SINGLE exit for
        'an item is done'."""
        buf["pending"] = None
        nxt = self._wa12_first_unresolved(buf)
        if nxt is None:
            buf["cur"] = None
            buf["focus"] = False
            sess._set_buffer(buf)
            return self._wa12_finalize_to_draft(sess, buf, from_e164, raw_from)
        buf["cur"] = nxt["lid"]
        buf["focus"] = True
        sess._set_buffer(buf)
        return self._wa12_present_item(sess, buf, nxt, from_e164, raw_from)

    def _wa12_finalize_to_draft(self, sess, buf, from_e164, raw_from):
        """All items resolved -> project the draftable lines (matched +
        confirmed/picked ONLY; skipped/unmatched/pending excluded) and route to
        the UNCHANGED _wa12_quote_from_slots (-> q_confirm + [Submit][Edit])."""
        buf["focus"] = False
        buf["cur"] = None
        buf["pending"] = None
        draftable = [{"product_id": ln["product_id"],
                      "product_name": ln["product_name"],
                      "qty": ln.get("qty") or 1,
                      "rep_price": ln.get("rep_price"),
                      "stated_price": ln.get("stated_price")}
                     for ln in buf.get("lines") or []
                     if ln.get("kind") == "matched"
                     and ln.get("state") in ("confirmed", "picked")]
        sender = sess.user_id
        if not draftable:
            sess.sudo().write({"step": "done", "active": False})
            return self._wa6_reply(raw_from, from_e164, _(
                "Nothing left to quote — every item was skipped. Send new "
                "items or *cancel*."))
        partner = self.env["res.partner"].sudo().browse(
            buf.get("partner_id") or 0).exists()
        candidates = self.env["res.partner"].sudo().browse()
        if not partner:
            partner, candidates = self._wa12_client_candidates(
                buf.get("client_txt") or "")
        if not partner:
            return self._wa12_start_client_intake(
                sender, buf.get("client_txt") or "", candidates, draftable,
                buf.get("date_txt") or "", buf.get("days") or 1,
                from_e164, raw_from, prefills=buf.get("prefills") or {})
        return self._wa12_quote_from_slots(
            sender, partner, draftable, buf.get("date_txt") or "",
            buf.get("days") or 1, from_e164, raw_from,
            extras=buf.get("prefills") or {})

    # ---- the variant-vs-unsure signal + candidate sources (matcher untouched).
    def _wa12_is_family_term(self, raw):
        """True when the rep NAMED a family/alias (a variant pick is owed), not
        a specific product. Reuses the matcher's own public helpers -- a
        confirmed CATEGORY alias, or a synonym-derived family with no residual
        product token (modulo stopwords / generic nouns)."""
        import re
        raw = (raw or "").strip()
        if not raw:
            return False
        kind, val, expanded = self._r2_alias_expand(raw)
        if kind == "category":
            return True
        # a confirmed TERM alias whose expansion is itself a bare family word
        # ("blinder" -> term "molefay" -> lighting family) is a variant pick.
        if kind == "term" and self._wa6_family_code(val or "") \
                and self._wa12_is_family_term(val or ""):
            return True
        fam = self._wa6_family_code(raw)
        if not fam:
            return False
        # the family synonym IS essentially the whole phrase (no extra product
        # token) -> a bare family word like "blinder"/"screen"/"cans".
        toks = [t for t in re.findall(r"[a-z0-9.]+", raw.lower())
                if t not in _WA6_STOP and t not in _WA6_GENERIC_NOUN]
        # strip the tokens that themselves derive the family.
        residual = [t for t in toks if not self._wa6_family_code(t) == fam]
        return len(residual) == 0

    def _wa12_family_candidate_ids(self, fam, limit=10):
        """In-family product ids (the variant set) -- NOT from suggestions[:3]
        (the matcher caps that at 3). Prefer products whose equipment_category_id
        IS this family (the keystone made categories reliable) so a name-synonym
        leak from an UNcategorised product can't pull a cross-family item into
        the variant list. Falls back to the name-synonym set only if the
        category yields nothing."""
        if not fam:
            return []
        PT = self.env["product.template"].sudo()
        Cat = self.env["neon.equipment.category"].sudo()
        cat = Cat.search([("code", "=", fam)], limit=1)
        if cat:
            by_cat = PT.search([("is_workshop_item", "=", True),
                                ("equipment_category_id", "=", cat.id)])
            if by_cat:
                return by_cat.ids[:limit]
        pkg = Cat.search([("code", "=", "packages")], limit=1)
        dom = [("is_workshop_item", "=", True)]
        if pkg:
            dom.append(("equipment_category_id", "!=", pkg.id))
        cands = PT.search(dom).filtered(lambda p: self._wa6_in_family(p, fam))
        return cands.ids[:limit]

    def _wa12_suggestion_ids(self, names):
        """Map matcher `suggestions` NAMES -> product ids by exact _r2_norm
        equality within the workshop catalogue. EXCLUDES the Packages family +
        test residue: a raw `name ilike "3M X 2M SCREEN"` otherwise matches a
        PACKAGE whose long name embeds that phrase (wire 675-707), and prefers
        an EXACT _r2_norm match so a substring package can't win. Caps at 3."""
        if not names:
            return []
        PT = self.env["product.template"].sudo()
        pkg = self.env["neon.equipment.category"].sudo().search(
            [("code", "=", "packages")], limit=1)
        out = []
        for nm in names[:3]:
            want = self._r2_norm(nm)
            dom = [("is_workshop_item", "=", True), ("name", "ilike", nm),
                   ("name", "not ilike", "[TEST"),
                   ("name", "not ilike", "REMOTES")]
            if pkg:
                dom.append(("equipment_category_id", "!=", pkg.id))
            p = PT.search(dom, limit=8)
            # EXACT normalised-name match only -- never a substring package.
            hit = p.filtered(lambda x: self._r2_norm(x.name) == want)[:1]
            if hit and hit.id not in out:
                out.append(hit.id)
        return out

    _WA12_FAMILY_WORD = {
        "visual": "screens", "lighting": "lights", "sound": "speakers",
        "trussing": "truss pieces", "staging": "stage pieces",
        "effects": "effects units", "cabling": "cables",
        "dance_floor": "dance-floor panels", "laptops": "laptops"}

    def _wa12_family_word(self, fam):
        return self._WA12_FAMILY_WORD.get(fam, _("options"))

    def _wa12_build_buf_lines(self, buf, matched, unmatched):
        """Build/extend the v3 `lines` from a fresh _wa12_match_text_items
        result. Confident hits -> matched lines; weak/no hits -> unmatched lines
        carrying their family + a transient `_variant`/`_cand_ids` so the picker
        can frame a family variant vs a genuinely-unsure 'did you mean'. q_items
        ONLY (the matcher is unchanged; the signal is derived here)."""
        buf = self._wa12_buf_migrate(buf)
        for it in matched or []:
            self._wa12_add_line(
                buf, kind="matched", product_id=it.get("product_id"),
                product_name=it.get("product_name") or "",
                qty=it.get("qty") or 1, rep_price=it.get("rep_price"),
                stated_price=it.get("stated_price"))
        for um in unmatched or []:
            raw = um.get("name") or ""
            fam = um.get("family") or self._wa6_family_code(raw) or ""
            is_variant = bool(fam and self._wa12_is_family_term(raw))
            cand_ids = (self._wa12_family_candidate_ids(fam) if is_variant
                        else self._wa12_suggestion_ids(um.get("suggestions") or []))
            self._wa12_add_line(
                buf, kind="unmatched", raw=raw, qty=um.get("qty") or 1,
                stated_price=um.get("stated_price"),
                suggestions=um.get("suggestions") or [], family=fam,
                _variant=is_variant, _cand_ids=cand_ids)
        return buf

    # ---- B: present a pick (count branching + Meta truncation + framing).
    _WA12_BTN_TITLE = 20
    _WA12_LIST_TITLE = 24
    _WA12_LIST_MAX = 10

    def _wa12_send_pick(self, sess, target, kind, cand_ids, label, family,
                        from_e164, raw_from, counter=None, seq=None,
                        drop_pid=None):
        """Offer the candidate set as taps. <=2 -> buttons (+skip); >=3 -> LIST
        (so a 'None of these' row never displaces a candidate); >10 -> 9 + a
        'Type to narrow' row. Titles truncated to Meta limits; the list-row
        DESCRIPTION carries the FULL name + per-day rate. `target` is 'b<lid>'
        (q_items) or 'l<line_id>'. WA-12.4: counter prefix ("② of 4"), seq in the
        payloads (idempotency), drop_pid (exclude a just-rejected product), and
        an alias-aware family word ("blinders -> molefays")."""
        PT = self.env["product.template"].sudo()
        secret = self.env["ir.config_parameter"].sudo().get_param(
            "database.secret") or ""
        if drop_pid:
            cand_ids = [p for p in cand_ids if p != drop_pid]
        cand_ids = [p for p in cand_ids if PT.browse(p).exists()]
        if not cand_ids:
            return self._wa6_reply(raw_from, from_e164, _(
                "I don't have a confident option for that — please re-type it."))
        if kind == "variant":
            body = _("*%s* → %s — which one?") % (
                label, self._wa12_family_word_for(label, family))
        else:
            body = _("\"%s\" — did you mean one of these?") % label
        if counter:
            body = "%s\n%s" % (counter, body)

        def _enc(intent, *extra):
            args = [sess.id, target] + list(extra)
            if seq is not None:
                args.append(seq)
            return wa_payload.encode(secret, intent, *args)

        def pick(pid):
            return _enc("wa12_pick", pid)
        skip = _enc("wa12_pick_skip")
        more = _enc("wa12_pick_more")

        def desc(pid):
            prod = PT.browse(pid)
            rate, cur = self._wa12_price_lookup(prod)
            d = ("%s · %s %.2f/day" % (prod.name, cur, rate)
                 if rate and rate > _WA12_PLACEHOLDER_RATE else prod.name)
            return d[:72]
        n = len(cand_ids)
        if n <= 2:
            buttons = [{"id": pick(p),
                        "title": PT.browse(p).name[:self._WA12_BTN_TITLE]}
                       for p in cand_ids]
            buttons.append({"id": skip,
                            "title": _("None of these")[:self._WA12_BTN_TITLE]})
            return self._wa6_send_buttons(raw_from, from_e164, body, buttons)
        show = (cand_ids[:self._WA12_LIST_MAX - 1]
                if n > self._WA12_LIST_MAX else cand_ids)
        rows = [{"id": pick(p),
                 "title": PT.browse(p).name[:self._WA12_LIST_TITLE],
                 "description": desc(p)} for p in show]
        if n > self._WA12_LIST_MAX:
            rows.append({"id": more,
                         "title": _("Type to narrow")[:self._WA12_LIST_TITLE],
                         "description": _("None of these — type a few more words")})
            body += _("\n(showing the closest %d — or narrow it)") % len(show)
        else:
            rows.append({"id": skip,
                         "title": _("None of these")[:self._WA12_LIST_TITLE],
                         "description": _("none of these")})
        return self._wa6_send_list(raw_from, from_e164, body, _("Pick item"),
                                   rows)

    # ================================================================
    # WA-12.4 -- the one-item stepper: presenters + focused dispatch. Each item
    # is resolved in its OWN message with a counter; ALL input while focused on
    # item N applies to N only and can NEVER spawn a new line (the fix for the
    # "where do I tap" -> matched-as-item regression, Robin wire 618-629).
    # ================================================================
    def _wa12_present_item(self, sess, buf, ln, from_e164, raw_from):
        """Bump the idempotency seq, then present the cursor line: a confident
        matched line as a ✓/✗ card, an unmatched line as a pick LIST."""
        self._wa12_assert_focus(buf)
        buf["seq"] = (buf.get("seq") or 0) + 1
        if ln.get("kind") == "matched":
            return self._wa12_present_confident(sess, buf, ln, from_e164,
                                                raw_from)
        return self._wa12_present_pick(sess, buf, ln, from_e164, raw_from)

    def _wa12_present_confident(self, sess, buf, ln, from_e164, raw_from):
        """A confident line -> "✅ <product> ×qty — $X/day" + [✓ Correct][✗
        Change], with the progress counter. NOT auto-confirmed (D-NOAUTO)."""
        secret = self.env["ir.config_parameter"].sudo().get_param(
            "database.secret") or ""
        prod = self.env["product.template"].sudo().browse(ln["product_id"])
        rate, cur = self._wa12_price_lookup(prod)
        if rate is not None and rate > _WA12_PLACEHOLDER_RATE:
            money = "%s %.2f/day" % (cur, rate)
        elif ln.get("rep_price"):
            money = _("%s %.2f/day (rep-priced)") % (cur, ln["rep_price"])
        else:
            money = _("no rate yet — reply `price <amt>`")
        body = _("%s\n✅ *%s* ×%d — %s") % (
            self._wa12_counter(buf, ln), prod.name, ln.get("qty") or 1, money)
        sq = buf["seq"]
        self._wa12_set_pending(buf, ln["lid"], "confirm", [prod.id], prod.name,
                               ln.get("family") or "", seq=sq)
        sess._set_buffer(buf)
        ok = wa_payload.encode(secret, "wa12_ok", sess.id, "b%d" % ln["lid"], sq)
        chg = wa_payload.encode(secret, "wa12_change", sess.id,
                                "b%d" % ln["lid"], sq)
        return self._wa6_send_buttons(raw_from, from_e164, body, [
            {"id": ok, "title": _("✓ Correct")[:self._WA12_BTN_TITLE]},
            {"id": chg, "title": _("✗ Change")[:self._WA12_BTN_TITLE]}])

    def _wa12_present_pick(self, sess, buf, ln, from_e164, raw_from):
        """An unmatched line -> the candidate LIST (variant or ambiguous),
        counter-prefixed. No candidates -> ask for a re-type (still focused)."""
        cand_ids = ln.get("_cand_ids") or []
        sq = buf["seq"]
        kind = "variant" if ln.get("_variant") else "ambiguous"
        if not cand_ids:
            self._wa12_set_pending(buf, ln["lid"], kind, [],
                                   ln.get("raw") or "", ln.get("family") or "",
                                   seq=sq)
            sess._set_buffer(buf)
            return self._wa6_reply(raw_from, from_e164, _(
                "%s  I couldn't place \"%s\" — type the item name, or 'skip'.")
                % (self._wa12_counter(buf, ln), ln.get("raw") or ""))
        self._wa12_set_pending(
            buf, ln["lid"], kind, cand_ids, ln.get("raw") or "",
            ln.get("family") or "",
            overflow=len(cand_ids) > self._WA12_LIST_MAX, seq=sq)
        sess._set_buffer(buf)
        return self._wa12_send_pick(
            sess, "b%d" % ln["lid"], kind, cand_ids, ln.get("raw") or "",
            ln.get("family") or "", from_e164, raw_from,
            counter=self._wa12_counter(buf, ln), seq=sq)

    def _wa12_focus_help(self, buf, ln):
        """One-line HELP for the focused item (mode-tailored)."""
        c = self._wa12_counter(buf, ln)
        if ln.get("kind") == "matched":
            return _("%s  Tap *✓ Correct* to keep it, *✗ Change* to swap it, "
                     "or type the product name. 'skip' to drop it.") % c
        return _("%s  Tap an option for \"%s\", or type the product name. "
                 "'skip' to drop it.") % (c, ln.get("raw") or "")

    def _wa12_retype_confident(self, raw, hint=None):
        """True iff `raw` confidently re-identifies a product OR names a family
        the picker can resolve. `hint` = the cursor line's family, so a bare-
        dimension correction ("3 x 2" on a screen line) is judged WITHIN that
        family (dimensional-exact -> confident) instead of failing as cross-
        category noise. Reuses the byte-unchanged matcher."""
        hit = self._wa6_match_one(raw, category_hint=hint or None)
        if hit.get("status") == "matched" and hit.get("confidence") in (
                "exact", "strong"):
            return True
        fam = hit.get("family") or hint or self._wa6_family_code(raw) or ""
        return bool(fam and self._wa12_is_family_term(raw)
                    and self._wa12_family_candidate_ids(fam))

    def _wa12_is_question(self, raw):
        """A question / meta / unrecognised message -> HELP + reshow (never a
        catalogue match). '?' or a leading wh/help token; a greeting/show/
        continue mid-step is also meta."""
        low = " ".join((raw or "").lower().split())
        if not low:
            return True
        if (low in _WA12_GREETINGS or low in _WA12_SHOW_WORDS
                or low in _WA12_RESUME_WORDS):
            return True
        if "?" in low:
            return True
        return any(low == t or low.startswith(t + " ") for t in _WA12_Q_TOKENS)

    def _wa12_focus_dispatch(self, sess, buf, raw, norm, from_e164, raw_from):
        """ALL input applies to buf['cur'] ONLY. The ONLY line-creating verb on
        this path is an explicit 'add <item>'. _wa12_q_items_try /
        _wa12_surface_unmatched / the LLM batch are NOT reachable while focused,
        so a question/unrecognised text can never spawn a new line."""
        import re
        sender = sess.user_id
        if not (sender and sender.active and self._wa12_can_quote(sender)):
            sess.sudo().write({"active": False})
            return self._wa6_reply(raw_from, from_e164, _(_WA12_REFUSAL))
        ln = self._wa12_line_by_lid(buf, buf.get("cur"))
        if ln is None:
            return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)

        # 1) explicit 'add <item>' -- the ONLY new-line verb (tight).
        m = re.match(r"^add\s+(.+)$", raw, re.I)
        if m:
            return self._wa12_focus_add_item(sess, buf, m.group(1).strip(),
                                             from_e164, raw_from)
        # 2) skip / remove / drop THIS item -> skipped, advance.
        if norm in _WA12_SKIP_WORDS:
            ln["state"] = "skipped"
            return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)
        # 3) header edits -> mutate the header, re-present the SAME item.
        m = re.match(r"^client\s+(.+)$", raw, re.I)
        if m:
            partner, _c = self._wa12_client_candidates(m.group(1).strip())
            buf["client_txt"] = partner.name if partner else m.group(1).strip()
            buf["partner_id"] = partner.id if partner else False
            sess._set_buffer(buf)
            return self._wa12_present_item(sess, buf, ln, from_e164, raw_from)
        ev_date, ph = self._wa12_resolve_date(raw)
        if not ph:
            buf["date_txt"] = ev_date.isoformat()
            sess._set_buffer(buf)
            return self._wa12_present_item(sess, buf, ln, from_e164, raw_from)
        if re.match(r"^qty\s+(?:to\s+)?\d+\s*$", norm) and \
                ln.get("kind") == "matched":
            ln["qty"] = max(1, int(re.search(r"\d+", norm).group()))
            sess._set_buffer(buf)
            return self._wa12_present_item(sess, buf, ln, from_e164, raw_from)
        m = re.match(r"^price\s+([0-9]+(?:\.[0-9]+)?)\s*$", norm)
        if m and ln.get("kind") == "matched":
            return self._wa12_focus_price(sess, buf, ln, float(m.group(1)),
                                          from_e164, raw_from)
        # 4) bare confirm on a CONFIDENT card = confirm-and-advance (BUG-6).
        if ln.get("kind") == "matched" and norm in _WA12_CONFIRM_WORDS:
            ln["state"] = "confirmed"
            return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)
        # 5) a redirected 'yes'/'submit' inside focus -> nudge, never draft.
        if norm in _WA12_SUBMIT_WORDS:
            return self._wa6_reply(raw_from, from_e164, _(
                "Let's finish item %s first — tap an option, type the item, "
                "or 'skip'.") % self._wa12_counter(buf, ln))
        # 5b) M4 complaint language mid-item -> the repair prompt (never a
        #     catalogue match). Re-present the item card FIRST (so it's still on
        #     screen), then the repair prompt as the final word.
        if any(t in norm for t in _WA12_COMPLAINT_TOKENS):
            self._wa12_present_item(sess, buf, ln, from_e164, raw_from)
            return self._wa12_repair_prompt(raw_from, from_e164)
        # 6) QUESTION / unrecognised -> HELP + RE-SHOW N. Never a catalogue
        #    match, never a new line. A confident/family RE-TYPE wins first --
        #    and confidence is judged WITH the cursor line's family as the hint,
        #    so a bare-dimension correction ("3 x 2" on a screen line) scopes to
        #    Visual and counts as confident (wire defect 7), instead of being
        #    bounced to HELP as "no confident match".
        hint = ln.get("family") or ""
        if not hint and ln.get("product_id"):
            _p = self.env["product.template"].sudo().browse(ln["product_id"])
            hint = (_p.equipment_category_id.code
                    or self._wa6_family_code(_p.name) or "")
        if self._wa12_is_question(raw) or not self._wa12_retype_confident(
                raw, hint):
            self._wa6_reply(raw_from, from_e164, self._wa12_focus_help(buf, ln))
            return self._wa12_present_item(sess, buf, ln, from_e164, raw_from)
        # 7) a deliberate CONFIDENT/family RE-TYPE of N -> re-match (with the
        #    family hint), bind or re-frame N's LIST. Never appends.
        return self._wa12_focus_retype(sess, buf, ln, raw, from_e164, raw_from)

    def _wa12_focus_retype(self, sess, buf, ln, raw, from_e164, raw_from):
        """Re-match the cursor line through the funnel. Confident -> bind N +
        advance; weak/family -> re-frame N's candidates and STAY on N (never a
        new line). Preserves the stable lid + qty. Passes the CURRENT line's
        family as the category_hint so a bare-dimension correction ("3 x 2" on a
        screen line) scopes to that family -> 3M X 2M LED SCREEN, not a cross-
        category 3M X 2M GOALPOST TRUSS (wire defect 7)."""
        lid_saved = ln["lid"]
        qty_saved = ln.get("qty") or 1
        hint = ln.get("family") or ""
        if not hint and ln.get("product_id"):
            prod0 = self.env["product.template"].sudo().browse(ln["product_id"])
            hint = (prod0.equipment_category_id.code
                    or self._wa6_family_code(prod0.name) or "")
        hit = self._wa6_match_one(raw, category_hint=hint or None)
        if hit.get("status") == "matched" and hit.get("confidence") in (
                "exact", "strong"):
            ln.clear()
            ln.update({"lid": lid_saved, "kind": "matched", "state": "picked",
                       "product_id": hit["product_id"],
                       "product_name": hit["product_name"],
                       "qty": hit.get("qty") or qty_saved,
                       "rep_price": None, "stated_price": None})
            self._wa12_clear_pending_for(buf, lid_saved)
            return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)
        fam = hit.get("family") or self._wa6_family_code(raw) or ""
        is_v = bool(fam and self._wa12_is_family_term(raw))
        cids = (self._wa12_family_candidate_ids(fam) if is_v
                else self._wa12_suggestion_ids(hit.get("suggestions") or []))
        for k in ("product_id", "product_name"):
            ln.pop(k, None)
        ln.update({"kind": "unmatched", "raw": raw,
                   "qty": hit.get("qty") or qty_saved,
                   "suggestions": hit.get("suggestions") or [], "family": fam,
                   "_variant": is_v, "_cand_ids": cids, "state": "pending"})
        return self._wa12_present_pick(sess, buf, ln, from_e164, raw_from)

    def _wa12_focus_add_item(self, sess, buf, term, from_e164, raw_from):
        """The ONLY in-focus line creator: append the term as new pending
        line(s) at the tail; the cursor stays on the current item."""
        m, u = self._wa12_match_text_items(term)
        cur_ln = self._wa12_line_by_lid(buf, buf.get("cur"))
        if not m and not u:
            self._wa6_reply(raw_from, from_e164, _(
                "Couldn't read \"%s\" as an item — finish item %s first, or "
                "type a catalogue name.") % (
                    term, self._wa12_counter(buf, cur_ln) if cur_ln else "?"))
            if cur_ln:
                return self._wa12_present_item(sess, buf, cur_ln, from_e164,
                                               raw_from)
            return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)
        self._wa12_build_buf_lines(buf, m, u)  # appends, state='pending'
        self._wa6_reply(raw_from, from_e164,
                        _("Added \"%s\" — I'll get to it.") % term)
        if cur_ln:
            return self._wa12_present_item(sess, buf, cur_ln, from_e164,
                                           raw_from)
        return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)

    def _wa12_focus_price(self, sess, buf, ln, amt, from_e164, raw_from):
        """Guarded rep-price on the cursor line (mirrors the q_items price
        guard): refuse when a catalogue rate exists; refuse a placeholder-low
        amount; else set rep_price + re-present."""
        prod = self.env["product.template"].sudo().browse(ln["product_id"])
        rate, cur = self._wa12_price_lookup(prod)
        if rate is not None and rate > _WA12_PLACEHOLDER_RATE:
            return self._wa6_reply(raw_from, from_e164, _(
                "%s has a catalogue rate (%s %.2f/day) — that's what drafts.")
                % (ln["product_name"], cur, rate))
        if amt <= _WA12_PLACEHOLDER_RATE:
            return self._wa6_reply(raw_from, from_e164, _(
                "That rate is too low — give the real day rate."))
        ln["rep_price"] = amt
        sess._set_buffer(buf)
        return self._wa12_present_item(sess, buf, ln, from_e164, raw_from)

    def _wa12_offer_pick_for_buffer(self, sess, buf, ln, from_e164, raw_from):
        """Set `pending` for an unmatched/variant buffer line and send the pick.
        Returns the send result. Candidates come from the line's transient
        `_cand_ids` (in-family variants OR suggestion ids)."""
        cand_ids = ln.get("_cand_ids") or []
        kind = "variant" if ln.get("_variant") else "ambiguous"
        self._wa12_set_pending(buf, ln["lid"], kind, cand_ids,
                               ln.get("raw") or "", ln.get("family") or "",
                               overflow=len(cand_ids) > self._WA12_LIST_MAX)
        sess._set_buffer(buf)
        return self._wa12_send_pick(
            sess, "b%d" % ln["lid"], kind, cand_ids, ln.get("raw") or "",
            ln.get("family") or "", from_e164, raw_from)

    def _wa12_offer_pick_for_replace(self, sess, buf, target_ln, new_txt,
                                     new_hit, from_e164, raw_from):
        """A non-confident REPLACE (C `<n> = <weak>` / the existing `replace`
        path / a D batch item) -> a B pick instead of a 'did you mean' text. The
        target buffer line becomes pending against the new term's candidates."""
        fam = new_hit.get("family") or self._wa6_family_code(new_txt) or ""
        is_variant = bool(fam and self._wa12_is_family_term(new_txt))
        cand_ids = (self._wa12_family_candidate_ids(fam) if is_variant
                    else self._wa12_suggestion_ids(new_hit.get("suggestions")
                                                   or []))
        if not cand_ids:
            return self._wa6_reply(raw_from, from_e164, _(
                "Couldn't confidently match \"%s\" — try a catalogue name.")
                % new_txt)
        target_ln["raw"] = new_txt
        target_ln["family"] = fam
        target_ln["_variant"] = is_variant
        target_ln["_cand_ids"] = cand_ids
        kind = "variant" if is_variant else "ambiguous"
        self._wa12_set_pending(buf, target_ln["lid"], kind, cand_ids, new_txt,
                               fam, overflow=len(cand_ids) > self._WA12_LIST_MAX)
        sess._set_buffer(buf)
        return self._wa12_send_pick(sess, "b%d" % target_ln["lid"], kind,
                                    cand_ids, new_txt, fam, from_e164, raw_from)

    # ---- B: handle the tap. Entered from _wa12_maybe_intercept (sentinel).
    def _wa12_handle_pick_tap(self, intent, parts, from_e164, raw_from, message):
        """A wa12_pick* tap. parts = [session_id, target(, product_id)]. Resolve
        the session by PHONE, then assert it matches the payload session_id
        (cross-session lid-collision guard) AND the sender is still quote-
        capable (two-factor). target = 'b<lid>' (q_items) | 'l<line_id>'
        (q_confirm). The bound product is re-validated against the OFFERED set
        so a tap can never bind a product the matcher didn't surface."""
        self._wa6_audit_in(from_e164, message, intent)
        sess = self.env["neon.wa.equip.session"].sudo()._active_for_phone(
            from_e164)
        sid = int(parts[0]) if parts and str(parts[0]).isdigit() else 0
        if not (sess and sess.id == sid
                and sess.step in ("q_items", "q_confirm", "qs_item")
                and from_e164 == sess.phone_number):
            return self._wa6_reply(raw_from, from_e164, _(
                "That choice has expired — send the items again to re-quote."))
        sender = sess.user_id
        if not (sender and sender.active and self._wa12_can_quote(sender)):
            sess.sudo().write({"active": False})
            return self._wa6_reply(raw_from, from_e164, _(_WA12_REFUSAL))
        sess.sudo().write({"last_inbound": fields.Datetime.now()})
        target = str(parts[1]) if len(parts) > 1 else ""
        # WA-12.6 structured item-loop taps carry the 's0' target.
        if sess.step == "qs_item" or target.startswith("s"):
            return self._wa12_struct_pick_apply(
                sess, intent, parts, from_e164, raw_from)
        if sess.step == "q_confirm":
            return self._wa12_pick_apply_draft(
                sess, intent, target, parts, from_e164, raw_from)
        return self._wa12_pick_apply_buffer(
            sess, intent, target, parts, from_e164, raw_from)

    def _wa12_struct_pick_apply(self, sess, intent, parts, from_e164, raw_from):
        """A structured item-loop tap. wa12_pick -> log the chosen product (re-
        validated against the pending item's offered candidates) + ask qty;
        wa12_ok -> log the confirmed product; wa12_change -> re-open the family
        list; wa12_pick_skip -> drop the in-flight item (NOT logged) + ask next.
        NEVER touches the client or earlier items."""
        buf = sess._get_buffer()
        buf = buf if isinstance(buf, dict) else {}
        pend = buf.get("pending_item") or {}
        PT = self.env["product.template"].sudo()
        if intent == "wa12_pick_skip":
            buf["pending_item"] = None
            sess._set_buffer(buf)
            return self._wa6_reply(raw_from, from_e164, _(
                "Skipped. What's the next item? (or *done*)"))
        if intent == "wa12_change":
            # re-open the family list for the in-flight item (never advances
            # without a pick -- fixes the Change->silent-skip bug).
            pid0 = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() \
                else 0
            prod0 = PT.browse(pid0)
            fam = (prod0.equipment_category_id.code
                   or self._wa6_family_code(prod0.name) or "") if prod0.exists() \
                else (pend.get("family") or "")
            cids = [p for p in (self._wa12_family_candidate_ids(fam)
                                or self._wa12_suggestion_ids([prod0.name]))
                    if p != pid0]
            if not cids:
                return self._wa6_reply(raw_from, from_e164, _(
                    "Type the correct item name (or *skip* it)."))
            buf["pending_item"] = {"raw": prod0.name if prod0.exists()
                                   else pend.get("raw") or "", "family": fam,
                                   "_variant": bool(fam), "_cand_ids": cids}
            sess._set_buffer(buf)
            return self._wa12_struct_send_item_list(
                sess, buf, buf["pending_item"]["raw"], fam, bool(fam), cids,
                from_e164, raw_from)
        # wa12_ok (confident card) OR wa12_pick (list) -> log the product.
        if intent == "wa12_ok":
            pid = pend.get("confirm_pid") or 0
        else:
            pid = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() \
                else 0
            if pid not in set(pend.get("_cand_ids") or []):
                return self._wa6_reply(raw_from, from_e164, _(
                    "That option's gone — type the item again."))
        prod = PT.browse(pid)
        if not (pid and prod.exists()):
            return self._wa6_reply(raw_from, from_e164, _(
                "That option's gone — type the item again."))
        return self._wa12_struct_log_item(sess, buf, prod, from_e164, raw_from)

    def _wa12_pick_apply_buffer(self, sess, intent, target, parts, from_e164,
                                raw_from):
        """Apply a stepper tap (wa12_ok / wa12_change / wa12_pick / _more /
        _skip) to the cursor's stable-lid buffer line. SEQ-IDEMPOTENT: a tap
        acts only if its lid is the live cursor AND its trailing seq matches the
        live pending offer; a duplicate/stale delivery just re-presents the
        cursor (no double-advance, no wrong bind)."""
        buf = self._wa12_buf_migrate(sess._get_buffer())
        lid = int(target[1:]) if target.startswith("b") and target[1:].isdigit() \
            else 0
        ln = self._wa12_line_by_lid(buf, lid)
        pend = buf.get("pending") or {}
        # trailing seq: wa12_pick carries (.., pid, seq) -> parts[3]; the others
        # carry (.., seq) -> parts[2]. Absent on a legacy payload -> None.
        seq_i = 3 if intent == "wa12_pick" else 2
        tap_seq = (int(parts[seq_i]) if len(parts) > seq_i
                   and str(parts[seq_i]).isdigit() else None)
        # idempotency + stale-anchor gate: only the live cursor's live offer acts.
        if (ln is None or lid != buf.get("cur") or not buf.get("focus")
                or (tap_seq is not None and pend.get("seq") not in
                    (None, tap_seq))):
            return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)

        if intent == "wa12_ok":
            ln["state"] = "confirmed"
            return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)
        if intent == "wa12_change":
            # re-derive family candidates from the bound product, drop the
            # rejected one, flip N back to a pending pick, re-present (NO advance).
            prod = self.env["product.template"].sudo().browse(
                ln.get("product_id"))
            fam = (prod.equipment_category_id.code
                   or self._wa6_family_code(prod.name) or "")
            cids = [p for p in (self._wa12_family_candidate_ids(fam)
                                or self._wa12_suggestion_ids([prod.name]))
                    if p != prod.id]
            ln.update({"kind": "unmatched", "raw": prod.name, "family": fam,
                       "_variant": bool(fam), "state": "pending",
                       "_cand_ids": cids})
            ln.pop("product_id", None)
            ln.pop("product_name", None)
            return self._wa12_present_pick(sess, buf, ln, from_e164, raw_from)
        if intent == "wa12_pick_more":
            return self._wa12_pick_narrow(sess, buf, lid, from_e164, raw_from)
        if intent == "wa12_pick_skip":
            ln["state"] = "skipped"
            return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)
        # wa12_pick: validate the product against the OFFERED candidate set.
        pid = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 0
        offered = set(pend.get("candidates") or []) | set(ln.get("_cand_ids")
                                                          or [])
        prod = self.env["product.template"].sudo().browse(pid)
        if not (pid and prod.exists() and pid in offered):
            return self._wa6_reply(raw_from, from_e164, _(
                "That option is no longer available — re-type the item."))
        ln.update({"kind": "matched", "product_id": pid,
                   "product_name": prod.name, "rep_price": None,
                   "stated_price": None, "state": "picked"})
        for k in ("raw", "suggestions", "family", "_variant", "_cand_ids"):
            ln.pop(k, None)
        return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)

    def _wa12_pick_apply_draft(self, sess, intent, target, parts, from_e164,
                               raw_from):
        """Apply a q_confirm tap to a real draft quote.line. Re-matches the
        product NAME through the funnel + the parity gate (uniform with the
        draft edit path), then writes as the salesperson."""
        buf = sess._get_buffer() if sess else {}
        buf = buf if isinstance(buf, dict) else {}
        quote = self.env["neon.finance.quote"].sudo().browse(
            buf.get("quote_id") or 0).exists()
        if not quote:
            return self._wa6_reply(raw_from, from_e164, _(
                "That quote is no longer editable."))
        if intent in ("wa12_pick_skip", "wa12_pick_more"):
            unpriced = self._wa12_unpriced_lines(quote)
            return self._wa6_reply(raw_from, from_e164,
                                   self._wa12_draft_summary(quote, unpriced))
        lid = int(target[1:]) if target.startswith("l") and target[1:].isdigit() \
            else 0
        line = self.env["neon.finance.quote.line"].sudo().browse(lid)
        pid = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 0
        prod = self.env["product.template"].sudo().browse(pid)
        if not (line.exists() and line.quote_id == quote and prod.exists()):
            return self._wa6_reply(raw_from, from_e164, _(
                "That option is no longer available."))
        new_hit = self._wa6_match_one(prod.name)
        if not (new_hit.get("status") == "matched"
                and new_hit.get("confidence") in ("exact", "strong")):
            return self._wa6_reply(raw_from, from_e164, _(
                "Couldn't confirm that product — re-type it."))
        sender = sess.user_id
        actor = sender.id or quote.salesperson_id.id or self.env.uid
        line.with_user(actor).sudo().write({"product_template_id": prod.id})
        return self._wa12_after_edit(
            quote, from_e164, raw_from, _("Set line to %s") % prod.name)

    def _wa12_pick_narrow(self, sess, buf, lid, from_e164, raw_from):
        """>10 overflow: remember WHICH line the next free-text should re-target,
        scoped to that line's family. The narrow phrase re-runs the matcher."""
        ln = self._wa12_line_by_lid(buf, lid)
        buf["narrow_target"] = {"lid": lid,
                                "family": (ln or {}).get("family") or ""}
        sess._set_buffer(buf)
        return self._wa6_reply(raw_from, from_e164, _(
            "Type a few more words for that item (e.g. a size or wattage) and "
            "I'll narrow it down."))

    def _wa12_q_items_try(self, sess, buf, raw, from_e164, raw_from,
                          batch=False):
        """Apply ONE q_items correction command against the v3 `lines` buffer.
        Returns the reply (or 'applied' sentinel when batch=True, mutating buf
        without replying so a multi-command batch yields ONE reshow), or None if
        ``raw`` isn't a recognised correction. WA-12.3 adds line-NUMBER
        addressing (C): a bare leading int targets a line by display position;
        `<n> = <new>` replaces; `remove <n>` removes exactly that line.
        Every replacement re-matches through _wa6_match_one + the parity gate;
        a non-confident replace routes to a B tappable pick."""
        import re
        buf = self._wa12_buf_migrate(buf)
        lines = buf["lines"]
        norm = " ".join((raw or "").strip().lower().split())

        def reshow():
            sess._set_buffer(buf)
            if batch:
                return "applied"
            return self._wa6_reply(raw_from, from_e164,
                                   self._wa12_items_confirm_text(buf))

        def find_by_number(tok):
            """(line, err). A 'lid#<L>' sentinel (from the D two-pass) resolves
            by stable lid; a bare int by 1-based display position."""
            tok = str(tok).strip()
            if tok.startswith("lid#") and tok[4:].isdigit():
                ln = self._wa12_line_by_lid(buf, int(tok[4:]))
                if ln is None:
                    return None, self._wa6_reply(raw_from, from_e164, _(
                        "That line is gone — check the list and try again."))
                return ln, None
            if not tok.isdigit():
                return None, None
            ln = self._wa12_line_by_number(buf, int(tok))
            if ln is None:
                return None, self._wa6_reply(raw_from, from_e164, _(
                    "There's no line %s — you have %d.")
                    % (tok, len(lines)))
            return ln, None

        def find_one(tok):
            """A bare int / lid# -> by number; else a contains-match on a
            MATCHED product name (>1 -> refuse; 0 -> refuse)."""
            t = (tok or "").strip()
            if t.isdigit() or t.startswith("lid#"):
                ln, err = find_by_number(t)
                if ln is not None or err is not None:
                    return ln, err
            tl = t.lower()
            hits = [ln for ln in lines if ln.get("kind") == "matched"
                    and tl in (ln.get("product_name") or "").lower()]
            if not hits:
                return None, self._wa6_reply(raw_from, from_e164, _(
                    "No line matches \"%s\".") % t)
            if len(hits) > 1:
                return None, self._wa6_reply(raw_from, from_e164, _(
                    "Several items match \"%s\" — say the line number: %s")
                    % (t, " / ".join("%d) %s" % (lines.index(h) + 1,
                                                 h["product_name"])
                                     for h in hits)))
            return hits[0], None

        def apply_replace(target_ln, new_txt):
            new_hit = self._wa6_match_one(new_txt)
            if (new_hit.get("status") == "matched"
                    and new_hit.get("confidence") in ("exact", "strong")):
                target_ln.clear()
                target_ln.update({
                    "lid": target_ln_lid, "kind": "matched",
                    "product_id": new_hit["product_id"],
                    "product_name": new_hit["product_name"],
                    "qty": new_qty, "rep_price": None, "stated_price": None})
                self._wa12_clear_pending_for(buf, target_ln_lid)
                return reshow()
            # non-confident -> a B tappable pick (never a "did you mean" text).
            self._wa12_clear_pending_for(buf, target_ln_lid)
            if batch:
                # in a batch we can't send a pick per item; flag the line
                # unmatched + let the post-batch reshow offer the first pick.
                target_ln.clear()
                fam = new_hit.get("family") or self._wa6_family_code(new_txt) or ""
                is_v = bool(fam and self._wa12_is_family_term(new_txt))
                cids = (self._wa12_family_candidate_ids(fam) if is_v
                        else self._wa12_suggestion_ids(new_hit.get("suggestions")
                                                       or []))
                target_ln.update({
                    "lid": target_ln_lid, "kind": "unmatched", "raw": new_txt,
                    "qty": new_qty, "suggestions": new_hit.get("suggestions")
                    or [], "family": fam, "_variant": is_v, "_cand_ids": cids})
                return "applied"
            return self._wa12_offer_pick_for_replace(
                sess, buf, target_ln, new_txt, new_hit, from_e164, raw_from)

        # client <name>
        m = re.match(r"client\s+(.+)$", raw, re.I)
        if m:
            name = m.group(1).strip()
            partner, _cand = self._wa12_client_candidates(name)
            buf["client_txt"] = partner.name if partner else name
            buf["partner_id"] = partner.id if partner else False
            return reshow()

        # C: `<n> = <new>` / `<n> -> <new>` -- replace BY NUMBER. ':' is NOT a
        # separator (avoids time/ratio collision). A non-numeric LHS falls to
        # the `replace` form below; a non-existent index falls through (None).
        m = re.match(r"^\s*((?:lid#)?\d+)\s*(?:=|->)\s*(.+)$", raw, re.I)
        if m:
            ln, err = find_by_number(m.group(1))
            if err:
                return err
            if ln is not None:
                target_ln, target_ln_lid = ln, ln["lid"]
                new_qty = ln.get("qty") or 1
                return apply_replace(ln, m.group(2).strip())
            # not a valid index -> fall through (so "2x100 molefay" re-types).

        # name-led replace -- `replace <old> = <new>` (also `<old> -> <new>`).
        m = re.match(r"replace\s+(.+?)\s*(?:=|->)\s*(.+)$", raw, re.I)
        if m:
            it, err = find_one(m.group(1).strip())
            if err:
                return err
            target_ln, target_ln_lid = it, it["lid"]
            new_qty = it.get("qty") or 1
            return apply_replace(it, m.group(2).strip())

        # remove -- a bare int / lid# removes EXACTLY that line; a token removes
        # by contains-match (announcing a multi-remove, never silent).
        m = re.match(r"remove\s+(.+)$", raw, re.I)
        if m:
            tok = m.group(1).strip()
            if tok.isdigit() or tok.startswith("lid#"):
                ln, err = find_by_number(tok)
                if err:
                    return err
                self._wa12_clear_pending_for(buf, ln["lid"])
                lines.remove(ln)
                return reshow()
            tl = tok.lower()
            keep = [ln for ln in lines
                    if tl not in (ln.get("product_name")
                                  or ln.get("raw") or "").lower()]
            n_removed = len(lines) - len(keep)
            if not n_removed:
                return self._wa6_reply(raw_from, from_e164, _(
                    "No line matches \"%s\".") % tok)
            for ln in lines:
                if ln not in keep:
                    self._wa12_clear_pending_for(buf, ln["lid"])
            buf["lines"] = keep
            note = (_("Removed %d lines matching \"%s\".\n\n")
                    % (n_removed, tok)) if n_removed > 1 else ""
            sess._set_buffer(buf)
            if batch:
                return "applied"
            return self._wa6_reply(raw_from, from_e164,
                                   note + self._wa12_items_confirm_text(buf))

        # qty -- `qty <tok> <m>` / `qty <tok> to <m>`. tok may be a number.
        m = re.match(r"qty\s+(.+?)\s+(?:to\s+)?(\d+)\s*$", raw, re.I)
        if m:
            it, err = find_one(m.group(1).strip())
            if err:
                return err
            it["qty"] = max(1, int(m.group(2)))
            return reshow()

        # price -- `price <tok> <amt>`, ONLY where no catalogue rate exists.
        m = re.match(r"price\s+(.+?)\s+([0-9]+(?:\.[0-9]+)?)\s*$", raw, re.I)
        if m:
            it, err = find_one(m.group(1).strip())
            if err:
                return err
            if it.get("kind") != "matched":
                return self._wa6_reply(raw_from, from_e164, _(
                    "That line isn't matched yet — pick the product first."))
            prod = self.env["product.template"].sudo().browse(it["product_id"])
            rate, cur = self._wa12_price_lookup(prod)
            if rate is not None and rate > _WA12_PLACEHOLDER_RATE:
                return self._wa6_reply(raw_from, from_e164, _(
                    "%s has a catalogue rate (%s %.2f/day) — that's what "
                    "drafts. You can apply a discount after drafting.")
                    % (it["product_name"], cur, rate))
            amt = float(m.group(2))
            if amt <= _WA12_PLACEHOLDER_RATE:
                return self._wa6_reply(raw_from, from_e164, _(
                    "That rate is too low — give the real day rate."))
            it["rep_price"] = amt
            return reshow()

        ev_date, ph = self._wa12_resolve_date(raw)
        if not ph:
            buf["date_txt"] = ev_date.isoformat()
            return reshow()

        # re-typed item(s): only CONFIDENT matches add here. A purely-weak/
        # no-match input returns None so the caller can try the LLM translate;
        # genuinely-weak re-types are surfaced by the caller's fallback. qty
        # carried; a re-type reconciles a matching unmatched line.
        adds, _weak = self._wa12_match_text_items(raw)
        if adds:
            known = {ln["product_id"] for ln in lines
                     if ln.get("kind") == "matched"}
            added_names = set()
            for a in adds:
                if a["product_id"] not in known:
                    self._wa12_add_line(
                        buf, kind="matched", product_id=a["product_id"],
                        product_name=a["product_name"], qty=a.get("qty") or 1,
                        rep_price=a.get("rep_price"),
                        stated_price=a.get("stated_price"))
                    known.add(a["product_id"])
                added_names.add(a["product_name"])
            # drop any unmatched line whose suggestions the add resolved.
            buf["lines"] = [ln for ln in buf["lines"]
                            if not (ln.get("kind") == "unmatched"
                                    and (added_names
                                         & set(ln.get("suggestions") or [])))]
            return reshow()
        return None

    def _wa12_apply_multi(self, quote, body, from_e164, raw_from):
        """F4: extract a multi-item message at q_confirm and ADD the confident
        matches to the live draft (engine-priced / rep-priced per F8); report
        weak/unmatched lines. None when extraction yields nothing (the caller
        falls through to the translate-edit hook)."""
        data = self._wa12_llm_extract_quote(body)
        items = [it for it in ((data or {}).get("items") or [])
                 if it.get("name")]
        if not items:
            return None
        matched, unmatched = self._wa12_match_slot_items(items)
        # F8 enrichment on the adds: stated price -> rep price ONLY where no
        # catalogue rate resolves.
        for it in matched:
            prod = self.env["product.template"].sudo().browse(it["product_id"])
            rate, _cur = self._wa12_price_lookup(prod)
            sp = it.get("stated_price")
            if ((rate is None or rate <= _WA12_PLACEHOLDER_RATE)
                    and sp and float(sp) > _WA12_PLACEHOLDER_RATE):
                it["rep_price"] = float(sp)
        days = max(quote.line_ids.mapped("duration_days") or [1])
        existing = set(quote.line_ids.mapped("product_template_id").ids)
        adds = [it for it in matched if it["product_id"] not in existing]
        dupes = [it for it in matched if it["product_id"] in existing]
        if adds:
            self._wa12_build_lines(quote, adds, int(days))
        # MATCH-3/FSM-6: the note reports from `adds` ONLY (never claim an item
        # was "Added" when it was deduped); a duplicate is reported honestly +
        # its qty change routed through the guarded qty-edit (build_lines only
        # creates, so the requested qty would otherwise be silently dropped).
        note_bits = []
        if adds:
            note_bits.append(_("Added %s") % ", ".join(
                it["product_name"] for it in adds))
        for it in dupes:
            ql = quote.line_ids.filtered(
                lambda l: l.product_template_id.id == it["product_id"])[:1]
            want = int(it.get("qty") or 1)
            if ql and want > 1 and ql.quantity != want:
                ql.with_user(quote.salesperson_id.id or self.env.uid).sudo(
                    ).write({"quantity": want})
                note_bits.append(_("%s already on the quote → qty %d")
                                 % (it["product_name"], want))
            else:
                note_bits.append(_("%s already on the quote")
                                 % it["product_name"])
        for um in unmatched:
            sugg = um.get("suggestions") or []
            note_bits.append(_("⚠️ \"%s\" — not sure%s") % (
                um.get("name"),
                (_(" (did you mean: %s?)") % " / ".join(sugg[:3]))
                if sugg else ""))
        return self._wa12_after_edit(
            quote, from_e164, raw_from, "\n".join(note_bits) or _("No change"))

    _WA12_BATCH_MAX = 6

    def _wa12_llm_translate_items(self, text, buf):
        """D: translate a natural q_items message into a LIST of deterministic
        commands (one per change), each re-run through _wa12_q_items_try (which
        re-enforces every guard). Returns [cmd, ...] (deduped, capped), or None
        on unclear / degraded. The current lines are shown WITH NUMBERS so the
        model can address a line by position (`N = <item>`)."""
        buf = self._wa12_buf_migrate(buf)
        numbered = "\n".join(
            "%d. %s" % (i, ln.get("product_name") or ("⚠️ " + (ln.get("raw")
                        or "")))
            for i, ln in enumerate(buf.get("lines") or [], 1)) or "(none)"
        sys = (
            "You map a sales rep's WhatsApp message to a LIST of correction "
            "commands for an UNCONFIRMED quote item list. Output ONE command "
            "per line, one per change, plain text, no quotes, no prose. Allowed "
            "forms: 'N = <new item>' (replace line number N), '<oldname> = "
            "<new item>', 'remove N', 'remove <name>', 'qty N <n>', 'price N "
            "<amount>', 'client <name>', a date (YYYY-MM-DD), 'yes', or "
            "'cancel'. Prefer addressing a line by its NUMBER. Current lines:\n"
            + numbered + "\nIf the message is a complaint with no specific "
            "change, output exactly REPAIR. If nothing maps, output exactly "
            "UNKNOWN.")
        raw = self._wa12_llm_chat([{"role": "system", "content": sys},
                                   {"role": "user", "content": text or ""}])
        if not raw:
            return None
        out, seen = [], set()
        for line in raw.strip().splitlines():
            cmd = line.strip().strip('"`').strip()
            if not cmd or cmd.upper() == "UNKNOWN":
                continue
            key = " ".join(cmd.lower().split())
            if key in seen:
                continue
            seen.add(key)
            out.append(cmd)
        if not out:
            return None
        if len(out) > self._WA12_BATCH_MAX:
            # too many at once -> safer to ask for them one at a time than to
            # apply a long, possibly-misread batch.
            return ["REPAIR_TOO_MANY"]
        return out

    def _wa12_batch_resolve_lids(self, buf, cmds):
        """D two-pass: rewrite each NUMBER-addressed command's leading index to a
        stable 'lid#<L>' token against the PRE-batch line order, so a `remove`
        early in the batch can't shift the number a later command was generated
        against. Non-number commands pass through unchanged."""
        import re
        buf = self._wa12_buf_migrate(buf)
        lines = buf.get("lines") or []
        out = []
        for cmd in cmds:
            c = cmd
            m = re.match(r"^\s*(\d+)\s*(=|->)\s*(.+)$", cmd)
            if m and 1 <= int(m.group(1)) <= len(lines):
                lid = lines[int(m.group(1)) - 1]["lid"]
                c = "lid#%d %s %s" % (lid, m.group(2), m.group(3).strip())
            else:
                m = re.match(r"^\s*(remove|qty|price)\s+(\d+)\b(.*)$", cmd, re.I)
                if m and 1 <= int(m.group(2)) <= len(lines):
                    lid = lines[int(m.group(2)) - 1]["lid"]
                    c = "%s lid#%d%s" % (m.group(1).lower(), lid, m.group(3))
            out.append(c)
        return out

    def _wa12_try_narrow(self, sess, buf, raw, from_e164, raw_from):
        """A >10-overflow narrow follow-up: re-run the matcher on the typed
        phrase scoped to the remembered line's family, then offer the (smaller)
        candidate set as a pick. Returns the send, or None if the phrase looks
        like a command/yes/cancel (let the normal parser handle it) or yields
        nothing. Clears narrow_target on use."""
        buf = self._wa12_buf_migrate(buf)
        nt = buf.get("narrow_target") or {}
        lid = nt.get("lid")
        ln = self._wa12_line_by_lid(buf, lid) if lid else None
        if not ln:
            buf.pop("narrow_target", None)
            sess._set_buffer(buf)
            return None
        norm = " ".join((raw or "").strip().lower().split())
        # don't hijack an explicit command / yes / cancel / number-edit.
        import re
        if (norm in _WA12_SUBMIT_WORDS or self._wa12_is_cancel(norm)
                or re.match(r"^(remove|qty|price|client|replace)\b", norm)
                or re.match(r"^\s*\d+\s*(=|->)", norm)):
            return None
        hit = self._wa6_match_one(raw)
        if hit.get("status") == "matched" and hit.get("confidence") in (
                "exact", "strong"):
            ln.clear()
            ln.update({"lid": lid, "kind": "matched",
                       "product_id": hit["product_id"],
                       "product_name": hit["product_name"],
                       "qty": nt.get("qty") or ln.get("qty") or 1,
                       "rep_price": None, "stated_price": None})
            buf.pop("narrow_target", None)
            self._wa12_clear_pending_for(buf, lid)
            sess._set_buffer(buf)
            return self._wa6_reply(raw_from, from_e164,
                                   self._wa12_items_confirm_text(buf))
        fam = nt.get("family") or hit.get("family") or ""
        cids = self._wa12_family_candidate_ids(fam) if fam else \
            self._wa12_suggestion_ids(hit.get("suggestions") or [])
        # scope to those whose name contains a typed token (the narrow).
        PT = self.env["product.template"].sudo()
        toks = [t for t in re.findall(r"[a-z0-9.]+", norm)
                if t not in _WA6_STOP]
        scoped = [p for p in cids
                  if any(t in (PT.browse(p).name or "").lower() for t in toks)]
        cids = scoped or cids
        if not cids:
            return None
        buf.pop("narrow_target", None)
        ln["raw"] = raw
        ln["family"] = fam
        ln["_cand_ids"] = cids
        ln["_variant"] = bool(fam and self._wa12_is_family_term(raw))
        return self._wa12_offer_pick_for_buffer(sess, buf, ln, from_e164,
                                                raw_from)

    # ================================================================
    # WA-12.2 conversational lane — the LLM is a TRANSLATOR at the door:
    # extraction only, never prices / approves / bypasses a guard. Every
    # failure degrades to the deterministic forms (quoting is never blocked
    # by an LLM outage).
    # ================================================================
    def _wa12_llm_chat(self, messages):
        """One-shot LLM completion for EXTRACTION ONLY, temperature 0 (a
        translator must be deterministic -- bake-off ruling, 12 Jun). Fallback
        chain RE-ORDERED by the bake-off evidence: groq/llama (primary, 9/9)
        -> groq/openai/gpt-oss-120b (same key, 9/9) -> gemini (parse-fail +
        3x latency, demoted last). Returns the assistant text, or None on ANY
        failure/timeout/absence (graceful degradation -- quoting is never
        blocked by an LLM outage)."""
        try:
            from odoo.addons.neon_ai_core.models.ai.chat_adapter_factory \
                import get_chat_adapter
        except Exception:  # noqa: BLE001 -- ai_core absent -> degrade
            return None
        Prov = self.env["neon.dashboard.ai.provider"].sudo()
        # Default ALIGNED to "google" (Gemini) to match _wa_provider() /
        # handle_inbound / the wa_config_params seed -- so a DELETED param no
        # longer splits the WA-12 extraction lane back to Groq while the Copilot
        # uses Gemini. The live primary is whatever the param holds; this default
        # only fires if the param is absent. (The bake-off note below describes
        # the groq-primary ORDERING; it stays correct for the param=="groq" case.)
        primary = self.env["ir.config_parameter"].sudo().get_param(
            "neon_channels.whatsapp_provider_key", "google")
        # (provider_key, per-call model override) in evidence order; the
        # configured primary leads, then the same-key Groq backup model,
        # then the demoted Gemini lane.
        attempts = [(primary, None)]
        if primary == "groq":
            attempts += [("groq", "openai/gpt-oss-120b"), ("google", None)]
        else:
            attempts += [("groq", None), ("groq", "openai/gpt-oss-120b")]
        for k, model in attempts:
            prov = Prov.search([("provider_key", "=", k),
                                ("is_enabled", "=", True)], limit=1)
            adapter = get_chat_adapter(prov) if prov else None
            if not adapter:
                continue
            try:
                res = adapter.chat(messages, temperature=0.0, model=model)
            except Exception as e:  # noqa: BLE001 -- never crash a turn
                _logger.warning("WA-12.2 LLM chat failed (%s/%s): %s",
                                k, model or "default", e)
                continue
            if res is not None and getattr(res, "success", False) \
                    and res.assistant_message:
                return res.assistant_message
        return None

    @api.model
    def _wa12_llm_json(self, raw):
        """Parse an LLM reply into a dict, tolerating ```json fences / prose
        around the object. None on any failure."""
        import json
        import re
        if not raw:
            return None
        s = raw.strip()
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            s = m.group(0)
        try:
            data = json.loads(s)
            return data if isinstance(data, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def _wa12_llm_extract_quote(self, text):
        """Translate a free-text quote request into slots. Returns
        {client, items:[{name,qty,stated_price}], date, phone, email,
        contact_person} when intent=quote (client/items may be empty for a
        BARE intent -- M5), else None (not a quote / degraded). Multi-item
        briefs (client + phone + several equipment lines) are the NORMAL rep
        format -- every item must come back in the list (M1)."""
        today = fields.Date.context_today(self).isoformat()
        sys = (
            "You convert a sales rep's WhatsApp message into a QUOTE request "
            "for an events-hire company. Respond with ONLY a JSON object, no "
            "prose. Schema: {\"intent\": \"quote\"|\"other\", \"client\": "
            "string|null, \"items\": [{\"name\": string, \"qty\": integer, "
            "\"stated_price\": number|null, \"category\": "
            "\"visual\"|\"lighting\"|\"staging\"|\"sound\"|\"effects\"|"
            "\"trussing\"|\"cabling\"|null}], \"date\": string|null, "
            "\"phone\": string|null, \"email\": string|null, "
            "\"contact_person\": string|null, \"address\": string|null, "
            "\"event_name\": string|null}. Set intent='quote' if the "
            "message asks to price/quote/hire equipment OR expresses the wish "
            "to make a quote (then client/items may be empty -- do NOT invent "
            "them). Extract EVERY equipment line in a multi-line brief as its "
            "own item (briefs list client details then several items). A price "
            "the rep states for an item goes in stated_price (it is a hint, "
            "not the rate). phone/email/contact_person: only if present in the "
            "message. address = the client's street/physical address if "
            "given; event_name = the event's subject/name (e.g. 'Redan "
            "Launch') if given. Resolve relative dates (e.g. 'next Friday', "
            "'month end') "
            "to an absolute YYYY-MM-DD in Africa/Harare given today is " + today
            + "; if no date or you are unsure, set date null. NEVER invent a "
            "client, items, phone, email or address not in the message. "
            "JSON only.")
        # few-shot pairs drawn from REAL rep briefs (proof corpus, 12 Jun):
        # multi-line brief w/ phone + a system-price hint + a priced ad-hoc
        # line; and a located-at/Subject brief with X2 qty notation.
        fs_u1 = ("Name of client: Ellen Prestige \nPhone: +263773863012\n\n"
                 "They have a wedding so they want to hire \n\nAudio "
                 "equipment - pa system (the one for 250) \nLighting "
                 "Equipment - RGB LED CAN quantity 5 they cost 10 each in "
                 "the system \nLogistics is 150 \n\nDraft")
        fs_a1 = ('{"intent": "quote", "client": "Ellen Prestige", "items": '
                 '[{"name": "pa system 250", "qty": 1, "stated_price": null}, '
                 '{"name": "RGB LED CAN", "qty": 5, "stated_price": 10}, '
                 '{"name": "Logistics", "qty": 1, "stated_price": 150}], '
                 '"date": null, "phone": "+263773863012", "email": null, '
                 '"contact_person": null, "address": null, '
                 '"event_name": "wedding"}')
        fs_u2 = ("I want a quotation for EC Rentals located at 10 Hugh "
                 "Fraser Road, Highlands, Harare Subject : EC Rentals, Redan "
                 "Launch \nItems: 5m x 3m LED screen , 1m x 3m DIGITAL "
                 "BANNERS X2, KOMMANDER MEDIA SERVER , STAGGING AND FLOORING "
                 "EQUIPMENT - 5M X 5M OUTDOOR INFINITY DANCEFLOOR,\nAUDIO "
                 "EQUIPMENT - PA SYSTEM 500 PAX.")
        fs_a2 = ('{"intent": "quote", "client": "EC Rentals", "items": '
                 '[{"name": "5M X 3M LED SCREEN", "qty": 1, "stated_price": '
                 'null}, {"name": "1M X 3M DIGITAL BANNERS", "qty": 2, '
                 '"stated_price": null}, {"name": "KOMMANDER MEDIA SERVER", '
                 '"qty": 1, "stated_price": null}, {"name": "5M X 5M OUTDOOR '
                 'INFINITY DANCEFLOOR", "qty": 1, "stated_price": null}, '
                 '{"name": "PA SYSTEM 500 PAX", "qty": 1, "stated_price": '
                 'null}], "date": null, "phone": null, "email": null, '
                 '"contact_person": null, "address": "10 Hugh Fraser Road, '
                 'Highlands, Harare", "event_name": "Redan Launch"}')
        raw = self._wa12_llm_chat([
            {"role": "system", "content": sys},
            {"role": "user", "content": fs_u1},
            {"role": "assistant", "content": fs_a1},
            {"role": "user", "content": fs_u2},
            {"role": "assistant", "content": fs_a2},
            {"role": "user", "content": text or ""}])
        data = self._wa12_llm_json(raw)
        if not data or (data.get("intent") or "").lower() != "quote":
            return None
        return data

    def _wa12_llm_translate_edit(self, text, quote):
        """Translate a free-text in-session message into ONE deterministic edit
        command the q_confirm loop understands, or None (unclear / degraded).
        Extraction only -- the returned command is re-run through the SAME
        deterministic _wa12_try_edit (which re-enforces every guard)."""
        lines = " · ".join("%s" % l.name for l in quote.line_ids) or "(none)"
        sys = (
            "You map a sales rep's WhatsApp message to EXACTLY ONE quote-edit "
            "command, output as plain text on one line, no quotes, no prose. "
            "Allowed commands: 'price <item> <amount>', 'discount <item> "
            "<n>%', 'qty <item> <n>', 'days <n>', 'add <item> x<n>', 'add "
            "custom <description> at <amount>', 'remove <item>', 'no tax', "
            "'with tax', 'client <name>', 'terms <text>', a date "
            "(YYYY-MM-DD), 'yes' (submit), or 'cancel'. Current line items: "
            + lines + ". If the message is a COMPLAINT or says something is "
            "wrong without naming one specific change, output exactly REPAIR. "
            "If the message doesn't clearly map to one command, "
            "output exactly UNKNOWN.")
        raw = self._wa12_llm_chat([{"role": "system", "content": sys},
                                   {"role": "user", "content": text or ""}])
        if not raw:
            return None
        cmd = raw.strip().strip('"`').splitlines()[0].strip()
        if not cmd or cmd.upper() == "UNKNOWN":
            return None
        return cmd

    @api.model
    def _wa12_llm_intake_maybe(self, message):
        """WA-12.2 conversational quote-INITIATION fallback. Called from
        handle_inbound AFTER every deterministic interceptor misses + BEFORE the
        Copilot. Sales-capable sender + multi-word free TEXT -> LLM translate to
        a quote (extraction only). Not a quote / LLM down / live session ->
        None, so the Copilot runs unchanged."""
        if message.get("type") != "text":
            return None
        raw_from = message.get("from")
        from_e164 = to_e164(raw_from)
        if not from_e164:
            return None
        body = self._extract_body(message, "text")
        if len((body or "").split()) < _WA12_LLM_MIN_WORDS:
            return None
        sender = self._wa6_resolve_user(from_e164)
        if not (sender and self._wa12_can_quote(sender)):
            return None
        # a live session means an earlier interceptor owns this phone -- defensive
        # (it would have claimed the turn already); never start a parallel quote.
        if self.env["neon.wa.equip.session"]._active_for_phone(from_e164):
            return None
        return self._wa12_llm_quote_fallback(
            sender, body, from_e164, raw_from, message)

    def _wa12_llm_quote_fallback(self, sender, body, from_e164, raw_from,
                                 message):
        """WA-12.6: a conversational quote intent RESETS to the structured one-
        at-a-time collection -- the brief is NOT bulk-extracted (the proven
        item-drop/wrong-client failure). The LLM read (inside begin_structured)
        only PRE-FILLS the client/date prompts as confirmable suggestions; items
        are always collected one-by-one fresh. Returns a reply, or None to fall
        through only if this isn't a quote at all."""
        # cheap gate: only claim if the LLM reads it as a quote intent (so a
        # random chat still falls to the Copilot). Pre-fill happens in
        # begin_structured; here we just confirm intent.
        data = self._wa12_llm_extract_quote(body)
        if not data or (data.get("intent") or "") != "quote":
            return None
        return self._wa12_begin_structured(
            sender, body, from_e164, raw_from, message=message)

    @api.model
    def _wa12_match_slot_items(self, items):
        """Resolve LLM-extracted items through the EXISTING catalogue matcher,
        one by one (qty from the slot, not re-parsed). Returns (matched,
        unmatched) where matched = [{product_id, product_name, qty,
        stated_price}] and unmatched = [{name, suggestions}].

        F2: only an 'exact'/'strong'-confidence hit is auto-accepted; a WEAK
        hit goes to the unmatched bucket WITH its alternatives, so the rep
        picks per item in the confirm echo instead of a token-overlap guess
        landing in the draft."""
        matched, unmatched = [], []
        for it in items:
            name = it.get("name") or ""
            # DEFECT-1 safety net: an LLM item name may itself contain MULTIPLE
            # items the model failed to separate ("4 blinders on totems",
            # "screen and a stage"). Re-split each name deterministically
            # (_wa6_match_items splits on , / newline / ' and ') so EVERY item
            # reaches the stepper -- the LLM is never the sole splitter.
            sub = self._wa6_match_items(name)
            multi = len(sub) > 1
            for hit in sub:
                # qty: a re-split sub-item keeps its OWN parsed qty; a single
                # item takes the LLM slot qty (the rep's stated count).
                qty = (int(hit.get("qty") or 1) if multi
                       else int(it.get("qty") or hit.get("qty") or 1))
                sp = it.get("stated_price") if not multi else None
                if (hit.get("status") == "matched"
                        and hit.get("confidence") in ("exact", "strong")):
                    matched.append({
                        "product_id": hit["product_id"],
                        "product_name": hit["product_name"],
                        "qty": max(1, qty), "stated_price": sp})
                else:
                    sugg = hit.get("suggestions") or []
                    if hit.get("status") == "matched" \
                            and hit.get("product_name") \
                            and hit["product_name"] not in sugg:
                        sugg = [hit["product_name"]] + sugg
                    unmatched.append({"name": hit.get("raw") or name,
                                      "qty": max(1, qty), "stated_price": sp,
                                      "suggestions": sugg[:3],
                                      "family": hit.get("family") or ""})
        return matched, unmatched

    @api.model
    def _wa12_discovery_family(self, text):
        """M-B: catalogue-discovery intent ('list LED screens' / 'what screens
        do you have' / 'show me the lighting') -> the family code, else None."""
        import re
        low = " ".join((text or "").lower().split())
        if not re.match(
                r"^(list|show( me)?|what|which|do you have|got any|any)\b", low):
            return None
        return self._wa6_family_code(low)

    @api.model
    def _wa12_family_names(self, fam):
        """The EXACT catalogue names in a family (M-B pick-list = the names the
        team knows; the rep replies with one). EXCLUDES the Packages family +
        test residue so a single-item discovery never lists a bundle (wire
        675-707)."""
        P = self.env["product.template"].sudo()
        pkg = self.env["neon.equipment.category"].sudo().search(
            [("code", "=", "packages")], limit=1)
        dom = [("is_workshop_item", "=", True), ("name", "not ilike", "[TEST")]
        if pkg:
            dom.append(("equipment_category_id", "!=", pkg.id))
        return P.search(dom).filtered(
            lambda p: self._wa6_in_family(p, fam)).mapped("name")

    @api.model
    def _wa12_strip_correction(self, text):
        """M-C: strip a correction lead-in ('no it's a', 'i mean', 'actually',
        'make it', 'should be') so the remainder RE-SEARCHES as the intended
        item -- never extracts to 'none'. Returns the stripped term."""
        import re
        return re.sub(
            r"^(no[,\s]+|i mean[,\s]+|actually[,\s]+|it'?s\s+(a |an )?|"
            r"make it\s+(a |an )?|should be\s+(a |an )?)+", "",
            (text or "").strip(), flags=re.I).strip()

    @api.model
    def _wa12_match_text_items(self, text):
        """Match a free-text item list with the F2 confidence gate (review
        MATCH-1/FSM-3): only exact/strong hits are auto-accepted; weak /
        not_found go to the unmatched bucket WITH the guess prepended to the
        suggestions, so a thin token-overlap never lands as a confident line.
        Same (matched, unmatched) contract as _wa12_match_slot_items, for
        rep-TYPED text (q_itemreq / direct Quote: / q_confirm `add`)."""
        matched, unmatched = [], []
        for h in self._wa6_match_items(text):
            qty = max(1, int(h.get("qty") or 1))
            if (h.get("status") == "matched"
                    and h.get("confidence") in ("exact", "strong")):
                matched.append({"product_id": h["product_id"],
                                "product_name": h["product_name"], "qty": qty,
                                "stated_price": None})
            else:
                sugg = h.get("suggestions") or []
                if h.get("status") == "matched" and h.get("product_name") \
                        and h["product_name"] not in sugg:
                    sugg = [h["product_name"]] + sugg
                # WA-12.3: carry the matcher's family (it scoped one even on a
                # weak hit) so the builder can offer the in-family variant set.
                unmatched.append({"name": h.get("raw") or "", "qty": qty,
                                  "stated_price": None,
                                  "suggestions": sugg[:3],
                                  "family": h.get("family") or ""})
        return matched, unmatched

    def _wa12_open_items_confirm(self, sender, client_txt, matched, unmatched,
                                 date_txt, prefills, from_e164, raw_from,
                                 partner_id=False):
        """Open the q_items session + send the ONE confirmation message (M1).
        NO quote exists yet -- provision happens only on the rep's yes.

        F8 enrichment: a rep-STATED price on an item with NO catalogue rate
        becomes the rep price (line will draft 'manual', loudly flagged); on a
        PRICED item it stays a disambiguation hint (the engine rate drafts)."""
        for it in (matched or []):
            prod = self.env["product.template"].sudo().browse(it["product_id"])
            rate, _cur = self._wa12_price_lookup(prod)
            sp = it.get("stated_price")
            if ((rate is None or rate <= _WA12_PLACEHOLDER_RATE)
                    and sp and float(sp) > _WA12_PLACEHOLDER_RATE):
                it["rep_price"] = float(sp)
        if not matched and not unmatched:
            return self._wa6_reply(raw_from, from_e164, _(
                "I couldn't read any items from that — what items should I "
                "quote?"))
        # WA-12.4 STEPPER: build the v4 ordered `lines` buffer, then resolve ONE
        # item at a time (each its own message + counter). No combined block.
        buf = {"v": 4, "next_lid": 1, "lines": [], "pending": None,
               "cur": None, "focus": False, "seq": 0,
               "client_txt": client_txt, "partner_id": partner_id,
               "date_txt": date_txt or "", "days": 1,
               "prefills": prefills or {}}
        buf = self._wa12_build_buf_lines(buf, matched, unmatched)
        for ln in buf["lines"]:
            ln.setdefault("state", "pending")
        sess = self.env["neon.wa.equip.session"]._start_quote(
            from_e164, sender, "q_items", buf)
        if not buf["lines"]:
            sess.sudo().write({"step": "done", "active": False})
            return self._wa6_reply(raw_from, from_e164, _(
                "I couldn't read any items — what should I quote?"))
        self._wa6_reply(raw_from, from_e164, _(
            "Let's confirm %d item(s) for *%s*, one at a time. 👇")
            % (len(buf["lines"]), client_txt or _("the client")))
        return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)

    def _wa12_items_confirm_text(self, buf):
        """The M1 confirmation message: every matched line with the ENGINE
        rate + qty; weak/unmatched lines listed per-item with alternatives
        (F2). Rates here are EXACTLY what the draft will carry (the F1
        echo-equals-draft binding): engine rate, or the rep price flagged
        '(rep-priced — no catalogue rate)' (F8), or 'no rate set — what
        should it be?' (which blocks until priced)."""
        # WA-12.3: render the single numbered v3 `lines` list (matched +
        # unmatched in one numbering space, so a number addresses ANY line).
        buf = self._wa12_buf_migrate(buf)
        PT = self.env["product.template"].sudo()
        pend = buf.get("pending") or {}
        rows = []
        for i, ln in enumerate(buf.get("lines") or [], 1):
            if ln.get("kind") == "matched":
                prod = PT.browse(ln["product_id"])
                rate, cur = self._wa12_price_lookup(prod)
                note = ""
                if rate is not None and rate > _WA12_PLACEHOLDER_RATE:
                    rate_txt = "%s %.2f/day" % (cur, rate)
                    sp = ln.get("stated_price")
                    if sp and abs(float(sp) - rate) > 0.005:
                        note = _(" (you said %.2f — the catalogue rate applies)"
                                 ) % sp
                elif ln.get("rep_price"):
                    rate_txt = "%s %.2f/day" % (cur, ln["rep_price"])
                    note = _(" (rep-priced — no catalogue rate)")
                else:
                    rate_txt = _("no rate set — what should it be? "
                                 "(`price %d <amt>`)") % i
                rows.append("%d. %s ×%d @ %s%s" % (
                    i, ln["product_name"], ln.get("qty") or 1, rate_txt, note))
            else:
                # unmatched: a pending line says "tap an option above"; else the
                # variant / did-you-mean hint.
                if pend.get("lid") == ln.get("lid"):
                    tail = _(" — tap an option above")
                elif ln.get("_variant"):
                    tail = _(" — which one? (tap above, or re-type)")
                else:
                    sugg = ln.get("suggestions") or []
                    tail = ((_(" — did you mean: %s? (`%d = <the right one>`)")
                             % (" / ".join(sugg[:3]), i)) if sugg else
                            _(" — no catalogue match (`%d = <item>` or "
                              "`remove %d`)") % (i, i))
                rows.append(_("%d. ⚠️ \"%s\"%s") % (i, ln.get("raw") or "",
                                                    tail))
        head = _("I matched for *%s*%s:") % (
            buf.get("client_txt") or _("(client TBC)"),
            (_(" — %s") % buf["date_txt"]) if buf.get("date_txt") else "")
        return "%s\n%s\n\n%s" % (head, "\n".join(rows), _(
            "Reply *yes* to draft, or correct me by line number — e.g. "
            "`2 = 4x100 molefay` · `remove 3` · `qty 1 to 4` · "
            "`price 2 250` · a date · `client <name>`."))

    def _wa12_handle_session(self, sess, message, from_e164, raw_from):
        """A q_confirm / q_reject turn. Re-checks entitlement every turn, with
        the gate that matches the STEP's actor: q_confirm is the requester
        (creation capability), q_reject is the approver (approver capability).
        Applying the creation gate to a reject turn would lock a pure-finance
        approver out of completing their own rejection."""
        self._wa6_audit_in(from_e164, message, "wa12-sess")
        sess.sudo().write({"last_inbound": fields.Datetime.now()})
        sender = sess.user_id
        ok = (self._wa12_is_approver(sender) if sess.step == "q_reject"
              else self._wa12_can_quote(sender))
        if not (sender and sender.active and ok):
            sess.sudo().write({"active": False})
            return self._wa6_reply(raw_from, from_e164, _(_WA12_REFUSAL))
        # a stray INTERACTIVE tap (e.g. a stale WA-13 button titled 'Cancel')
        # reaching a q_* TEXT session must NOT have its TITLE parsed as a
        # 'cancel'/'yes'/edit command (that would cancel a live quote draft) --
        # claim the turn + re-prompt, never act on it. q_* turns are text-only.
        if message.get("type") == "interactive":
            if sess.step == "q_reject":
                return self._wa6_reply(raw_from, from_e164, _(
                    "Send a one-line reason and I'll relay it to the requester."))
            if sess.step in _WA12_CAPTURE_STEPS:
                return self._wa6_reply(raw_from, from_e164, _(
                    "Please reply with text to continue adding the client."))
            return self._wa6_reply(raw_from, from_e164, _(
                "Reply *yes* to submit, *cancel*, or edit the draft."))
        body = self._extract_body(message, message.get("type"))
        # global cancel works at every collection step.
        if self._wa12_is_cancel(" ".join((body or "").lower().split())) \
                and sess.step in _WA12_STRUCT_STEPS:
            sess.sudo().write({"step": "done", "active": False})
            return self._wa6_reply(raw_from, from_e164, _("Quote cancelled."))
        # new-client intake FSM (qc_*).
        if sess.step in _WA12_CAPTURE_STEPS:
            return self._wa12_handle_capture(sess, body, from_e164, raw_from)
        # WA-12.6 STRUCTURED collection steps (event details / item loop).
        if sess.step in _WA12_STRUCT_STEPS:
            _sbuf = sess._get_buffer()
            _sbuf = _sbuf if isinstance(_sbuf, dict) else {}
            if sess.step == "qs_event":
                return self._wa12_handle_struct_event(
                    sess, _sbuf, body, from_e164, raw_from)
            return self._wa12_handle_struct_item(
                sess, _sbuf, body, from_e164, raw_from)
        # WA-12.2 conversational steps (confirm-before-draft / bare intent).
        if sess.step in _WA12_CONVO_STEPS:
            return self._wa12_handle_convo(sess, body, from_e164, raw_from)
        buf = sess._get_buffer()
        buf = buf if isinstance(buf, dict) else {}
        quote = self.env["neon.finance.quote"].sudo().browse(
            buf.get("quote_id") or 0)
        norm = " ".join((body or "").strip().lower().split())
        if sess.step == "q_confirm":
            if self._wa12_is_cancel(norm):
                sess.sudo().write({"step": "done", "active": False})
                return self._wa6_reply(raw_from, from_e164, _("Quote cancelled."))
            # F6: a greeting mid-draft greets + offers resume/cancel, never
            # the syntax card.
            if norm in _WA12_GREETINGS:
                who = (sender.name or "").split(" ")[0]
                return self._wa6_reply(raw_from, from_e164, _(
                    "Hi %s 👋 — you have an open draft (%s for %s). Reply "
                    "*continue* to see it, *yes* to submit, or *cancel* to "
                    "drop it.") % (
                        who, quote.name if quote.exists() else _("a quote"),
                        quote.partner_id.name if quote.exists() else ""))
            if norm in _WA12_RESUME_WORDS and quote.exists():
                summary = self._wa12_draft_summary(
                    quote, self._wa12_unpriced_lines(quote))
                return self._wa6_reply(raw_from, from_e164, summary + _(
                    "\n\nReply *yes* to submit, *cancel*, *preview*, or keep "
                    "editing."))
            if norm in _WA12_SUBMIT_WORDS:
                if not quote.exists() or quote.state != "draft":
                    sess.sudo().write({"active": False})
                    return self._wa6_reply(raw_from, from_e164, _(
                        "That quote is no longer a draft."))
                if self._wa12_unpriced_lines(quote):
                    return self._wa6_reply(raw_from, from_e164, _(
                        "Still can't submit — some lines have no rate set."))
                return self._wa12_submit(quote, sess, from_e164, raw_from)
            # draft-editing commands (price/discount/qty/days/add/remove/no tax/
            # with tax/client). Each mutates -> recalc -> re-show the summary.
            if quote.exists() and quote.state == "draft":
                edited = self._wa12_try_edit(quote, body, from_e164, raw_from)
                if edited is not None:
                    return edited
                # DEFECT-3: a QUESTION post-draft ("how did you know I want a
                # smoke machine?", "where do I tap?") must get a HELP answer, NOT
                # be translated into an edit command (the LLM read it as `remove
                # smoke` and dropped the line on the wire). Same rule as the
                # stepper's focused sub-state, extended to the draft step:
                # a question NEVER mutates the quote.
                if self._wa12_is_question(body):
                    return self._wa12_draft_help(quote, from_e164, raw_from)
                # M4: complaint/correction language -> the repair prompt,
                # never the syntax menu (deterministic check first -- free).
                if any(t in norm for t in _WA12_COMPLAINT_TOKENS):
                    return self._wa12_repair_prompt(raw_from, from_e164)
                # F4: a MULTI-item message (a pasted brief / price-list) routes
                # through EXTRACTION, never a single-command parse (proof #2
                # msg 594 was read as one `add JVC TV`). Adds confident
                # matches to the draft + reports the rest.
                if (body or "").count("\n") >= 1 or (body or "").count(",") >= 2:
                    multi = self._wa12_apply_multi(
                        quote, body, from_e164, raw_from)
                    if multi is not None:
                        return multi
                # CONVERSATIONAL EDIT FALLBACK (WA-12.2): the deterministic
                # parser missed -> translate the free text into ONE edit command
                # and re-run it through the SAME guarded _wa12_try_edit. The LLM
                # only TRANSLATES; the command it emits is re-validated here.
                # 'REPAIR' = the model judged it a complaint -> repair prompt.
                cmd = self._wa12_llm_translate_edit(body, quote)
                if cmd:
                    if cmd.upper().startswith("REPAIR"):
                        return self._wa12_repair_prompt(raw_from, from_e164)
                    cmd_norm = " ".join(cmd.lower().split())
                    # FSM-7: translated cancel runs; a natural confirm asks for
                    # one explicit 'yes' (the approval-triggering submit stays
                    # an explicit human action, never an LLM interpretation).
                    if self._wa12_is_cancel(cmd_norm):
                        sess.sudo().write({"step": "done", "active": False})
                        return self._wa6_reply(raw_from, from_e164, _(
                            "Quote cancelled."))
                    if cmd_norm in _WA12_SUBMIT_WORDS:
                        return self._wa6_reply(raw_from, from_e164, _(
                            "Reply *yes* to submit %s for approval.")
                            % quote.name)
                    edited = self._wa12_try_edit(
                        quote, cmd, from_e164, raw_from)
                    if edited is not None:
                        return edited
            return self._wa6_reply(raw_from, from_e164, _(
                "Reply *yes* to submit, *preview* to see the draft PDF, or "
                "*cancel* to drop it. To change something, just tell me in "
                "plain words — an item, a quantity, a discount, the date, or "
                "the client — and I'll sort it."))
        if sess.step == "q_reject":
            # the APPROVER typed a rejection comment -> relay to the requester.
            return self._wa12_apply_reject_comment(
                quote, body, sess, from_e164, raw_from)
        return None

    # ================================================================
    # Draft editing (q_confirm, pre-submit) -- WA-12 flexibility.
    # ================================================================
    def _wa12_match_line(self, quote, token):
        """Resolve a typed token to ONE quote.line, by 1-based index, then a
        contains-match on the line name / product name (covers custom lines,
        which carry only a name). (line, error_or_None); >1 -> ambiguous list."""
        token = (token or "").strip()
        lines = quote.line_ids
        if not lines:
            return lines, _("This quote has no lines.")
        if token.isdigit():
            i = int(token)
            if 1 <= i <= len(lines):
                return lines[i - 1], None
        low = token.lower()
        hits = lines.filtered(
            lambda l: low in (l.name or "").lower()
            or low in (l.product_template_id.name or "").lower())
        if len(hits) == 1:
            return hits, None
        if len(hits) > 1:
            menu = " · ".join("%d) %s" % (i + 1, l.name)
                              for i, l in enumerate(lines))
            return lines.browse(), _(
                "Several lines match \"%s\" — say the number: %s") % (token, menu)
        return lines.browse(), _("No line matches \"%s\".") % token

    def _wa12_after_edit(self, quote, from_e164, raw_from, note, keep_note=False):
        """Recalc + re-show the draft summary with the edit note + the prompt.
        ``keep_note`` preserves quote.wa12_discount_note (set ONLY by the whole-
        quote discount path); every OTHER edit clears it so a per-line change
        can never leave a stale whole-quote-discount label on the PDF."""
        actor = quote.salesperson_id.id or self.env.uid
        if not keep_note and quote.wa12_discount_note:
            quote.with_user(actor).sudo().write({"wa12_discount_note": False})
        # ⚠️ DECISION (review WA12-FLEX-2): a `days N` recalc re-prices an
        # engine line through the day-bracket. With binding (b) every per-
        # product rule is FLAT (1..* x1.0) and binding (a) deactivates the
        # category placeholders, so unit_rate does NOT change on a day edit ->
        # a set discount neither drifts nor exceeds the base. The reviewer's
        # 'mark the line manual' fix is rejected: _wa12_unpriced_lines blocks a
        # 'manual' equipment line (anti-fabrication guard), so it would break
        # submit. The residual silent-drift / _check_discount edge is reachable
        # ONLY if a future REAL multi-bracket day-taper CATEGORY rule is added
        # (polish backlog, LOW). Until then we GUARD the recalc: a
        # ValidationError (<: UserError) becomes a clean reply, never a silent
        # half-applied turn or a 500.
        try:
            quote.with_user(actor).sudo().action_recalculate_pricing()
        except (UserError, AccessError) as e:
            return self._wa6_reply(raw_from, from_e164, str(e))
        unpriced = self._wa12_unpriced_lines(quote)
        summary = self._wa12_draft_summary(quote, unpriced)
        tail = (_("\n\n⚠️ Can't submit yet — no rate set: %s.")
                % ", ".join(unpriced)) if unpriced else _(
                "\n\nReply *yes* to submit, *cancel*, or keep editing.")
        return self._wa6_reply(raw_from, from_e164,
                               "%s — done.\n\n%s%s" % (note, summary, tail))

    def _wa12_whole_quote_discount(self, quote, value, ex_vat, is_target,
                                   from_e164, raw_from):
        """Apply a WHOLE-QUOTE discount (review WA12-FLEX). ``value`` is the $
        discount (is_target=False) or the desired total (is_target=True).
        ``ex_vat`` picks the basis: default (False) operates on the VAT-INCLUSIVE
        Total so it lands EXACTLY on target; ex_vat=True operates on the ex-VAT
        goods subtotal (VAT then applies on top). Mechanism: clear existing
        discounts -> recalc to read the true BASE -> set a uniform per-line
        discount_pct = D/base -> recalc. The reduction lands on the chosen base
        exactly (per-line rounding aside). Sets wa12_discount_note for the
        summary/PDF label; the parity gate reads the BASE unit_rate so a discount
        never trips it; confirm-before-draft is intact (the draft is re-shown,
        nothing is submitted)."""
        actor = quote.salesperson_id.id or self.env.uid
        cur = quote.currency_id.name
        lines = quote.line_ids
        if not lines:
            return self._wa6_reply(raw_from, from_e164,
                                   _("This quote has no lines yet."))
        # BASE = undiscounted totals: clear discounts, recalc, read.
        lines.with_user(actor).sudo().write(
            {"discount_pct": 0.0, "discount_amount": 0.0})
        try:
            quote.with_user(actor).sudo().action_recalculate_pricing()
        except (UserError, AccessError) as e:
            return self._wa6_reply(raw_from, from_e164, str(e))
        base = (quote.amount_untaxed or 0.0) if ex_vat else (
            quote.amount_total or 0.0)
        label = _("subtotal") if ex_vat else _("total")
        if base <= _WA12_PLACEHOLDER_RATE:
            return self._wa6_reply(raw_from, from_e164, _(
                "No priced lines to discount yet — set a rate first."))
        if is_target:
            if value <= 0:
                return self._wa6_reply(raw_from, from_e164, _(
                    "The target %s must be a positive amount.") % label)
            if value >= base:
                return self._wa6_reply(raw_from, from_e164, _(
                    "That target (%s %.2f) is at or above the current %s "
                    "(%s %.2f) — that's not a discount.")
                    % (cur, value, label, cur, base))
            disc = base - value
        else:
            disc = value
            if disc >= base:
                return self._wa6_reply(raw_from, from_e164, _(
                    "%s %.2f is the whole %s (%s %.2f) or more — can't discount "
                    "to zero.") % (cur, disc, label, cur, base))
        frac = disc / base
        lines.with_user(actor).sudo().write(
            {"discount_pct": round(frac * 100.0, 6), "discount_amount": 0.0})
        # Label the note with the ACHIEVED drop (read AFTER recalc), not the
        # requested figure: per-line cent rounding means the realized total can
        # differ by a few cents, and the label must TIE OUT with the Subtotal/
        # VAT/Total on the client-facing PDF (review WA12-FLEX, money lens).
        try:
            quote.with_user(actor).sudo().action_recalculate_pricing()
        except (UserError, AccessError) as e:
            return self._wa6_reply(raw_from, from_e164, str(e))
        quote.invalidate_recordset()
        realized = ((base - (quote.amount_untaxed or 0.0)) if ex_vat
                    else (base - (quote.amount_total or 0.0)))
        basis = _("ex VAT") if ex_vat else _("incl. VAT")
        quote.with_user(actor).sudo().write(
            {"wa12_discount_note": _("Discount %s %.2f (%s)")
             % (cur, realized, basis)})
        return self._wa12_after_edit(
            quote, from_e164, raw_from,
            _("Whole-quote discount: %s %.2f off (%s)") % (cur, realized, basis),
            keep_note=True)

    def _wa12_try_edit(self, quote, body, from_e164, raw_from):
        """Parse + apply ONE draft-edit command; return the re-shown summary,
        or None if the text isn't a recognised edit command. All writes run as
        the rep (with_user) under sudo for the cross-tier ACL."""
        import re
        actor = quote.salesperson_id.id or self.env.uid
        QL = self.env["neon.finance.quote.line"].with_user(actor).sudo()
        raw = (body or "").strip()
        low = raw.lower()
        cur = quote.currency_id.name

        def err(msg):
            return self._wa6_reply(raw_from, from_e164, msg)

        def priced_equipment_blocked(line):
            return line.line_type != "custom" and (
                line.pricing_status in ("not_yet", "no_rule")
                or (line.unit_rate or 0.0) <= _WA12_PLACEHOLDER_RATE)

        # PREVIEW: render the CURRENT draft (DRAFT-stamped report) to the
        # REQUESTER. Pure preview -- no state change, no approval interaction,
        # repeatable after any edit. The DRAFT QUOTE banner is the not-final
        # marker; the QUO- number is the working reference.
        if low in ("preview", "pdf"):
            return self._wa12_send_pdf(quote, raw_from, from_e164, draft=True)

        if low in ("no tax", "notax", "no-tax"):
            quote.line_ids.with_user(actor).sudo().write({"tax_id": False})
            return self._wa12_after_edit(quote, from_e164, raw_from, _("Tax removed"))
        if low in ("with tax", "withtax", "add tax"):
            quote.line_ids.with_user(actor).sudo().write(
                {"tax_id": QL._default_tax()})
            return self._wa12_after_edit(quote, from_e164, raw_from,
                                         _("VAT 15.5%% applied"))

        # terms <text>: phone-native payment-term override (the rep is NEVER
        # told to open an Odoo button). Light-parses "N day(s)" -> final_due,
        # "X%" -> deposit; the text is kept as the term note.
        m = re.match(r"terms\s+(.+)$", raw, re.I)
        if m:
            return self._wa12_set_terms(
                quote, m.group(1).strip(), from_e164, raw_from)

        m = re.match(r"client\s+(.+)$", raw, re.I)
        if m:
            partner, e = self._wa12_resolve_client(m.group(1).strip())
            if e:
                return err(e)
            quote.event_job_id.commercial_job_id.with_user(actor).sudo().write(
                {"partner_id": partner.id})
            return self._wa12_after_edit(quote, from_e164, raw_from,
                                         _("Client set to %s") % partner.name)

        m = re.match(r"add\s+custom\s+(.+?)\s+at\s+([0-9]+(?:\.[0-9]+)?)\s*$",
                     raw, re.I)
        if m:
            desc, price = m.group(1).strip(), float(m.group(2))
            days = max(quote.line_ids.mapped("duration_days") or [1])
            QL.create({"quote_id": quote.id, "line_type": "custom",
                       "name": "[CUSTOM] %s" % desc, "quantity": 1.0,
                       "unit_rate": price, "duration_days": int(days)})
            return self._wa12_after_edit(quote, from_e164, raw_from,
                                         _("Added custom \"%s\" @ %s %.2f")
                                         % (desc, cur, price))

        if low.startswith("add ") and not low.startswith("add custom"):
            text = raw[4:].strip()
            # F2 (review MATCH-1c): only exact/strong matches add a line; a weak
            # hit is refused WITH suggestions, never drafted as a guessed line.
            matched, unmatched = self._wa12_match_text_items(text)
            if not matched:
                um = unmatched[0] if unmatched else {}
                sugg = um.get("suggestions") or []
                return err(_("Couldn't confidently match \"%s\"%s.") % (
                    text, (_(" — did you mean: %s?") % " / ".join(sugg[:3]))
                    if sugg else ""))
            days = max(quote.line_ids.mapped("duration_days") or [1])
            self._wa12_build_lines(quote, matched, int(days))
            note = _("Added %s") % ", ".join(
                it["product_name"] for it in matched)
            if unmatched:
                note += "\n" + "\n".join(_("⚠️ \"%s\" — not sure%s") % (
                    u.get("name"),
                    (_(" (did you mean: %s?)") % " / ".join(
                        (u.get("suggestions") or [])[:3]))
                    if u.get("suggestions") else "") for u in unmatched)
            return self._wa12_after_edit(quote, from_e164, raw_from, note)

        m = re.match(r"remove\s+(.+)$", raw, re.I)
        if m:
            line, e = self._wa12_match_line(quote, m.group(1).strip())
            if e:
                return err(e)
            if len(quote.line_ids) <= 1:
                return err(_("Can't remove the last line — a quote needs at "
                             "least one item."))
            nm = line.name
            line.with_user(actor).sudo().unlink()
            return self._wa12_after_edit(quote, from_e164, raw_from,
                                         _("Removed %s") % nm)

        m = re.match(r"days\s+([0-9]+)\s*$", raw, re.I)
        if m:
            n = max(1, int(m.group(1)))
            quote.line_ids.with_user(actor).sudo().write({"duration_days": n})
            return self._wa12_after_edit(quote, from_e164, raw_from,
                                         _("All lines -> %d day(s)") % n)

        m = re.match(r"days\s+(.+?)\s+([0-9]+)\s*$", raw, re.I)
        if m:
            line, e = self._wa12_match_line(quote, m.group(1).strip())
            if e:
                return err(e)
            line.with_user(actor).sudo().write(
                {"duration_days": max(1, int(m.group(2)))})
            return self._wa12_after_edit(quote, from_e164, raw_from,
                                         _("%s -> %s day(s)") % (line.name, m.group(2)))

        m = re.match(r"qty\s+(.+?)\s+([0-9]+(?:\.[0-9]+)?)\s*$", raw, re.I)
        if m:
            line, e = self._wa12_match_line(quote, m.group(1).strip())
            if e:
                return err(e)
            line.with_user(actor).sudo().write({"quantity": float(m.group(2))})
            return self._wa12_after_edit(quote, from_e164, raw_from,
                                         _("%s -> qty %s") % (line.name, m.group(2)))

        m = re.match(r"price\s+(.+?)\s+([0-9]+(?:\.[0-9]+)?)\s*$", raw, re.I)
        if m:
            line, e = self._wa12_match_line(quote, m.group(1).strip())
            if e:
                return err(e)
            amt = float(m.group(2))
            if line.line_type == "custom":
                line.with_user(actor).sudo().write(
                    {"unit_rate": amt, "discount_amount": 0.0, "discount_pct": 0.0})
                return self._wa12_after_edit(quote, from_e164, raw_from,
                                             _("%s price -> %s %.2f")
                                             % (line.name, cur, amt))
            if priced_equipment_blocked(line):
                return err(_("%s has no rate set yet — can't set a price on it.")
                           % line.name)
            if amt > line.unit_rate:
                return err(_("%s %.2f is above the base rate (%s %.2f) — that's "
                             "a markup, not a discount.")
                           % (cur, amt, cur, line.unit_rate))
            line.with_user(actor).sudo().write(
                {"discount_amount": line.unit_rate - amt, "discount_pct": 0.0})
            return self._wa12_after_edit(quote, from_e164, raw_from,
                                         _("%s -> %s %.2f/day") % (line.name, cur, amt))

        # WHOLE-QUOTE discount / target-total (review WA12-FLEX). A BARE amount
        # (no item token) discounts the WHOLE quote; "total <amt>" / "total
        # should be <amt>" / "make the total <amt>" sets the target. DEFAULT
        # basis = VAT-INCLUSIVE (the headline Total the client pays); an explicit
        # "ex vat" / "on goods" switches to the ex-VAT goods subtotal (matches
        # the per-item discounts). Distributed as a uniform per-line discount_pct
        # so it renders per-line + in the total; wa12_discount_note labels the
        # basis on the summary/PDF. MUST precede the per-item `discount <item>
        # <n>` regex (a bare number has no item token, so they're disjoint).
        _ex_vat = bool(re.search(
            r"\b(ex[\s-]*vat|on\s+goods|before\s+vat|excl\.?\s*vat)\b", low))
        _dlow = re.sub(
            r"\b(ex[\s-]*vat|on\s+goods|before\s+vat|excl\.?\s*vat|"
            r"incl\.?\s*vat|with\s+vat)\b", "", low).strip()
        m = re.match(r"(?:make\s+(?:the\s+)?total|total)\s*"
                     r"(?:should\s+be|is|=|:|of)?\s*"
                     r"([0-9]+(?:\.[0-9]+)?)\s*$", _dlow)
        if m:
            return self._wa12_whole_quote_discount(
                quote, float(m.group(1)), _ex_vat, True, from_e164, raw_from)
        m = re.match(r"discount\s+([0-9]+(?:\.[0-9]+)?)\s*$", _dlow)
        if m:
            return self._wa12_whole_quote_discount(
                quote, float(m.group(1)), _ex_vat, False, from_e164, raw_from)

        m = re.match(r"discount\s+(.+?)\s+([0-9]+(?:\.[0-9]+)?)\s*(%?)\s*$",
                     raw, re.I)
        if m:
            line, e = self._wa12_match_line(quote, m.group(1).strip())
            if e:
                return err(e)
            val, is_pct = float(m.group(2)), bool(m.group(3))
            if priced_equipment_blocked(line):
                return err(_("%s has no rate set yet — can't discount it.")
                           % line.name)
            if is_pct:
                if val > 100:
                    return err(_("Discount %% can't exceed 100."))
                line.with_user(actor).sudo().write(
                    {"discount_pct": val, "discount_amount": 0.0})
            else:
                if val > line.unit_rate:
                    return err(_("Discount %s is above the base rate — that's "
                                 "a markup.") % val)
                line.with_user(actor).sudo().write(
                    {"discount_amount": val, "discount_pct": 0.0})
            return self._wa12_after_edit(quote, from_e164, raw_from,
                                         _("%s discounted") % line.name)

        # a bare DATE message sets/confirms the event date (NOT the help menu).
        # Runs LAST so command words always win; resolve_date returns a
        # placeholder flag for anything that isn't a real date.
        ev_date, ph = self._wa12_resolve_date(raw)
        if not ph:
            cj = quote.event_job_id.commercial_job_id
            if cj:
                cj.with_user(actor).sudo().write(
                    {"event_date": ev_date, "event_date_is_placeholder": False})
            return self._wa12_after_edit(
                quote, from_e164, raw_from,
                _("Event date set to %s") % ev_date.strftime("%d %b %Y"))

        return None  # not a recognised edit command

    def _wa12_set_terms(self, quote, text, from_e164, raw_from):
        """Apply a payment term from a phone-typed `terms <text>`. Light-parses
        a leading 'N day(s)' -> final_due_days and 'X%' -> deposit_pct; the raw
        text is preserved as the term note. Append-only (a new term per edit)."""
        import re
        actor = quote.salesperson_id.id or self.env.uid
        vals = {"partner_id": quote.partner_id.id, "deposit_pct": 0.0,
                "deposit_due_days": 0, "final_due_days": 7,
                "late_policy": "reminder", "notes": "WA terms: %s" % text}
        dm = re.search(r"(\d+)\s*day", text, re.I)
        if dm:
            vals["final_due_days"] = int(dm.group(1))
        pm = re.search(r"(\d+)\s*%", text)
        if pm:
            vals["deposit_pct"] = float(pm.group(1))
        term = self.env["neon.finance.payment.term"].with_user(actor).sudo(
            ).create(vals)
        quote.with_user(actor).sudo().write({"payment_term_id": term.id})
        return self._wa12_after_edit(quote, from_e164, raw_from,
                                     _("Payment terms set: %s") % text)

    def _wa12_submit(self, quote, sess, from_e164, raw_from):
        """Submit the draft for approval (as the real requester) + ping the
        approver(s). Crash-safe: a model UserError/AccessError (e.g. no payment
        term configured) becomes a clean reply, never a webhook rollback + Meta
        re-delivery loop. Two non-pending outcomes are handled explicitly:
        (1) finance config approval_required_for_all=False makes submit go
        draft->approved atomically -> deliver the PDF now (no tap will fire);
        (2) no approver is reachable -> tell the requester rather than leave a
        silent stuck pending_approval. (Self-approval collapse is NOT offered --
        the requester is never their own approver here.)"""
        requester = sess.user_id
        sess.sudo().write({"step": "done", "active": False})
        # defence-in-depth: guarantee a payment term so the submit gate can
        # never tell a phone user to open an Odoo button (proof wall a).
        self._wa12_ensure_payment_term(quote, quote.partner_id)
        try:
            quote.with_user(requester.id).sudo().action_submit_for_approval()
        except (UserError, AccessError) as e:
            return self._wa6_reply(raw_from, from_e164, str(e))
        if quote.state == "approved":
            # config relaxation already approved it -> the approve-tap PDF path
            # will never run; send the final PDF straight to the requester.
            sp_phone = self._wa6_user_phone(quote.salesperson_id) or raw_from
            self._wa12_send_pdf(quote, sp_phone, sp_phone, draft=False,
                                with_send_button=True)
            return self._wa6_reply(raw_from, from_e164, _(
                "%s was auto-approved — the PDF is on its way.") % quote.name)
        pinged = self._wa12_send_approval_ping(quote, requester)
        if not pinged:
            return self._wa6_reply(raw_from, from_e164, _(
                "Submitted %s, but no approver is reachable on WhatsApp right "
                "now — please follow it up in Odoo.") % quote.name)
        return self._wa6_reply(raw_from, from_e164, _(
            "Submitted %s for approval — you'll get the PDF here once it's "
            "approved.") % quote.name)

    # ================================================================
    # Approval dispatch (dual-payload, first-tap-wins lock).
    # ================================================================
    def _wa12_handle_tap(self, intent, quote, from_e164, raw_from, message):
        self._wa6_audit_in(from_e164, message, "wa12-tap")
        tapper = self._wa6_resolve_user(from_e164)
        if not tapper:
            return None
        if not quote or not quote.exists():
            return self._wa6_reply(raw_from, from_e164, _(
                "That quote is no longer available."))
        if len(quote) > 1:
            # a payload-less template-QR tap with several quotes pending at once
            # -- we can't tell which the button was for. REFUSE rather than act
            # on the wrong quote (money surface); the in-window HMAC buttons or
            # Odoo resolve it unambiguously.
            return self._wa6_reply(raw_from, from_e164, _(
                "Several quotes are awaiting approval — I can't tell which this "
                "is for. Please action it in Odoo."))
        if intent == "wa12_view_pdf":
            # the HMAC payload binds only to quote_id; gate the document send
            # on the tapper's role (approver / the salesperson / an initiator)
            # so a forwarded button id can't pull a quote PDF for an outsider.
            if not (tapper.id in _WA12_APPROVER_UIDS
                    or tapper == quote.salesperson_id
                    or self._wa6_can_initiate(tapper)):
                return self._wa6_reply(raw_from, from_e164, _(_WA12_REFUSAL))
            return self._wa12_send_pdf(quote, raw_from, from_e164, draft=True)
        if intent == "wa12_send":
            return self._wa12_handle_send_to_client(
                quote, tapper, from_e164, raw_from)
        # approve / reject -> first-tap-wins lock on the quote.
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)", (_WA12_LOCK_NS, quote.id))
        if quote.state != "pending_approval":
            return self._wa6_reply(raw_from, from_e164, _(
                "%s is already %s.") % (quote.name, quote.state))
        if not self._wa12_is_approver(tapper):
            return self._wa6_reply(raw_from, from_e164, _(_WA12_REFUSAL))
        if intent == "wa12_approve":
            try:
                quote.with_user(tapper.id).sudo().action_approve()
            except (UserError, AccessError) as e:
                # model gate (has_group) rejected -> clean reply, never a crash
                # that rolls back the held advisory lock + re-loops via Meta.
                return self._wa6_reply(raw_from, from_e164, str(e))
            self._wa12_notify_other_approver(quote, tapper, approved=True)
            sp_phone = self._wa6_user_phone(quote.salesperson_id)
            # PDF send is best-effort inside _wa12_send_pdf (a render error must
            # not roll back the committed approval).
            self._wa12_send_pdf(quote, sp_phone, sp_phone, draft=False,
                                with_send_button=True)
            return self._wa6_reply(raw_from, from_e164, _("Approved ✓ %s")
                                   % quote.name)
        if intent == "wa12_reject":
            # open a q_reject session to capture the approver's comment.
            self.env["neon.wa.equip.session"]._start_quote(
                from_e164, tapper, "q_reject", {"quote_id": quote.id})
            return self._wa6_reply(raw_from, from_e164, _(
                "Send a one-line reason and I'll relay it to the requester."))
        return None

    def _wa12_apply_reject_comment(self, quote, comment, sess, from_e164,
                                   raw_from):
        sess.sudo().write({"step": "done", "active": False})
        if not (quote.exists() and quote.state == "pending_approval"):
            # the OTHER approver resolved it between the Reject tap and this
            # comment (first-tap-wins race). Do NOT relay a "rejected" message
            # to the requester -- the approve path already messaged them; that
            # would be a contradictory money-state note on a live quote.
            return self._wa6_reply(raw_from, from_e164, _(
                "%s is already %s — nothing to relay.") % (
                    quote.name if quote.exists() else _("That quote"),
                    quote.state if quote.exists() else _("gone")))
        try:
            quote.with_user(sess.user_id.id).with_context(
                rejection_reason=comment or "(no reason given)"
            ).sudo().action_reject()
        except (UserError, AccessError) as e:
            return self._wa6_reply(raw_from, from_e164, str(e))
        # relay to the requester ONLY now that the rejection actually applied.
        rphone = self._wa6_user_phone(quote.salesperson_id)
        if rphone:
            self._wa6_reply(rphone, rphone, _(
                "Quote %s was rejected: %s") % (quote.name, comment or ""))
        return self._wa6_reply(raw_from, from_e164, _("Rejection relayed."))

    def _wa12_handle_send_to_client(self, quote, tapper, from_e164, raw_from):
        """The requester taps [Send to client] -> email the client + mark sent.
        v1: email (the client WhatsApp doc is phase 2). The [Send to client]
        button is minted only onto the salesperson's PDF, but the HMAC binds to
        quote_id (not the recipient) -- so gate the egress on ownership: only
        the quote's salesperson or an approver may dispatch it to the client."""
        if not (tapper == quote.salesperson_id
                or self._wa12_is_approver(tapper)):
            return self._wa6_reply(raw_from, from_e164, _(_WA12_REFUSAL))
        if quote.state != "approved":
            return self._wa6_reply(raw_from, from_e164, _(
                "%s isn't approved yet.") % quote.name)
        if not (quote.partner_id.email or "").strip():
            # action_send marks the quote 'sent', but a client with NO email on
            # file receives nothing -> a false "sent" on an undelivered quote.
            # Refuse honestly and leave the state at 'approved' until an email
            # is set (or the rep forwards the PDF themselves).
            return self._wa6_reply(raw_from, from_e164, _(
                "%s has no email on file — add one in Odoo or forward the PDF "
                "yourself. %s is NOT marked sent.") % (
                    quote.partner_id.name or _("That client"), quote.name))
        try:
            quote.with_user(tapper.id).sudo().action_send()
        except (UserError, AccessError) as e:
            return self._wa6_reply(raw_from, from_e164, str(e))
        return self._wa6_reply(raw_from, from_e164, _(
            "Sent %s to the client.") % quote.name)

    # ================================================================
    # Price: face — read-only.
    # ================================================================
    @api.model
    def _wa12_price_lookup(self, product):
        """The per-product day rate via the SAME engine resolver the quote line
        uses (mirrors neon.finance.quote.line._find_pricing_rule: per-product
        rule PRIMARY -> category rule fallback -> none). Returns
        (rate_or_None, currency_name). Per binding (b) every per-product rule
        carries a flat 1.0 bracket, so base_rate IS the per-day rate. USD v1
        (Q3). This is why Price: never reads product.list_price."""
        currency = self.env.ref("base.USD")
        Rule = self.env["neon.finance.pricing.rule"].sudo()
        today = fields.Date.context_today(self)
        base = [("currency_id", "=", currency.id), ("active", "=", True),
                ("effective_date", "<=", today)]
        rule = Rule.search(
            [("product_template_id", "=", product.id)] + base,
            order="effective_date desc, id desc", limit=1)
        if not rule and product.equipment_category_id:
            rule = Rule.search(
                [("product_template_id", "=", False),
                 ("category_id", "=", product.equipment_category_id.id)] + base,
                order="effective_date desc, id desc", limit=1)
        return (rule.base_rate if rule else None), currency.name

    def _wa12_run_price(self, sender, body, from_e164, raw_from, message):
        self._wa6_audit_in(from_e164, message, "wa12-price")
        rest = self._wa12_strip_cmd(body, _WA12_PRICE_CMDS)
        items = self._wa6_match_items(rest)
        # MONEY GATE (Robin/Tatenda 2026-06-13): Price: quotes a rate ONLY for an
        # exact/strong hit -- PARITY with the quote-build gate (_wa12_match_slot_
        # items:1328 / _wa12_match_text_items:1386). Resolver v2 widens the
        # matched set with trgm-weak + LLM-grounded picks; a weak/LLM hit must
        # NOT surface a guessed rate over WhatsApp -> it reads as "couldn't find
        # a price", exactly as the quote path would refuse to auto-add it.
        matched = [it for it in items
                   if it.get("status") == "matched"
                   and it.get("confidence") in ("exact", "strong")]
        if not matched:
            return self._wa6_reply(raw_from, from_e164, _(
                "Couldn't find a price for \"%s\".") % rest)
        lines = []
        for it in matched:
            prod = self.env["product.template"].sudo().browse(it["product_id"])
            # the ENGINE rate (rule x bracket), NOT product.list_price -- so the
            # Price: read-out matches what Quote: actually charges (review
            # WA12-FLEX-3). no_rule / placeholder -> 'no rate set yet'.
            rate, cur = self._wa12_price_lookup(prod)
            if rate is None or rate <= _WA12_PLACEHOLDER_RATE:
                lines.append(_("%s — no rate set yet") % prod.name)
            else:
                lines.append(_("%s — %s %.2f / day") % (prod.name, cur, rate))
        return self._wa6_reply(raw_from, from_e164, "\n".join(lines))

    # ================================================================
    # Helpers — parse / resolve / build / guard / summary / send.
    # ================================================================
    @api.model
    def _wa12_parse_quote(self, rest):
        """(client, items, date_text, days). Format: '<client> — <items>,
        <date>'. Splits client off the first em-dash / ' - ' / ':'; the date
        is the trailing ', <date>' if present; 'for N days' -> days."""
        import re
        days = None
        # consume the optional plural + a word boundary so "for 3 days" doesn't
        # leave a dangling "s" glued into the item list.
        m = re.search(r"\bfor\s+(\d+)\s+days?\b", rest or "", re.I)
        if m:
            days = max(1, int(m.group(1)))
            rest = (rest[:m.start()] + rest[m.end():]).strip(" ,-")
        # client vs the rest: first em-dash / hyphen / colon.
        parts = re.split(r"\s+[—–-]\s+|:\s+", rest or "", maxsplit=1)
        if len(parts) < 2:
            return "", "", "", days
        client = parts[0].strip()
        tail = parts[1].strip()
        # trailing ", <date>"
        date_txt = ""
        if "," in tail:
            head, _, last = tail.rpartition(",")
            date_txt = last.strip()
            tail = head.strip()
        return client, tail, date_txt, days

    @api.model
    def _wa12_resolve_client(self, name):
        """(partner, error_text). Exact-ish res.partner name search. 0 -> a
        'not found' message; >1 -> an 'ambiguous' message naming the count;
        1 -> that partner. NEVER auto-creates (mirrors WA-9 discipline)."""
        P = self.env["res.partner"].sudo()
        hits = P.search([("name", "ilike", name), ("is_venue", "=", False)],
                        limit=6)
        if not hits:
            return P.browse(), _(
                "Couldn't find a client matching \"%s\". Check the name or "
                "add them in Odoo first.") % name
        exact = hits.filtered(lambda p: (p.name or "").strip().lower()
                              == name.strip().lower())
        if len(exact) == 1:
            return exact, None
        if len(hits) == 1:
            return hits, None
        return P.browse(), _(
            "More than one client matches \"%s\" (%d). Be more specific."
        ) % (name, len(hits))

    @api.model
    def _wa12_resolve_date(self, date_txt):
        """(date, is_placeholder). DAY-FIRST (Zimbabwe). Tolerant of 25/09/26,
        25/09/2026, 25-09-2026, 29 Sept 2026, 15 september 2026, 15th Sep 2026.
        Unparseable -> today, flagged placeholder (event_date is required)."""
        from datetime import datetime
        import re as _re
        today = fields.Date.context_today(self)
        s = (date_txt or "").strip()
        if s:
            # normalise: strip ordinal suffixes (15th->15), Sept->Sep, collapse ws
            s = _re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s, flags=_re.I)
            s = _re.sub(r"\bsept\b", "Sep", s, flags=_re.I)
            s = " ".join(s.split())
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y",
                        "%d-%m-%y", "%d %b %Y", "%d %B %Y", "%d %b %y",
                        "%d %B %y", "%d %b", "%d %B", "%d/%m", "%d-%m"):
                try:
                    d = datetime.strptime(s, fmt).date()
                    if d.year == 1900:
                        d = d.replace(year=today.year)
                    return d, False
                except ValueError:
                    continue
        return today, True

    def _wa12_build_lines(self, quote, matched, days):
        """Create one quote.line per matched item. unit_rate = the product's
        per-product day rate (Robin ruling 1 -- direct, not the category
        engine); a placeholder/0 rate stays low so the no_rule guard catches
        it. line_type='equipment' (no equipment_line_id -> recalc stamps
        'manual' when unit_rate>0 else 'not_yet')."""
        # create the financial lines as the real rep (create_uid honesty); sudo
        # for the cross-tier ACL (the sales actor may not own quote.line).
        actor = quote.salesperson_id.id or self.env.uid
        QL = self.env["neon.finance.quote.line"].with_user(actor).sudo()
        for it in matched:
            # WA-12.6 CUSTOM line: a not-in-catalogue item the rep wrote in
            # (no product_id, an explicit per-day rep_price) -> line_type
            # 'custom', rendered loudly CUSTOM, approval-visible (F8 rule).
            if not it.get("product_id"):
                QL.create({
                    "quote_id": quote.id,
                    "line_type": "custom",
                    "name": it.get("custom_desc") or it.get("product_name")
                    or _("Custom item"),
                    "quantity": float(it.get("qty") or 1),
                    "duration_days": int(days or 1),
                    "unit_rate": float(it.get("rep_price") or 0.0),
                })
                continue
            prod = self.env["product.template"].sudo().browse(it["product_id"])
            # unit_rate is left UNSET (0.0) -> the pricing ENGINE resolves it
            # (per-product rule PRIMARY -> category rule -> no_rule, which the
            # guard blocks). The WA-12 lane NEVER reads list_price.
            # F8 EXCEPTION: an item the engine can't price MAY carry an
            # explicit REP price (it["rep_price"], set only when no catalogue
            # rate resolves + loudly flagged in the echo/summary/ping/PDF) ->
            # created WITH that rate, so the create() gate stamps 'manual'.
            QL.create({
                "quote_id": quote.id,
                "line_type": "equipment",
                "product_template_id": prod.id,
                "name": prod.name,
                "quantity": float(it.get("qty") or 1),
                "duration_days": int(days or 1),
                "unit_rate": float(it.get("rep_price") or 0.0),
            })

    def _wa12_unpriced_lines(self, quote):
        """Names of lines with NO real rate (binding-1 guard, line_type-aware).

        F8 EVOLUTION (user-ratified): the guard's job is "no silent zero / no
        invented rate" — an EQUIPMENT line blocks on not_yet/no_rule or a base
        unit_rate<=$1. A 'manual' line with a REAL rate now PASSES: the only
        WA-12 path that creates one is the explicit, loudly-flagged rep-price
        mechanism (no catalogue rate -> the rep typed the rate; rendered
        '(rep-priced)' in the echo/summary/ping/PDF and queryable via
        pricing_status='manual' for Robin's rate-promotion review). The old
        blanket manual-block predates per-product rules; the engine path still
        NEVER fabricates manual (lines are created at 0.0 unless rep-priced).
        A CUSTOM line (explicit typed rate) passes once its unit_rate>$1.
        Reads the BASE unit_rate, not the discounted effective — a discount
        (even 100%) is an explicit, approval-visible choice."""
        bad = []
        for l in quote.line_ids:
            if l.line_type == "custom":
                if (l.unit_rate or 0.0) <= _WA12_PLACEHOLDER_RATE:
                    bad.append(l.name or "(item)")
                continue
            if l.pricing_status in ("not_yet", "no_rule") \
                    or (l.unit_rate or 0.0) <= _WA12_PLACEHOLDER_RATE:
                bad.append(l.name or "(item)")
        return bad

    def _wa12_default_payment_term(self):
        """Get-or-create the company-default phone-quote term: 7-day net (org
        house rule -- 'Payment terms default to 7 days unless agreed
        otherwise'). Singleton (no partner), idempotent by its structured key,
        so a phone quote is NEVER left termless."""
        PT = self.env["neon.finance.payment.term"].sudo()
        key = [("partner_id", "=", False), ("deposit_pct", "=", 0.0),
               ("deposit_due_days", "=", 0), ("final_due_days", "=", 7),
               ("late_policy", "=", "reminder")]
        term = PT.search(key, limit=1)
        if not term:
            term = PT.create({
                "deposit_pct": 0.0, "deposit_due_days": 0, "final_due_days": 7,
                "late_policy": "reminder",
                "notes": "Company default — 7-day net (WA-12 phone quote; org "
                         "house rule)."})
        return term

    def _wa12_ensure_payment_term(self, quote, partner):
        """submit_for_approval requires a payment term. Prefer the partner's
        most-recent; else AUTO-APPLY the company 7-day default (get-or-create).
        Never leaves a phone quote termless -- that made submit tell the rep to
        open an Odoo button, breaking the phone-native flow (proof wall a).
        Idempotent (a no-op once a term is set)."""
        if quote.payment_term_id:
            return
        PT = self.env["neon.finance.payment.term"].sudo()
        term = (PT.search([("partner_id", "=", partner.id)],
                          order="create_date desc", limit=1)
                if (partner and partner.id and "partner_id" in PT._fields)
                else PT.browse())
        if not term:
            term = self._wa12_default_payment_term()
        actor = quote.salesperson_id.id or self.env.uid
        quote.with_user(actor).sudo().write({"payment_term_id": term.id})

    def _wa12_draft_summary(self, quote, unpriced):
        cur = quote.currency_id.name
        rows = []
        # WA-12.3: number the lines (1-based, the exact order _wa12_match_line
        # indexes) so the rep can edit by number on the draft too.
        for _i, l in enumerate(quote.line_ids, 1):
            base = l.unit_rate or 0.0
            if l.discount_amount:
                eff, disc = base - l.discount_amount, "%s %.2f" % (
                    cur, l.discount_amount)
            elif l.discount_pct:
                eff, disc = base * (1 - l.discount_pct / 100.0), "%g%%" % (
                    l.discount_pct)
            else:
                eff, disc = base, None
            if l.line_type == "custom":
                tag = "[CUSTOM] "
            elif l.pricing_status == "manual" and not l.equipment_line_id:
                # F8: a rep-priced line (no catalogue rate) is LOUD everywhere.
                tag = "[REP-PRICED] "
            else:
                tag = ""
            if disc:
                rate_txt = "%s %.2f → %.2f/day (disc. %s)" % (
                    cur, base, max(eff, 0.0), disc)
            else:
                rate_txt = "%s %.2f/day" % (cur, base)
            rows.append("%d. %s%s ×%g — %s × %dd"
                        % (_i, tag, l.name, l.quantity, rate_txt,
                           l.duration_days))
        # the VAT line is conditional: 'no tax' clears the line taxes -> no VAT.
        vat = _(" (incl. VAT)") if (quote.amount_tax or 0.0) else _(" (no VAT)")
        # event date is ALWAYS shown (proof wall b); a placeholder/unset date
        # nudges the rep to send one (which the bare-date edit then sets).
        cj = quote.event_job_id.commercial_job_id
        ev = cj.event_date if cj else False
        ev_ph = (cj.event_date_is_placeholder if cj else True) or not ev
        date_line = _("📅 %s%s\n") % (
            ev.strftime("%d %b %Y") if ev else _("date not set"),
            _(" — TBC, reply with a date") if ev_ph else "")
        # WA-12 whole-quote discount label (the per-line discounts above already
        # carry the math; this names the basis the rep chose).
        disc_line = (_("💸 %s\n") % quote.wa12_discount_note
                     if quote.wa12_discount_note else "")
        return _("*Quote %s* for %s\n%s%s%s\n*Total: %s %.2f*%s") % (
            quote.name, quote.partner_id.name, date_line, "\n".join(rows),
            "\n" + disc_line if disc_line else "",
            cur, quote.amount_total or 0.0, vat)

    def _wa12_send_approval_ping(self, quote, requester):
        """Ping the MD/OD approver audience (uids 7 + 21), skipping anyone
        inactive or no longer holding the approver group. The REQUESTER is NOT
        skipped (WA-12 addendum, 12 Jun 2026): an MD/OD who submits their own
        quote receives the ping too -- their own [Approve] tap is valid (the
        ratified self-approval principle), so the same phone gets both the
        summary and the ping. Cold window -> the Active wa12_quote_approval
        TEMPLATE (static QR buttons; quote resolved from pending context on
        tap); in window -> interactive HMAC buttons. Returns the number
        actually pinged so the caller can surface an empty audience instead of
        a silent stuck quote."""
        summary = self._wa12_item_summary(quote)
        total = "%s %.2f" % (quote.currency_id.name, quote.amount_total or 0.0)
        approvers = self.env["res.users"].sudo().browse(
            list(_WA12_APPROVER_UIDS))
        sent = 0
        for appr in approvers.exists().filtered(
                lambda u: u.active and self._wa12_is_approver(u)):
            phone = self._wa6_user_phone(appr)
            if not phone:
                continue
            body_params = [requester.name, quote.partner_id.name, summary, total]
            if self._wa5_window_open(phone):
                res = self.sudo().send_buttons(
                    phone, self._wa12_ping_body(body_params),
                    self._wa12_inwindow_buttons(quote))
            else:
                res = self.sudo().send_template(
                    phone, _WA12_TEMPLATE, body_params=body_params)
            # only count a ping Meta actually ACCEPTED. A rejected cold template
            # (opt-out / no_config / 4xx-5xx) must NOT read as 'pinged', else the
            # requester is told "approval on its way" while the quote is silently
            # stranded in pending_approval. send_buttons -> bool; send_template
            # -> {'ok': bool}.
            ok = res.get("ok") if isinstance(res, dict) else bool(res)
            if not ok:
                _logger.warning(
                    "WA-12 approval ping to %s NOT accepted (%s) for %s",
                    phone, res, quote.name)
                continue
            self._wa6_audit_out(phone, "wa12 approval ping %s" % quote.name)
            sent += 1
        return sent

    @api.model
    def _wa12_item_summary(self, quote):
        names = []
        for l in quote.line_ids[:4]:
            flag = ""
            if l.line_type != "custom" and l.pricing_status == "manual" \
                    and not l.equipment_line_id:
                # F8: the approver sees exactly which rates came from the rep.
                flag = _(" (rep-priced)")
            names.append("%s×%g%s" % (l.name, l.quantity, flag))
        more = "…" if len(quote.line_ids) > 4 else ""
        return ", ".join(names) + more

    @api.model
    def _wa12_ping_body(self, params):
        return _("🧾 Quote approval needed\n%s drafted a quote for %s.\n%s\n"
                 "Total: %s\nApprove or reject below.") % tuple(params)

    def _wa12_inwindow_buttons(self, quote):
        secret = self.env["ir.config_parameter"].sudo().get_param(
            "database.secret") or ""
        return [
            {"id": wa_payload.encode(secret, "wa12_approve", quote.id),
             "title": "Approve"},
            {"id": wa_payload.encode(secret, "wa12_reject", quote.id),
             "title": "Reject"},
            {"id": wa_payload.encode(secret, "wa12_view_pdf", quote.id),
             "title": "View PDF"},
        ]

    def _wa12_notify_other_approver(self, quote, who, approved):
        """First-tap-wins: tell the OTHER approver the decision is made."""
        others = self.env["res.users"].sudo().browse(
            [u for u in _WA12_APPROVER_UIDS if u != who.id])
        for o in others.exists():
            phone = self._wa6_user_phone(o)
            if phone and self._wa5_window_open(phone):
                self._wa6_reply(phone, phone, _(
                    "%s was %s by %s — no action needed.") % (
                    quote.name, "approved" if approved else "rejected",
                    who.name))

    def _wa12_send_pdf(self, quote, raw_to, to_e164, draft=True,
                       with_send_button=False):
        """Render the quote QWeb PDF (DRAFT-stamped by state) + send it as a
        WhatsApp document. Optionally append the [Send to client] button (to the
        requester on approval)."""
        if not raw_to:
            return True
        report = self.env.ref(
            "neon_finance.action_report_neon_quote", raise_if_not_found=False)
        if not report:
            return self._wa6_reply(raw_to, to_e164, _("Quote PDF unavailable."))
        # Odoo 17: render via ir.actions.report with the report_ref first arg.
        # BEST-EFFORT: _render_qweb_pdf raises on a QWeb/wkhtmltopdf error, and
        # this is called AFTER action_approve commits in the same webhook txn --
        # an unhandled raise would roll the whole request back (un-approving the
        # quote) and Meta would re-deliver the tap into an infinite loop. So a
        # render failure must degrade to a soft reply, never propagate.
        try:
            pdf, _ext = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
                report.report_name, res_ids=[quote.id])
        except Exception as e:  # noqa: BLE001 -- must not roll back the approval
            _logger.warning("WA-12 PDF render failed for %s: %s", quote.name, e)
            return self._wa6_reply(raw_to, to_e164, _(
                "%s is approved — the PDF couldn't be generated just now; "
                "it can be sent from Odoo.") % quote.name)
        fname = "%s.pdf" % (quote.name or "quote").replace("/", "-")
        self.sudo().send_document(raw_to, pdf, fname,
                                  caption=_("Quote %s") % quote.name)
        self._wa6_audit_out(to_e164 or raw_to, "wa12 pdf %s" % quote.name,
                            "document")
        if with_send_button and self._wa5_window_open(to_e164 or raw_to):
            secret = self.env["ir.config_parameter"].sudo().get_param(
                "database.secret") or ""
            self.sudo().send_buttons(
                raw_to, _("Approved ✓ — send to the client?"),
                [{"id": wa_payload.encode(secret, "wa12_send", quote.id),
                  "title": "Send to client"}])
        return True
