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

# Quote session steps live on the shared equip-session (q_confirm / q_reject).
_WA12_STEPS = ("q_confirm", "q_reject")

# Fresh advisory-lock namespace (NOT 5593500/600/700/800) -- first-tap-wins on
# the approver pair so only ONE of uids 7/21 wins a concurrent Approve/Reject.
_WA12_LOCK_NS = 5593900

# Soft session TTL: a quote draft-confirm is a quick step; idle past this falls
# through to the Copilot (a later message is never swallowed as a confirm).
_WA12_TTL_HOURS = 2

# A $1 (or lower) line rate is the catalogue PLACEHOLDER, never a real price.
_WA12_PLACEHOLDER_RATE = 1.0

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
        return any(norm == c or (c.endswith(":") and norm.startswith(c))
                   for c in _WA12_QUOTE_CMDS)

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

        # 3) A tight Quote:/Price: command.
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
        rest = self._wa12_strip_cmd(body, _WA12_QUOTE_CMDS)
        client_txt, items_txt, date_txt, days = self._wa12_parse_quote(rest)
        if not client_txt or not items_txt:
            return self._wa6_reply(raw_from, from_e164, _(
                "To quote, send:  Quote: <client> — <items>, <date>"))
        partner, err = self._wa12_resolve_client(client_txt)
        if err:
            return self._wa6_reply(raw_from, from_e164, err)
        items = self._wa6_match_items(items_txt)
        matched = [it for it in items if it.get("status") == "matched"]
        if not matched:
            return self._wa6_reply(raw_from, from_e164, _(
                "Couldn't match any catalogue items in \"%s\".") % items_txt)
        event_date, placeholder = self._wa12_resolve_date(date_txt)
        currency = (sender.company_id.currency_id
                    or self.env.ref("base.USD", raise_if_not_found=False))
        if not currency:
            return self._wa6_reply(raw_from, from_e164, _(
                "Can't quote — no currency is configured. Please set one up "
                "in Odoo first."))
        # provision the draft chain + the quote (sudo inside the helper).
        # A provisioning UserError (missing TBC venue, etc.) must reply cleanly,
        # not propagate to the webhook (which would roll back the audit row +
        # re-loop via Meta re-delivery).
        try:
            quote = self.env["neon.finance.quote"]._wa12_provision_chain(
                partner, event_date, currency, sender,
                date_is_placeholder=placeholder)
        except (UserError, AccessError) as e:
            return self._wa6_reply(raw_from, from_e164, str(e))
        self._wa12_build_lines(quote, matched, days or 1)
        quote.with_user(sender.id).sudo().action_recalculate_pricing()
        unpriced = self._wa12_unpriced_lines(quote)
        # set a payment term so submit is possible (binding: required to submit).
        self._wa12_ensure_payment_term(quote, partner)
        self.env["neon.wa.equip.session"]._start_quote(
            from_e164, sender, "q_confirm", {"quote_id": quote.id})
        summary = self._wa12_draft_summary(quote, unpriced)
        if unpriced:
            # GUARD (binding 1): a placeholder/unpriced line blocks submit.
            return self._wa6_reply(raw_from, from_e164, summary + "\n\n" + _(
                "⚠️ Can't submit yet — these have no rate set: %s. "
                "Pricing isn't loaded for them."
            ) % ", ".join(unpriced))
        return self._wa6_reply(raw_from, from_e164, summary + "\n\n" + _(
            "Reply *yes* to submit for approval, or *cancel*."))

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
            return self._wa6_reply(raw_from, from_e164, _(
                "Reply *yes* to submit, *cancel*, or edit the draft."))
        buf = sess._get_buffer()
        buf = buf if isinstance(buf, dict) else {}
        quote = self.env["neon.finance.quote"].sudo().browse(
            buf.get("quote_id") or 0)
        body = self._extract_body(message, message.get("type"))
        norm = " ".join((body or "").strip().lower().split())
        if sess.step == "q_confirm":
            if norm in ("cancel", "no", "stop"):
                sess.sudo().write({"step": "done", "active": False})
                return self._wa6_reply(raw_from, from_e164, _("Quote cancelled."))
            if norm in ("yes", "submit", "y", "ok"):
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
            items = self._wa6_match_items(text)
            matched = [it for it in items if it.get("status") == "matched"]
            if not matched:
                return err(_("Couldn't match any catalogue item in \"%s\".")
                           % text)
            days = max(quote.line_ids.mapped("duration_days") or [1])
            self._wa12_build_lines(quote, matched, int(days))
            return self._wa12_after_edit(
                quote, from_e164, raw_from,
                _("Added %s") % ", ".join(it["product_name"] for it in matched))

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

        return None  # not a recognised edit command

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
        """(date, is_placeholder). A parseable upcoming date, else today as a
        flagged placeholder (commercial.job.event_date is required)."""
        from datetime import datetime
        today = fields.Date.context_today(self)
        if date_txt:
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d %b %Y",
                        "%d %B %Y", "%d %b", "%d %B"):
                try:
                    d = datetime.strptime(date_txt.strip(), fmt).date()
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
            # unit_rate is left UNSET -> the pricing ENGINE resolves it from the
            # product's equipment_category_id x the quote currency (rule +
            # bracket + day-multiplier). A category with no rule -> 'no_rule' ->
            # the no_rule guard blocks submit. The WA-12 lane NEVER reads
            # list_price, so it can never fabricate a 'manual'-priced line (the
            # guard-bypass we closed; pinned by the pwa12 guard-bypass test).
            QL.create({
                "quote_id": quote.id,
                "line_type": "equipment",
                "product_template_id": prod.id,
                "name": prod.name,
                "quantity": float(it.get("qty") or 1),
                "duration_days": int(days or 1),
                # explicit 0.0 (the column is NOT NULL); falsy -> the create()
                # gate fires the engine instead of stamping 'manual'.
                "unit_rate": 0.0,
            })

    def _wa12_unpriced_lines(self, quote):
        """Names of lines with NO real rate (binding-1 guard, line_type-aware).
        EQUIPMENT line blocks if pricing_status not_yet/no_rule/MANUAL (the lane
        can't fabricate a hidden manual rate on an engine item) or base
        unit_rate<=$1. A CUSTOM line (explicit typed rate) passes once its
        unit_rate>$1. Reads the BASE unit_rate, not the discounted effective —
        a discount (even 100%) is an explicit, approval-visible choice."""
        bad = []
        for l in quote.line_ids:
            if l.line_type == "custom":
                if (l.unit_rate or 0.0) <= _WA12_PLACEHOLDER_RATE:
                    bad.append(l.name or "(item)")
                continue
            if l.pricing_status in ("not_yet", "no_rule", "manual") \
                    or (l.unit_rate or 0.0) <= _WA12_PLACEHOLDER_RATE:
                bad.append(l.name or "(item)")
        return bad

    def _wa12_ensure_payment_term(self, quote, partner):
        """submit_for_approval requires a payment term. Prefer the partner's
        most-recent; else the first active term. Best-effort (a missing term
        surfaces at submit)."""
        if quote.payment_term_id:
            return
        PT = self.env["neon.finance.payment.term"].sudo()
        term = PT.search([("partner_id", "=", partner.id)],
                         order="create_date desc", limit=1) \
            if "partner_id" in PT._fields else PT.browse()
        if not term:
            term = PT.search([], limit=1)
        if term:
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
            tag = "[CUSTOM] " if l.line_type == "custom" else ""
            if disc:
                rate_txt = "%s %.2f → %.2f/day (disc. %s)" % (
                    cur, base, max(eff, 0.0), disc)
            else:
                rate_txt = "%s %.2f/day" % (cur, base)
            rows.append("• %s%s ×%g — %s × %dd"
                        % (tag, l.name, l.quantity, rate_txt, l.duration_days))
        # the VAT line is conditional: 'no tax' clears the line taxes -> no VAT.
        vat = _(" (incl. VAT)") if (quote.amount_tax or 0.0) else _(" (no VAT)")
        return _("*Quote %s* for %s\n%s\n*Total: %s %.2f*%s") % (
            quote.name, quote.partner_id.name, "\n".join(rows),
            cur, quote.amount_total or 0.0, vat)

    def _wa12_send_approval_ping(self, quote, requester):
        """Ping the MD/OD approver audience (uids 7 + 21), skipping the
        requester, anyone inactive, and anyone who no longer holds the approver
        group. Cold window -> the Active wa12_quote_approval TEMPLATE (static
        QR buttons; quote resolved from pending context on tap); in window ->
        interactive HMAC buttons. Returns the number actually pinged so the
        caller can surface an empty audience instead of a silent stuck quote."""
        summary = self._wa12_item_summary(quote)
        total = "%s %.2f" % (quote.currency_id.name, quote.amount_total or 0.0)
        approvers = self.env["res.users"].sudo().browse(
            [u for u in _WA12_APPROVER_UIDS if u != requester.id])
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
        names = [("%s×%g" % (l.name, l.quantity)) for l in quote.line_ids[:4]]
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
