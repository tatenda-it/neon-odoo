# -*- coding: utf-8 -*-
"""B11 / WA-13 — Quote/Invoice retrieval + invoice-from-quote.

A WhatsApp FACE on the EXISTING P6.M7 invoice machinery -- no new finance
engine. Reuses the WA-12 rails (send_document, _wa12_resolve_client,
_wa12_is_approver, _wa6_can_initiate, the tight-parser -> list-then-pick ->
advisory-lock dispatch).

  Face 1 — RETRIEVAL (read-only; no money moves)
    Send quote <client|ref>     -> the quote PDF
    Send invoice <client|ref>   -> the (POSTED) invoice PDF
    Send <QUO-USD-NNNNNN>        -> quote by ref (currency infix; never bare QUO-)
    Send <INV-NNNN>             -> invoice by ref
      Quotes: sales-capable see their OWN (salesperson_id == rep, an EXPLICIT
      code domain -- sudo() bypasses the ir.rule); approver/OD see all.
      Invoices: approver/OD ONLY (explicit allow-list -- a pure sales rep or a
      jobs_manager who *can* read account.move via ACL is denied at the WA gate,
      not the data ACL). Posted only; a DRAFT (no INV- number) is refused
      honestly ("Kudzai posts it in Odoo") unless the requester can generate
      (then it re-sends the draft, §4.2).

  Face 2 — INVOICE-FROM-QUOTE (money surface; approver-gated)
    Reached from `Send invoice <client>` when no invoice exists yet and the
    requester holds the approver group: an accepted quote with a `scheduled`
    schedule -> a named TWO-PHASE confirm (stage / % / VAT-inclusive amount /
    client) -> the generate tap IS the authority gate -> action_trigger_now()
    (the approver-gated + state-guarded wrapper) creates a DRAFT account.move
    (no INV- number; Kudzai posts it in Odoo). The on_acceptance default
    (single 100%) auto-fires at accept, so a plain accepted quote has no
    scheduled stage left + already owns a draft invoice -> that path RE-SENDS
    the draft, never a dead end.

MONEY WALL: every Face-2 path is money-adjacent. Robin's sign-off OPENED the
gate (Robin + Munashe); Face 2 goes OPERATIONALLY live at the Zoho->Odoo
cutover (Robin's call) -- but ships behind the approver group + the accepted-
quote + scheduled-stage preconditions, so there is structurally nothing to
generate until real accepted quotes exist.

Intercepted in handle_inbound AFTER WA-12, BEFORE WA-6; claims ONLY its own
wa13_* taps, doc_pick/inv_pick/inv_confirm sessions, and the tight `Send …`
commands. A live inv_*/doc_pick session claims EVERY text turn (WA-6, the next
interceptor, grabs any live-session text unconditionally) -- re-prompt on
garbage, never let it reach the equip FSM.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.neon_channels.models.phone_utils import to_e164
from odoo.addons.neon_channels.models import wa_payload

_logger = logging.getLogger(__name__)

# Fresh advisory-lock namespace (NOT 5593800/900) -- first-tap-wins on the
# schedule so a double-tapped [Confirm] fires action_trigger_now exactly once.
_WA13_LOCK_NS = 5594000

# WA-13 session steps live on the shared equip-session.
_WA13_STEPS = ("doc_pick", "inv_pick", "inv_confirm")

# Terse, NON-advertising refusal (same shape as WA-12) -- never name the
# capability or teach the command.
_WA13_REFUSAL = (
    "Sorry — that isn't something I can action on your account.")

# Render actions (report_name read LIVE off the action so an instance override
# is honoured): quotes via the WA-12 report, invoices via the stock wrapper
# action (account.account_invoices -> report_name account.report_invoice* which
# t-calls account.report_invoice_document, onto which neon_finance's inherit
# applies the ZIMRA / banking blocks).
_WA13_QUOTE_ACTION = "neon_finance.action_report_neon_quote"
_WA13_INVOICE_ACTION = "account.account_invoices"


class WhatsAppMessageWA13(models.Model):
    _inherit = "neon.whatsapp.message"

    # ================================================================
    # Entitlement — EXPLICIT positive gates (review HIGH).
    # ================================================================
    @api.model
    def _wa13_can_retrieve_quote(self, user):
        """May this user retrieve a quote at all? Sales-capable OR approver/OD.
        (Own-vs-all scope is applied separately via _wa13_quote_all_scope.)"""
        return bool(user and user.id and (
            self._wa12_can_quote(user) or self._wa12_is_approver(user)))

    @api.model
    def _wa13_can_retrieve_invoice(self, user):
        """May this user retrieve an INVOICE? Approver group OR OD/superuser
        ONLY -- an EXPLICIT allow-list (never 'can_quote and not approver',
        never lean on account.move ACL to deny: a jobs_manager can read
        account.move, so the deny MUST be this WA gate)."""
        return bool(user and user.id and (
            self._wa12_is_approver(user) or self._wa6_can_initiate(user)))

    @api.model
    def _wa13_can_generate(self, user):
        """Face-2: may this user GENERATE an invoice from a quote? The approver
        GROUP -- the exact gate action_trigger_now enforces (never numeric
        uids), so the WA layer can never clear someone the model rejects."""
        return self._wa12_is_approver(user)

    @api.model
    def _wa13_quote_all_scope(self, user):
        """True if the user sees ALL quotes (approver/OD); else own-only."""
        return self._wa12_is_approver(user) or self._wa6_can_initiate(user)

    # ================================================================
    # Command parse — tight 'Send …'; a mid-sentence verb never matches.
    # ================================================================
    @api.model
    def _wa13_parse(self, body):
        """(kind, arg) where kind in ('quote','invoice') and arg is a client
        name or a QUO-/INV- ref (original case); or None if not a WA-13 command.
        Tight: a leading 'send quote '/'send invoice ' verb, or 'send <QUO-…|
        INV-…>'. A bare 'send', 'send me the address', a mid-sentence 'quote'/
        'invoice' -> None (no turn stolen)."""
        import re
        raw = (body or "").strip()
        m = re.match(r"send\s+quote\s+(.+)$", raw, re.I)
        if m:
            return "quote", m.group(1).strip()
        m = re.match(r"send\s+invoice\s+(.+)$", raw, re.I)
        if m:
            return "invoice", m.group(1).strip()
        m = re.match(r"send\s+(quo-\S.*)$", raw, re.I)
        if m:
            return "quote", m.group(1).strip()
        m = re.match(r"send\s+(inv-\S.*)$", raw, re.I)
        if m:
            return "invoice", m.group(1).strip()
        return None

    # ================================================================
    # Intercept entry (handle_inbound, after WA-12, before WA-6).
    # ================================================================
    @api.model
    def _wa13_maybe_intercept(self, message):
        """True if WA-13 handled this inbound, else None (fall through). Claims:
        a wa13_* generate-confirm tap, a doc_pick/inv_pick/inv_confirm session
        turn for this phone, or a tight `Send …` command from an entitled
        sender. Everything else -> None (WA-6 / WA-5 / Copilot run unchanged)."""
        raw_from = message.get("from")
        from_e164 = to_e164(raw_from)
        if not from_e164:
            return None

        # 1) a wa13_* HMAC tap (Face-2 [Confirm]/[Cancel]).
        tap = self._wa13_extract_tap(message)
        if tap:
            intent, sched = tap
            return self._wa13_handle_tap(
                intent, sched, from_e164, raw_from, message)

        # 2) a live WA-13 session turn for this phone. _active_for_phone has
        #    already deactivated + skipped a TTL-stale row, so a returned
        #    session is live. Claim EVERY text turn while it is an inv_*/doc_pick
        #    step (WA-6, next, grabs any live-session text unconditionally).
        sess = self.env["neon.wa.equip.session"]._active_for_phone(from_e164)
        if sess and sess.step in _WA13_STEPS:
            return self._wa13_handle_session(sess, message, from_e164, raw_from)
        if sess:
            # a live NON-WA-13 session (a WA-6 finalize, etc.) owns this
            # one-per-phone row -- never let the Send parser overrun it. Mirrors
            # the WA-12 bail-out; WA-6 (the next intercept) handles the turn.
            return None

        # 3) a tight `Send …` command.
        body = self._extract_body(message, message.get("type"))
        parsed = self._wa13_parse(body)
        if not parsed:
            return None
        kind, arg = parsed
        if not arg:
            return None
        sender = self._wa6_resolve_user(from_e164)
        if not sender:
            return None  # UNMAPPED -> silent fall-through (client lane/Copilot)
        if kind == "quote":
            if not self._wa13_can_retrieve_quote(sender):
                self._wa6_audit_in(from_e164, message, "wa13-deny")
                return self._wa6_reply(raw_from, from_e164, _(_WA13_REFUSAL))
            return self._wa13_run_quote(
                sender, arg, from_e164, raw_from, message)
        # invoice
        if not self._wa13_can_retrieve_invoice(sender):
            self._wa6_audit_in(from_e164, message, "wa13-deny")
            return self._wa6_reply(raw_from, from_e164, _(_WA13_REFUSAL))
        return self._wa13_run_invoice(
            sender, arg, from_e164, raw_from, message)

    @api.model
    def _wa13_extract_tap(self, message):
        """Return (intent, schedule_recordset) for a WA-13 interactive tap, else
        None. Only the IN-WINDOW HMAC [Confirm]/[Cancel] buttons route here (the
        retrieval / stage picks use NUMBER replies via the session)."""
        if message.get("type") != "interactive":
            return None
        payload = ((message.get("interactive") or {})
                   .get("button_reply") or {}).get("id")
        secret = self.env["ir.config_parameter"].sudo().get_param(
            "database.secret") or ""
        decoded = wa_payload.decode(secret, payload or "")
        if not decoded or not decoded[0].startswith("wa13_"):
            return None
        intent, parts = decoded
        Sched = self.env["neon.finance.invoice.schedule"].sudo()
        sched = Sched.browse(int(parts[0])) if (
            parts and parts[0].isdigit()) else Sched.browse()
        return (intent, sched)

    # ================================================================
    # Face 1 — quote retrieval.
    # ================================================================
    def _wa13_run_quote(self, sender, arg, from_e164, raw_from, message):
        self._wa6_audit_in(from_e164, message, "wa13-quote")
        quotes, err = self._wa13_resolve_quotes(arg, sender)
        if err:
            return self._wa6_reply(raw_from, from_e164, err)
        if not quotes:
            return self._wa6_reply(raw_from, from_e164, _(
                "No quote found for \"%s\".") % arg)
        if len(quotes) == 1:
            return self._wa13_send_quote_pdf(quotes, raw_from, from_e164)
        # list-then-pick (NUMBER reply via the doc_pick session).
        self.env["neon.wa.equip.session"]._start_inv(
            from_e164, sender, "doc_pick",
            {"kind": "quote", "ids": quotes.ids})
        return self._wa6_reply(raw_from, from_e164,
                               self._wa13_quote_menu(quotes))

    @api.model
    def _wa13_resolve_quotes(self, arg, user):
        """(quotes, error_or_None). A QUO- ref matches the full name (ilike);
        else resolve the client (reuse _wa12_resolve_client) then its quotes.
        Own-scope is an EXPLICIT salesperson domain for non-approver/non-OD --
        applied to BOTH the ref AND the client lookup (a ref must not bypass
        scope -- review)."""
        Q = self.env["neon.finance.quote"].sudo()
        dom = ([] if self._wa13_quote_all_scope(user)
               else [("salesperson_id", "=", user.id)])
        if (arg or "").strip().lower().startswith("quo-"):
            return Q.search([("name", "=ilike", arg.strip())] + dom), None
        partner, perr = self._wa12_resolve_client(arg)
        if perr:
            return Q.browse(), perr
        return Q.search([("partner_id", "=", partner.id)] + dom,
                        order="create_date desc"), None

    def _wa13_quote_menu(self, quotes):
        states = dict(quotes._fields["state"].selection)
        rows = [
            "%d) %s · %s %.2f · %s · %s" % (
                i + 1, q.name, q.currency_id.name or "", q.amount_total,
                states.get(q.state, q.state),
                (q.create_date and q.create_date.date()) or "")
            for i, q in enumerate(quotes)]
        return _("Which quote? Reply with the number:\n%s") % "\n".join(rows)

    def _wa13_send_quote_pdf(self, quote, raw_to, to_e164):
        report = self.env.ref(_WA13_QUOTE_ACTION, raise_if_not_found=False)
        if not report:
            return self._wa6_reply(raw_to, to_e164, _("Quote PDF unavailable."))
        try:
            pdf, _ext = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
                report.report_name, res_ids=[quote.id])
        except Exception as e:  # noqa: BLE001 -- render error must degrade soft
            _logger.warning("WA-13 quote PDF render failed for %s: %s",
                            quote.name, e)
            return self._wa6_reply(raw_to, to_e164, _(
                "Couldn't generate %s's PDF just now — try from Odoo.")
                % quote.name)
        fname = "%s.pdf" % (quote.name or "quote").replace("/", "-")
        sent = self.sudo().send_document(
            raw_to, pdf, fname, caption=_("Quote %s") % quote.name)
        self._wa6_audit_out(to_e164 or raw_to, "wa13 quote %s" % quote.name,
                            "document")
        if not sent:
            return self._wa6_reply(raw_to, to_e164, _(
                "Found %s but the PDF couldn't be sent — retrieve it from "
                "Odoo.") % quote.name)
        return True

    # ================================================================
    # Face 1 — invoice retrieval (+ the Face-2 entry).
    # ================================================================
    def _wa13_run_invoice(self, sender, arg, from_e164, raw_from, message):
        self._wa6_audit_in(from_e164, message, "wa13-invoice")
        Move = self.env["account.move"].sudo()
        can_gen = self._wa13_can_generate(sender)
        if (arg or "").strip().lower().startswith("inv-"):
            moves = Move.search([("name", "=ilike", arg.strip()),
                                 ("move_type", "=", "out_invoice")])
            partner = moves[:1].partner_id
        else:
            partner, perr = self._wa12_resolve_client(arg)
            if perr:
                return self._wa6_reply(raw_from, from_e164, perr)
            moves = Move.search([("partner_id", "=", partner.id),
                                 ("move_type", "=", "out_invoice")],
                                order="invoice_date desc, create_date desc")
        posted = moves.filtered(lambda m: m.state == "posted")
        if posted:
            if len(posted) == 1:
                return self._wa13_send_invoice_pdf(
                    posted, raw_from, from_e164)
            self.env["neon.wa.equip.session"]._start_inv(
                from_e164, sender, "doc_pick",
                {"kind": "invoice", "ids": posted.ids})
            return self._wa6_reply(raw_from, from_e164,
                                   self._wa13_invoice_menu(posted))
        # no POSTED invoice.
        drafts = moves.filtered(lambda m: m.state == "draft")
        if drafts:
            if not can_gen:
                return self._wa6_reply(raw_from, from_e164, _(
                    "%s's invoice isn't finalised yet — Kudzai posts it in "
                    "Odoo.") % (partner.name if partner else _("That client")))
            # §4.2 — re-send the already-generated DRAFT (marked draft).
            if len(drafts) == 1:
                return self._wa13_send_invoice_pdf(
                    drafts, raw_from, from_e164, draft=True)
            self.env["neon.wa.equip.session"]._start_inv(
                from_e164, sender, "doc_pick",
                {"kind": "invoice", "ids": drafts.ids})
            return self._wa6_reply(raw_from, from_e164,
                                   self._wa13_invoice_menu(drafts))
        # no invoice at all -> Face-2 offer (generator) or honest miss.
        if not can_gen:
            return self._wa6_reply(raw_from, from_e164, _(
                "No invoice found for \"%s\".") % arg)
        return self._wa13_offer_generate(sender, partner, from_e164, raw_from)

    def _wa13_invoice_menu(self, moves):
        rows = []
        for i, m in enumerate(moves):
            nm = m.name if (m.name and m.name != "/") else _("(draft)")
            rows.append("%d) %s · %s %.2f · %s · %s" % (
                i + 1, nm, m.currency_id.name or "", m.amount_total, m.state,
                m.invoice_date or (m.create_date and m.create_date.date())
                or ""))
        return _("Which invoice? Reply with the number:\n%s") % "\n".join(rows)

    def _wa13_send_invoice_pdf(self, move, raw_to, to_e164, draft=False,
                               prefix=None):
        move.ensure_one()
        action = self.env.ref(_WA13_INVOICE_ACTION, raise_if_not_found=False)
        if not action:
            return self._wa6_reply(raw_to, to_e164, _("Invoice PDF unavailable."))
        try:
            pdf, _ext = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
                action.report_name, res_ids=[move.id])
        except Exception as e:  # noqa: BLE001 -- render error must degrade soft
            _logger.warning("WA-13 invoice PDF render failed for %s: %s",
                            move.name or move.id, e)
            return self._wa6_reply(raw_to, to_e164, _(
                "Couldn't generate the invoice PDF just now — retrieve it from "
                "Odoo."))
        has_no = move.name and move.name != "/"
        label = move.name if has_no else (
            _("Draft invoice") if draft else _("Invoice"))
        fname = "%s.pdf" % str(label).replace("/", "-")
        caption = (_("DRAFT invoice — %s") % move.partner_id.name) if draft \
            else (_("Invoice %s") % label)
        sent = self.sudo().send_document(raw_to, pdf, fname, caption=caption)
        self._wa6_audit_out(to_e164 or raw_to,
                            "wa13 invoice %s" % (move.name or move.id),
                            "document")
        if not sent:
            return self._wa6_reply(raw_to, to_e164, _(
                "The invoice exists but the PDF couldn't be sent — retrieve it "
                "from Odoo."))
        if prefix:
            return self._wa6_reply(raw_to, to_e164, prefix)
        return True

    # ================================================================
    # Face 2 — invoice-from-quote (money surface; approver-gated).
    # ================================================================
    def _wa13_offer_generate(self, sender, partner, from_e164, raw_from):
        if not partner:
            return self._wa6_reply(raw_from, from_e164, _("No invoice found."))
        Q = self.env["neon.finance.quote"].sudo()
        quotes = Q.search([("partner_id", "=", partner.id),
                           ("state", "=", "accepted")])
        # only 'scheduled' stages can be triggered (the auto-fired on_acceptance
        # default is already 'invoiced' -- it is NOT offered here).
        scheds = quotes.mapped("invoice_schedule_ids").filtered(
            lambda s: s.state == "scheduled")
        if not scheds:
            if not quotes:
                return self._wa6_reply(raw_from, from_e164, _(
                    "No invoice found for %s, and no accepted quote to invoice "
                    "from.") % partner.name)
            return self._wa6_reply(raw_from, from_e164, _(
                "%s's accepted quote has no stage left to invoice.")
                % partner.name)
        if len(scheds) == 1:
            return self._wa13_present_confirm(
                sender, scheds, from_e164, raw_from)
        # multiple scheduled -> list-then-pick (NUMBER reply via inv_pick).
        self.env["neon.wa.equip.session"]._start_inv(
            from_e164, sender, "inv_pick", {"schedule_ids": scheds.ids})
        return self._wa6_reply(raw_from, from_e164,
                               self._wa13_sched_menu(scheds))

    def _wa13_sched_menu(self, scheds):
        rows = []
        for i, s in enumerate(scheds):
            stage = dict(s._fields["stage"].selection).get(s.stage, s.stage)
            rows.append("%d) %s · %s · %.0f%% · %s %.2f" % (
                i + 1, s.quote_id.name, stage, s.percentage,
                s.currency_id.name or "", s.amount))
        return _("Which stage to invoice? Reply with the number:\n%s") \
            % "\n".join(rows)

    def _wa13_present_confirm(self, sender, sched, from_e164, raw_from):
        """Two-phase confirm: open an inv_confirm session + send the HMAC
        [Confirm]/[Cancel] buttons (text yes/cancel also works). The same
        person who is offered the generate must confirm it (§2.4)."""
        sched.ensure_one()
        quote = sched.quote_id
        self.env["neon.wa.equip.session"]._start_inv(
            from_e164, sender, "inv_confirm",
            {"quote_id": quote.id, "schedule_id": sched.id})
        secret = self.env["ir.config_parameter"].sudo().get_param(
            "database.secret") or ""
        buttons = [
            {"id": wa_payload.encode(secret, "wa13_inv_confirm", sched.id),
             "title": "Confirm ✓"},
            {"id": wa_payload.encode(secret, "wa13_inv_cancel", sched.id),
             "title": "Cancel"}]
        return self._wa6_send_buttons(
            raw_from, from_e164, self._wa13_confirm_text(sched), buttons)

    def _wa13_confirm_text(self, sched):
        quote = sched.quote_id
        stage = dict(sched._fields["stage"].selection).get(
            sched.stage, sched.stage)
        return _(
            "Generate the %(stage)s invoice for %(client)s?\n"
            "Quote %(q)s · %(pct).0f%% · %(cur)s %(amt).2f (incl. VAT)\n"
            "Tap *Confirm* to create the DRAFT invoice (Kudzai posts it in "
            "Odoo), or *Cancel*.") % {
            "stage": stage, "client": quote.partner_id.name or "",
            "q": quote.name, "pct": sched.percentage,
            "cur": sched.currency_id.name or quote.currency_id.name or "",
            "amt": sched.amount}

    def _wa13_handle_tap(self, intent, sched, from_e164, raw_from, message):
        self._wa6_audit_in(from_e164, message, "wa13-tap")
        tapper = self._wa6_resolve_user(from_e164)
        if not tapper:
            return None
        # the generate tap IS the authority gate (§2.3).
        if not self._wa13_can_generate(tapper):
            return self._wa6_reply(raw_from, from_e164, _(_WA13_REFUSAL))
        sess = self.env["neon.wa.equip.session"]._active_for_phone(from_e164)
        if intent == "wa13_inv_cancel":
            if sess and sess.step in _WA13_STEPS:
                sess.sudo().write({"step": "done", "active": False})
            return self._wa6_reply(raw_from, from_e164, _(
                "Cancelled — no invoice created."))
        if intent == "wa13_inv_confirm":
            return self._wa13_do_generate(
                sched, tapper, sess, from_e164, raw_from)
        return None

    def _wa13_do_generate(self, sched, user, sess, from_e164, raw_from):
        """Fire action_trigger_now under a first-tap-wins lock. The created
        move is DRAFT (no INV- number) -- Kudzai posts it in Odoo. Idempotent on
        a double-tap (the engine guards state != 'scheduled'; we also re-send an
        already-created invoice rather than erroring)."""
        if sess and sess.step in _WA13_STEPS:
            sess.sudo().write({"step": "done", "active": False})
        if not sched or not sched.exists():
            return self._wa6_reply(raw_from, from_e164, _(
                "That schedule is no longer available."))
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)", (_WA13_LOCK_NS, sched.id))
        quote = sched.quote_id
        if quote.state != "accepted":
            return self._wa6_reply(raw_from, from_e164, _(
                "%s isn't an accepted quote — can't invoice it.")
                % (quote.name or _("That quote")))
        if sched.state != "scheduled":
            # already fired (double-tap / race) -> idempotent re-send.
            if sched.invoice_id:
                return self._wa13_send_invoice_pdf(
                    sched.invoice_id, raw_from, from_e164,
                    draft=(sched.invoice_id.state == "draft"))
            return self._wa6_reply(raw_from, from_e164, _(
                "That stage is already %s.") % sched.state)
        try:
            sched.with_user(user.id).sudo().action_trigger_now()
        except (UserError, AccessError) as e:
            return self._wa6_reply(raw_from, from_e164, str(e))
        move = sched.invoice_id
        if not move:
            return self._wa6_reply(raw_from, from_e164, _(
                "The schedule fired but no invoice surfaced — check Odoo."))
        return self._wa13_send_invoice_pdf(
            move, raw_from, from_e164, draft=True,
            prefix=_("Draft invoice created for %s — Kudzai posts it in Odoo.")
            % (quote.partner_id.name or _("the client")))

    # ================================================================
    # Session handling (doc_pick / inv_pick / inv_confirm).
    # ================================================================
    def _wa13_handle_session(self, sess, message, from_e164, raw_from):
        self._wa6_audit_in(from_e164, message, "wa13-sess")
        sess.sudo().write({"last_inbound": fields.Datetime.now()})
        sender = sess.user_id
        body = self._extract_body(message, message.get("type"))
        norm = " ".join((body or "").strip().lower().split())
        buf = sess._get_buffer()
        buf = buf if isinstance(buf, dict) else {}
        if sess.step == "doc_pick":
            return self._wa13_session_doc_pick(
                sess, buf, norm, from_e164, raw_from)
        # inv_pick / inv_confirm are Face-2 -> re-gate generation EVERY turn.
        if not (sender and sender.active and self._wa13_can_generate(sender)):
            sess.sudo().write({"active": False})
            return self._wa6_reply(raw_from, from_e164, _(_WA13_REFUSAL))
        if sess.step == "inv_pick":
            return self._wa13_session_inv_pick(
                sess, sender, buf, norm, from_e164, raw_from)
        if sess.step == "inv_confirm":
            if norm in ("cancel", "no", "stop"):
                sess.sudo().write({"step": "done", "active": False})
                return self._wa6_reply(raw_from, from_e164, _(
                    "Cancelled — no invoice created."))
            if norm in ("yes", "confirm", "y", "ok"):
                sched = self.env["neon.finance.invoice.schedule"].sudo().browse(
                    buf.get("schedule_id") or 0)
                return self._wa13_do_generate(
                    sched, sender, sess, from_e164, raw_from)
            return self._wa6_reply(raw_from, from_e164, _(
                "Reply *yes* to create the draft invoice, or *cancel*."))
        return None

    def _wa13_session_doc_pick(self, sess, buf, norm, from_e164, raw_from):
        ids = buf.get("ids") or []
        if not (norm.isdigit() and 1 <= int(norm) <= len(ids)):
            return self._wa6_reply(raw_from, from_e164, _(
                "Reply with a number from 1 to %d, or send a new command.")
                % len(ids))
        rec_id = ids[int(norm) - 1]
        sess.sudo().write({"step": "done", "active": False})
        if buf.get("kind") == "quote":
            quote = self.env["neon.finance.quote"].sudo().browse(rec_id).exists()
            if not quote:
                return self._wa6_reply(raw_from, from_e164, _(
                    "That quote is no longer available."))
            return self._wa13_send_quote_pdf(quote, raw_from, from_e164)
        move = self.env["account.move"].sudo().browse(rec_id).exists()
        if not move:
            return self._wa6_reply(raw_from, from_e164, _(
                "That invoice is no longer available."))
        return self._wa13_send_invoice_pdf(
            move, raw_from, from_e164, draft=(move.state == "draft"))

    def _wa13_session_inv_pick(self, sess, sender, buf, norm, from_e164,
                               raw_from):
        ids = buf.get("schedule_ids") or []
        if not (norm.isdigit() and 1 <= int(norm) <= len(ids)):
            return self._wa6_reply(raw_from, from_e164, _(
                "Reply with a number from 1 to %d, or send a new command.")
                % len(ids))
        sched = self.env["neon.finance.invoice.schedule"].sudo().browse(
            ids[int(norm) - 1]).exists()
        if not sched or sched.state != "scheduled":
            sess.sudo().write({"active": False})
            return self._wa6_reply(raw_from, from_e164, _(
                "That stage is no longer schedulable."))
        return self._wa13_present_confirm(sender, sched, from_e164, raw_from)
