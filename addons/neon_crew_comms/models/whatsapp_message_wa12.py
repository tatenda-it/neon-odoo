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

# Quote session steps live on the shared equip-session. WA-12 claims q_confirm /
# q_reject + the new-client capture steps + the conversational steps.
_WA12_STEPS = ("q_confirm", "q_reject") + _WA12_CAPTURE_STEPS + _WA12_CONVO_STEPS

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
            intent, quote = tap
            return self._wa12_handle_tap(
                intent, quote, from_e164, raw_from, message)

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
            payload = ((message.get("interactive") or {})
                       .get("button_reply") or {}).get("id")
            secret = self.env["ir.config_parameter"].sudo().get_param(
                "database.secret") or ""
            decoded = wa_payload.decode(secret, payload or "")
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
        """Build a DRAFT quote on a provisional chain + echo it for confirm.
        Returns True (claimed) once it looks like a real quote command; on a
        resolution miss it replies an honest message (still claimed -- the
        sender explicitly typed Quote:)."""
        self._wa6_audit_in(from_e164, message, "wa12-quote")
        rest = self._wa12_strip_cmd(body, _WA12_QUOTE_CMDS + _WA12_QUOTE_TRIGGERS)
        client_txt, items_txt, date_txt, days = self._wa12_parse_quote(rest)
        if not client_txt or not items_txt:
            return self._wa6_reply(raw_from, from_e164, _(
                "To quote, send:  Quote: <client> — <items>, <date>"))
        # F2 (review MATCH-1): confidence-gate the items. A WEAK/ambiguous hit
        # must NOT draft a guessed product -> route the whole quote through the
        # confirm-before-draft gate (q_items) so the rep resolves it; only an
        # all-confident tight quote provisions directly (unchanged UX).
        matched, unmatched = self._wa12_match_text_items(items_txt)
        if not matched and not unmatched:
            return self._wa6_reply(raw_from, from_e164, _(
                "Couldn't match any catalogue items in \"%s\".") % items_txt)
        if unmatched:
            return self._wa12_open_items_confirm(
                sender, client_txt, matched, unmatched, date_txt, {},
                from_e164, raw_from)
        # resolve the client: exactly one -> proceed; 0 or >1 -> the guided
        # new-client intake / list-then-pick (items + date are buffered so the
        # quote resumes without re-entry). Fixes the old >1 'be more specific'
        # dead-end + adds in-session client capture (LIVE-blocking amendment).
        partner, candidates = self._wa12_client_candidates(client_txt)
        if not partner:
            return self._wa12_start_client_intake(
                sender, client_txt, candidates, matched, date_txt, days,
                from_e164, raw_from)
        return self._wa12_quote_from_slots(
            sender, partner, matched, date_txt, days, from_e164, raw_from)

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
                                  prefills=None):
        """Open the qc_pick session: list any existing matches + offer *new*.
        Buffers the matched items + date so the quote resumes without re-entry.
        ``prefills`` (M3): phone/email/contact already present in the rep's
        brief — pre-fill the capture so only MISSING slots get asked."""
        buf = {"matched": matched, "date_txt": date_txt or "",
               "days": days or 1, "client_txt": client_txt,
               "candidate_ids": candidates.ids[:8],
               "prefills": prefills or {}}
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
            if not buf.get("matched"):
                # M5 bare-intent path: the client is set but no items were
                # captured yet -> ask for them (same lane, no re-entry).
                self.env["neon.wa.equip.session"]._start_quote(
                    from_e164, sender, "q_itemreq",
                    {"client_txt": partner.name, "partner_id": partner.id,
                     "date_txt": buf.get("date_txt") or "",
                     "prefills": buf.get("prefills") or {}})
                return self._wa6_reply(raw_from, from_e164, _(
                    "%s — what items? (e.g. `2x RGB LED CAN, smoke machine`)")
                    % partner.name)
            return self._wa12_quote_from_slots(
                sender, partner, buf.get("matched") or [],
                buf.get("date_txt") or "", buf.get("days") or 1,
                from_e164, raw_from, extras=buf.get("prefills") or {})

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
        """M4: complaint/correction language gets a REPAIR prompt, never the
        syntax menu."""
        return self._wa6_reply(raw_from, from_e164, _(
            "What should I fix — the items, the client, or the date? "
            "e.g. `remove <item>` · `qty <item> 2` · a new date · "
            "`client <name>`."))

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
        buf = sess._get_buffer()
        buf = buf if isinstance(buf, dict) else {}

        if self._wa12_is_cancel(norm):
            sess.sudo().write({"step": "done", "active": False})
            return self._wa6_reply(raw_from, from_e164, _("Quote cancelled."))

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
                buf.update({"client_txt": partner.name,
                            "partner_id": partner.id})
                sess.sudo().write({"step": "q_itemreq"})
                sess._set_buffer(buf)
                return self._wa6_reply(raw_from, from_e164, _(
                    "%s — what items? (e.g. `2x RGB LED CAN, smoke machine`)")
                    % partner.name)
            return self._wa12_start_client_intake(
                sender, raw, candidates, buf.get("matched") or [],
                buf.get("date_txt") or "", buf.get("days") or 1,
                from_e164, raw_from, prefills=buf.get("prefills") or {})

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
            matched = buf.get("matched") or []
            if not matched:
                return self._wa6_reply(raw_from, from_e164, _(
                    "Nothing matched to draft yet — re-type the items, or "
                    "*cancel*."))
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

        # deterministic corrections first (free).
        handled = self._wa12_q_items_try(sess, buf, raw, from_e164, raw_from)
        if handled is not None:
            return handled

        # F3: natural corrections -> ONE translated command, re-run through the
        # SAME deterministic parser ("the LED screen should be the 5m x 3m
        # one" -> replace ... = ...). REPAIR -> the repair prompt.
        cmd = self._wa12_llm_translate_items(raw, buf)
        if cmd:
            if cmd.upper().startswith("REPAIR"):
                return self._wa12_repair_prompt(raw_from, from_e164)
            cmd_norm = " ".join(cmd.lower().split())
            # FSM-7: the translator may emit 'cancel'/'yes' -- the deterministic
            # re-run can't execute those, so handle them here (cancel runs; a
            # natural confirm asks for one explicit 'yes' -- no LLM-triggered
            # state transition).
            if self._wa12_is_cancel(cmd_norm):
                sess.sudo().write({"step": "done", "active": False})
                return self._wa6_reply(raw_from, from_e164, _("Quote cancelled."))
            if cmd_norm in _WA12_SUBMIT_WORDS:
                return self._wa6_reply(raw_from, from_e164, _(
                    "Ready when you are — reply *yes* to draft the quote."))
            handled = self._wa12_q_items_try(
                sess, buf, cmd, from_e164, raw_from)
            if handled is not None:
                return handled
        # MATCH-2/FSM-5: neither a command nor a translatable correction -> if
        # the raw text weak/near-matches catalogue items, SURFACE them as picks
        # in the confirm echo (never silently drop); else the syntax card.
        surfaced = self._wa12_surface_unmatched(sess, buf, raw, from_e164,
                                                raw_from)
        if surfaced is not None:
            return surfaced
        return self._wa6_reply(raw_from, from_e164, _(
            "Reply *yes* to draft, *cancel*, or correct me — `remove <item>` "
            "· `qty <item> 2` · `price <item> <amt>` · a date · "
            "`client <name>` · re-type an item."))

    def _wa12_surface_unmatched(self, sess, buf, raw, from_e164, raw_from):
        """MATCH-2/FSM-5: a re-typed item that only WEAK/near-matches is added
        to the confirm echo's unmatched bucket WITH its suggestions (a pick),
        never silently dropped. Returns the reshow, or None if the text yields
        no catalogue signal at all (-> the caller's syntax card)."""
        _adds, weak = self._wa12_match_text_items(raw)
        weak = [w for w in weak if w.get("suggestions")]
        if not weak:
            return None
        un = list(buf.get("unmatched") or [])
        seen = {(u.get("name") or "").lower() for u in un}
        for w in weak:
            if (w.get("name") or "").lower() not in seen:
                un.append(w)
        buf["unmatched"] = un
        sess._set_buffer(buf)
        return self._wa6_reply(raw_from, from_e164,
                               self._wa12_items_confirm_text(buf))

    def _wa12_q_items_try(self, sess, buf, raw, from_e164, raw_from):
        """Apply ONE q_items correction command (deterministic). Returns the
        reply, or None if ``raw`` isn't a recognised correction. Used for both
        the rep's literal text and the LLM-translated command (F3)."""
        import re
        matched = buf.get("matched") or []
        norm = " ".join((raw or "").strip().lower().split())

        def reshow():
            sess._set_buffer(buf)
            return self._wa6_reply(raw_from, from_e164,
                                   self._wa12_items_confirm_text(buf))

        # FSM-4: resolve a token to EXACTLY ONE buffered line. >1 contains-match
        # -> refuse with the colliding names (mirrors the post-draft
        # _wa12_match_line resolver; never silently target the first hit).
        def find_one(tok):
            tok = (tok or "").strip().lower()
            hits = [it for it in matched
                    if tok in (it.get("product_name") or "").lower()]
            if not hits:
                return None, self._wa6_reply(raw_from, from_e164, _(
                    "No line matches \"%s\".") % tok)
            if len(hits) > 1:
                return None, self._wa6_reply(raw_from, from_e164, _(
                    "Several items match \"%s\" — be more specific: %s")
                    % (tok, " / ".join(it["product_name"] for it in hits)))
            return hits[0], None

        m = re.match(r"client\s+(.+)$", raw, re.I)
        if m:
            name = m.group(1).strip()
            partner, _cand = self._wa12_client_candidates(name)
            buf["client_txt"] = partner.name if partner else name
            buf["partner_id"] = partner.id if partner else False
            return reshow()

        # F3: per-item replace -- `replace <old> = <new>` (also `<old> -> <new>`).
        m = re.match(r"replace\s+(.+?)\s*(?:=|->)\s*(.+)$", raw, re.I)
        if m:
            old_tok, new_txt = m.group(1).strip(), m.group(2).strip()
            it, err = find_one(old_tok)
            if err:
                return err
            new_hit = self._wa6_match_one(new_txt)
            if not (new_hit.get("status") == "matched"
                    and new_hit.get("confidence") in ("exact", "strong")):
                sugg = new_hit.get("suggestions") or []
                return self._wa6_reply(raw_from, from_e164, _(
                    "Couldn't confidently match \"%s\"%s.") % (
                        new_txt,
                        (_(" — did you mean: %s?") % " / ".join(sugg[:3]))
                        if sugg else ""))
            it.update({"product_id": new_hit["product_id"],
                       "product_name": new_hit["product_name"],
                       "rep_price": None, "stated_price": None})
            return reshow()

        m = re.match(r"remove\s+(.+)$", raw, re.I)
        if m:
            tok = m.group(1).strip().lower()
            keep = [it for it in matched
                    if tok not in (it.get("product_name") or "").lower()]
            un_keep = [um for um in (buf.get("unmatched") or [])
                       if tok not in (um.get("name") or "").lower()]
            n_removed = (len(matched) - len(keep)) + (
                len(buf.get("unmatched") or []) - len(un_keep))
            if not n_removed:
                return self._wa6_reply(raw_from, from_e164, _(
                    "No line matches \"%s\".") % m.group(1).strip())
            buf["matched"], buf["unmatched"] = keep, un_keep
            # FSM-4 side: announce a multi-line removal so it's never silent.
            note = (_("Removed %d lines matching \"%s\".\n\n") % (
                n_removed, m.group(1).strip())) if n_removed > 1 else ""
            sess._set_buffer(buf)
            return self._wa6_reply(raw_from, from_e164,
                                   note + self._wa12_items_confirm_text(buf))

        m = re.match(r"qty\s+(.+?)\s+(\d+)\s*$", raw, re.I)
        if m:
            it, err = find_one(m.group(1))
            if err:
                return err
            it["qty"] = max(1, int(m.group(2)))
            return reshow()

        # F8: `price <item> <amt>` -- ONLY where no catalogue rate exists.
        m = re.match(r"price\s+(.+?)\s+([0-9]+(?:\.[0-9]+)?)\s*$", raw, re.I)
        if m:
            it, err = find_one(m.group(1))
            if err:
                return err
            prod = self.env["product.template"].sudo().browse(it["product_id"])
            rate, cur = self._wa12_price_lookup(prod)
            if rate is not None and rate > _WA12_PLACEHOLDER_RATE:
                return self._wa6_reply(raw_from, from_e164, _(
                    "%s has a catalogue rate (%s %.2f/day) — that's what "
                    "drafts. You can apply a discount after drafting "
                    "(`price <item> <amt>` on the draft).")
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

        # re-typed item(s): only CONFIDENT matches add here (reconciling any
        # unmatched pick they resolve). A purely-weak/no-match input returns
        # None so the caller can first try the F3 LLM translate (a conversational
        # correction must reach translate, not be swallowed as a weak item);
        # genuinely-weak re-types are surfaced by the caller's post-translate
        # fallback (_wa12_surface_unmatched). qty carried.
        adds, _weak = self._wa12_match_text_items(raw)
        if adds:
            known = {it["product_id"] for it in matched}
            for a in adds:
                if a["product_id"] not in known:
                    matched.append(a)
                    known.add(a["product_id"])
            buf["matched"] = matched
            added_names = {a["product_name"] for a in adds}
            buf["unmatched"] = [um for um in (buf.get("unmatched") or [])
                                if not (added_names
                                        & set(um.get("suggestions") or []))]
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

    def _wa12_llm_translate_items(self, text, buf):
        """F3: translate a natural q_items correction into ONE deterministic
        command (re-run through _wa12_q_items_try, which re-enforces every
        guard). None on unclear / degraded."""
        names = " · ".join((it.get("product_name") or "")
                           for it in (buf.get("matched") or [])) or "(none)"
        sys = (
            "You map a sales rep's WhatsApp message to EXACTLY ONE correction "
            "command for an UNCONFIRMED quote item list, output as plain text "
            "on one line, no quotes, no prose. Allowed: 'replace <item> = "
            "<new item>', 'remove <item>', 'qty <item> <n>', 'price <item> "
            "<amount>', 'client <name>', a date (YYYY-MM-DD), 'yes' "
            "(confirm), or 'cancel'. Current items: " + names + ". If the "
            "message is a complaint without one specific change, output "
            "exactly REPAIR. If it doesn't map to one command, output exactly "
            "UNKNOWN.")
        raw = self._wa12_llm_chat([{"role": "system", "content": sys},
                                   {"role": "user", "content": text or ""}])
        if not raw:
            return None
        cmd = raw.strip().strip('"`').splitlines()[0].strip()
        if not cmd or cmd.upper() == "UNKNOWN":
            return None
        return cmd

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
        primary = self.env["ir.config_parameter"].sudo().get_param(
            "neon_channels.whatsapp_provider_key", "groq")
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
        """The conversational quote-INITIATION fallback (hook A). Extract slots
        -> match -> CONFIRM-BEFORE-DRAFT (M1 binding: ONE confirmation message
        listing every matched line with the ENGINE rate + qty; NO provision
        until the rep says yes). Bare intent (no client/items) -> the guided
        q_client lane (M5). Returns a reply, or None to fall through (not a
        quote / LLM down)."""
        data = self._wa12_llm_extract_quote(body)
        if not data:
            return None
        client = (data.get("client") or "").strip()
        items = [it for it in (data.get("items") or []) if it.get("name")]
        prefills = {"phone": (data.get("phone") or "").strip(),
                    "email": (data.get("email") or "").strip(),
                    "contact": (data.get("contact_person") or "").strip(),
                    "address": (data.get("address") or "").strip(),
                    "event_name": (data.get("event_name") or "").strip()}
        date_txt = data.get("date") or ""
        self._wa6_audit_in(from_e164, message, "wa12-quote-ai")
        # M5 -- bare intent: enter the quote lane, never the generic Copilot.
        if not client and not items:
            self.env["neon.wa.equip.session"]._start_quote(
                from_e164, sender, "q_client",
                {"date_txt": date_txt, "prefills": prefills})
            return self._wa6_reply(raw_from, from_e164, _(
                "Sure — which client is this quote for?"))
        if not items:
            # client known, items missing -> ask for the list (same lane).
            self.env["neon.wa.equip.session"]._start_quote(
                from_e164, sender, "q_itemreq",
                {"client_txt": client, "date_txt": date_txt,
                 "prefills": prefills})
            return self._wa6_reply(raw_from, from_e164, _(
                "A quote for %s — what items? (e.g. `2x RGB LED CAN, smoke "
                "machine`)") % client)
        # match EVERY extracted item (stated prices are HINTS, never the rate).
        matched, unmatched = self._wa12_match_slot_items(items)
        return self._wa12_open_items_confirm(
            sender, client, matched, unmatched, date_txt, prefills,
            from_e164, raw_from)

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
            # M-A: pass the LLM family hint so the match is scoped to the
            # obvious family (visual/lighting/staging), never cross-category.
            hit = self._wa6_match_one(
                it.get("name") or "", category_hint=it.get("category"))
            qty = int(it.get("qty") or hit.get("qty") or 1)
            if (hit.get("status") == "matched"
                    and hit.get("confidence") in ("exact", "strong")):
                matched.append({
                    "product_id": hit["product_id"],
                    "product_name": hit["product_name"], "qty": max(1, qty),
                    "stated_price": it.get("stated_price")})
            else:
                sugg = hit.get("suggestions") or []
                if hit.get("status") == "matched" and hit.get("product_name") \
                        and hit["product_name"] not in sugg:
                    sugg = [hit["product_name"]] + sugg
                unmatched.append({"name": it.get("name") or "",
                                  "qty": max(1, qty),
                                  "stated_price": it.get("stated_price"),
                                  "suggestions": sugg[:3]})
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
        team knows; the rep replies with one)."""
        P = self.env["product.template"].sudo()
        return P.search([("is_workshop_item", "=", True)]).filtered(
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
                unmatched.append({"name": h.get("raw") or "", "qty": qty,
                                  "stated_price": None,
                                  "suggestions": sugg[:3]})
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
        buf = {"client_txt": client_txt, "partner_id": partner_id,
               "matched": matched, "unmatched": unmatched,
               "date_txt": date_txt or "", "days": 1,
               "prefills": prefills or {}}
        self.env["neon.wa.equip.session"]._start_quote(
            from_e164, sender, "q_items", buf)
        return self._wa6_reply(
            raw_from, from_e164,
            self._wa12_items_confirm_text(buf))

    def _wa12_items_confirm_text(self, buf):
        """The M1 confirmation message: every matched line with the ENGINE
        rate + qty; weak/unmatched lines listed per-item with alternatives
        (F2). Rates here are EXACTLY what the draft will carry (the F1
        echo-equals-draft binding): engine rate, or the rep price flagged
        '(rep-priced — no catalogue rate)' (F8), or 'no rate set — what
        should it be?' (which blocks until priced)."""
        PT = self.env["product.template"].sudo()
        rows = []
        for it in (buf.get("matched") or []):
            prod = PT.browse(it["product_id"])
            rate, cur = self._wa12_price_lookup(prod)
            note = ""
            if rate is not None and rate > _WA12_PLACEHOLDER_RATE:
                rate_txt = "%s %.2f/day" % (cur, rate)
                sp = it.get("stated_price")
                if sp and abs(float(sp) - rate) > 0.005:
                    note = _(" (you said %.2f — the catalogue rate applies)"
                             ) % sp
            elif it.get("rep_price"):
                rate_txt = "%s %.2f/day" % (cur, it["rep_price"])
                note = _(" (rep-priced — no catalogue rate)")
            else:
                rate_txt = _("no rate set — what should it be? "
                             "(`price <item> <amt>`)")
            rows.append("• %s ×%d @ %s%s" % (
                it["product_name"], it.get("qty") or 1, rate_txt, note))
        for um in (buf.get("unmatched") or []):
            sugg = um.get("suggestions") or []
            rows.append(_("• ⚠️ \"%s\" — not sure%s") % (
                um.get("name"),
                (_(" — did you mean: %s? (re-type the right one)")
                 % " / ".join(sugg[:3])) if sugg else
                _(" — no catalogue match (re-type or remove)")))
        head = _("I matched for *%s*%s:") % (
            buf.get("client_txt") or _("(client TBC)"),
            (_(" — %s") % buf["date_txt"]) if buf.get("date_txt") else "")
        return "%s\n%s\n\n%s" % (head, "\n".join(rows), _(
            "Reply *yes* to draft the quote, or correct me — e.g. "
            "`remove <item>` · `qty <item> 2` · `price <item> <amt>` · "
            "a date · `client <name>` · re-type an item."))

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
        # new-client intake FSM (qc_*).
        if sess.step in _WA12_CAPTURE_STEPS:
            return self._wa12_handle_capture(sess, body, from_e164, raw_from)
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
                "Reply *yes* to submit, *cancel*, *preview* (draft PDF), or "
                "edit — e.g. `price <item> <amt>` · `discount <item> 10%` · "
                "`qty <item> 2` · `days 3` · `add <item> x2` · "
                "`add custom <desc> at <amt>` · `remove <item>` · "
                "`no tax` / `with tax` · `client <name>`."))
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

    def _wa12_after_edit(self, quote, from_e164, raw_from, note):
        """Recalc + re-show the draft summary with the edit note + the prompt."""
        actor = quote.salesperson_id.id or self.env.uid
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
        matched = [it for it in items if it.get("status") == "matched"]
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
        for l in quote.line_ids:
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
            rows.append("• %s%s ×%g — %s × %dd"
                        % (tag, l.name, l.quantity, rate_txt, l.duration_days))
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
        return _("*Quote %s* for %s\n%s%s\n*Total: %s %.2f*%s") % (
            quote.name, quote.partner_id.name, date_line, "\n".join(rows),
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
