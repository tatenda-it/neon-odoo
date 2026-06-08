# -*- coding: utf-8 -*-
"""B11 / WA-5 -- client intake lane + handoff/assignment loop.

THE FIRST CLIENT-FACING SURFACE. A stranger (an UNMAPPED WhatsApp
number) lands here from ``handle_inbound``'s ``if not bot_user`` fork.

HARD SANDBOX (the core of the Gate-1 approval):
The client lane is STRUCTURALLY tool-less -- a finite state machine over
canned strings + at most one raw ``crm.lead`` create. There is NO LLM in
this lane and NO path to the Copilot: it never calls ``run_turn`` /
``handle_tap`` / ``variant_for`` / ``tool_registry`` and never resolves a
role or lens. So "the AI never quotes a price / reaches internal data /
invokes a staff tool" is a property of the *control flow*, not a prompt
rule. Client-lane button ids are FIXED, UNSIGNED strings (no record id /
no privilege behind them -> nothing to forge; an unknown id re-greets).

HANDOFF + ASSIGNMENT LOOP (PART 2):
Triggered from the client lane, but every actor here is MAPPED staff, so
these flow through the normal Copilot tap router (``handle_tap`` ->
:meth:`_wa5_handle_assign_tap`). Reuses the WA-1 list renderer + the WA-2
two-factor tap-back discipline (HMAC payload + sender identity). The lead
``user_id`` IS the assignment state: empty == unowned == the escalation
target's backstop. Decline clears ``user_id`` and bounces to the
escalation target -- NEVER auto-reassigns, NEVER loops, NEVER unowned-
and-silent (an Odoo activity always lands so a handoff is never lost even
if WhatsApp delivery fails).
"""
import logging
import re
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.tools import html2plaintext

from . import wa_payload
from .phone_utils import to_e164

_logger = logging.getLogger(__name__)

# --- client-lane menu (fixed, UNSIGNED button ids) -------------------
_CL_QUOTE = "cl_quote"
_CL_SERVICES = "cl_services"
_CL_TEAM = "cl_team"
# numeric text fallbacks if a client's WhatsApp can't render buttons.
_CL_NUMERIC = {"1": _CL_QUOTE, "2": _CL_SERVICES, "3": _CL_TEAM}

# --- handoff triggers in free client text (AI must NEVER quote) ------
# Single tokens matched on word boundaries (so "cost" doesn't fire on
# "costume", "rate" not on "celebrate"); phrases matched as substrings.
_WA5_HANDOFF_WORDS = {
    "price", "pricing", "cost", "costs", "discount", "budget", "rate",
    "rates", "cheap", "cheaper", "expensive", "afford", "deposit",
    "bespoke", "custom", "customise", "customize", "tailor",
    "complaint", "complain", "refund", "unhappy", "disappointed", "angry",
    "manager", "human", "agent", "representative", "rep", "someone",
}
_WA5_HANDOFF_PHRASES = (
    "how much", "what does it cost", "call me", "talk to", "speak to",
    "talk to the team", "talk to someone", "speak to someone",
)

# --- escalation target ----------------------------------------------
_WA5_ESCALATION_PARAM = "neon_channels.wa5_escalation_login"
_WA5_ESCALATION_DEFAULT = "munashe@neonhiring.co.zw"
# Resolved by xmlid (stable across DBs -- prod/local ids diverge).
_WA5_ASSIGNEE_GROUP = "neon_finance.group_neon_finance_sales"
_WA5_SUPERUSER_GROUP = "neon_core.group_neon_superuser"
# The OD/owner (Robin) is excluded from the assignee LIST by IDENTITY
# (login param), NOT by the superuser group -- a superuser who is ALSO a
# sales-team member (e.g. Tatenda) must stay assignable; only the
# OD/owner is removed. Same login-param pattern as the escalation target.
_WA5_OWNER_PARAM = "neon_channels.wa5_owner_login"
_WA5_OWNER_DEFAULT = "robin@neonhiring.co.zw"

# --- WA-5.1 window-aware staff escalation ---------------------------
# Meta's customer-service window is 24h from the recipient's last INBOUND
# (an outbound never opens it). We treat the window as open only within
# this margin BELOW 24h, so we don't fire an interactive right at the
# edge that Meta then silently drops. Closed -> a UTILITY template
# re-opens the window. Design Y: template body = name + lead summary
# only (NO URLs); links ride in the in-window follow-up.
_WA5_WINDOW_HOURS = 23
_WA5_TPL_HANDOFF = "wa5_lead_handoff"      # manager (escalation + bounce)
_WA5_TPL_ASSIGNED = "wa5_lead_assigned"    # assignee
_WA5_TPL_LANG = "en_US"

# --- WA-5.2 debounced re-handoff ------------------------------------
# A returning client's follow-up on an EXISTING lead re-alerts the human
# (assignee if owned, else Munashe) at most once per this many minutes --
# kills the rapid triple-fire while still re-notifying a genuine later
# follow-up. Tunable via the ir.config_parameter below.
_WA5_RENOTIFY_PARAM = "neon_channels.wa5_renotify_minutes"
_WA5_RENOTIFY_DEFAULT = 10

# --- WA-5.3 HARD idempotency lock -----------------------------------
# Postgres transaction-advisory-lock namespace for per-lead assignment
# actions. Concurrent taps / re-entry on the SAME lead serialize so the
# idempotency checks are authoritative -> exactly one assign / decline /
# re-notify per event (kills any duplicate-message flood). Auto-released
# at commit/rollback; non-blocking (pg_try_*).
_WA5_LOCK_NS = 5593500


class WhatsAppMessageClientLane(models.Model):
    _inherit = "neon.whatsapp.message"

    # ================================================================
    # PART 1 -- CLIENT INTAKE (the sandboxed core)
    # ================================================================
    @api.model
    def _wa_client_lane(self, message, metadata, raw_from=None):
        """Entry point from ``handle_inbound`` for an UNMAPPED sender.
        Deterministic FSM -- see the module docstring for the sandbox
        guarantee. Does ALL its own audit + sends (it returns to the
        caller, not through the privileged outbound block)."""
        from_e164 = message.get("from")  # already canonical at call site
        raw_from = raw_from or from_e164
        msg_type = message.get("type", "text")

        tap_id = None
        if msg_type == "interactive":
            inter = message.get("interactive", {}) or {}
            for k in ("button_reply", "list_reply"):
                if inter.get(k):
                    tap_id = inter[k].get("id")
                    break
        body = self._extract_body(message, msg_type)

        # inbound audit (no bot_user_id == a client, by construction)
        self.sudo().create({
            "name": message.get("id") or "wa-in-%s" % from_e164,
            "direction": "inbound", "phone_number": from_e164,
            "message_body": body, "message_type": msg_type,
            "state": "received", "raw_payload": str(message)})

        sess = self.env["neon.wa.client.session"]._get_or_start(from_e164)

        # WA-5.2 returning-client follow-up: once this session already has
        # a lead, a new message appends to the chatter and DEBOUNCE-gated
        # re-notifies the human handling it (assignee if owned, else
        # re-escalate Munashe) -- at most once per wa5_renotify_minutes, so
        # a rapid triple-fire is suppressed but a genuine later follow-up
        # still alerts a human. No new lead is created. (A >24h-idle return
        # resets the session via _get_or_start -> a fresh conversation.)
        if sess.lead_id and sess.lead_id.exists():
            return self._wa5_followup(sess, sess.lead_id, body, raw_from,
                                      from_e164)

        # awaiting quote details: the NEXT text is the event details ->
        # create the lead (checked first so a "1" reply mid-capture is
        # stored as details, not treated as a menu pick).
        if (sess.step == "awaiting_quote" and msg_type == "text"
                and (body or "").strip()):
            return self._wa5_complete_quote(sess, from_e164, raw_from, body)

        # explicit button taps (or numeric fallbacks)
        choice = tap_id or _CL_NUMERIC.get((body or "").strip())
        if choice == _CL_SERVICES:
            return self._wa5_send_client(
                raw_from, from_e164, self._wa5_services_text())
        if choice == _CL_TEAM:
            return self._wa5_handoff(
                sess, from_e164, raw_from, body, reason="talk_to_team")
        if choice == _CL_QUOTE:
            sess.sudo().write({"step": "awaiting_quote"})
            return self._wa5_send_client(
                raw_from, from_e164, self._wa5_quote_prompt_text())

        # free text that trips a handoff trigger (pricing / bespoke /
        # complaint / "talk to the team") -> straight to a human.
        if msg_type == "text" and self._wa5_is_handoff(body):
            return self._wa5_handoff(
                sess, from_e164, raw_from, body, reason="keyword")

        # default: (re)greet with the 3-button menu
        return self._wa5_greet(raw_from, from_e164)

    # ---- canned copy (NO pricing, ever) ----------------------------
    @api.model
    def _wa5_greet(self, raw_from, from_e164):
        body = ("\U0001F44B Welcome to Neon Events Elements -- premium event "
                "production, decor & AV in Zimbabwe. How can we help today?")
        buttons = [{"id": _CL_QUOTE, "title": "Request a quote"},
                   {"id": _CL_SERVICES, "title": "Our services"},
                   {"id": _CL_TEAM, "title": "Talk to the team"}]
        ok = self.sudo().send_buttons(raw_from, body, buttons)
        if not ok:
            body += ("\nReply 1) Request a quote  2) Our services  "
                     "3) Talk to the team")
            self.sudo().send_message(raw_from, body)
        self._wa5_audit_out(from_e164, body, "interactive" if ok else "text")
        return True

    @api.model
    def _wa5_services_text(self):
        return ("Neon Events Elements delivers premium event production "
                "across Zimbabwe:\n"
                "• Corporate dinners, product launches & conferences\n"
                "• Weddings & high-end social events\n"
                "• Government & NGO functions\n"
                "• Decor & staging, AV / sound / lighting, full event "
                "management\n\n"
                "Tell us about your event and the team will tailor a "
                "proposal -- send your event type, date and venue, or reply "
                "to request a quote.")

    @api.model
    def _wa5_quote_prompt_text(self):
        return ("Great -- we'd love to help. Please send your event TYPE, "
                "DATE and VENUE/AREA in one message (e.g. \"Corporate "
                "dinner, 14 August, Harare\") and the team will prepare a "
                "quote for you.")

    # ---- terminal client actions (both -> a lead + notify Munashe) --
    @api.model
    def _wa5_complete_quote(self, sess, from_e164, raw_from, details):
        lead = self._wa5_create_client_lead(from_e164, details, "quote")
        # WA-5.2: stamp last_notify at the initial escalation so an
        # immediate rapid follow-up is debounced.
        sess.sudo().write({"step": "done", "lead_id": lead.id,
                           "last_notify": fields.Datetime.now()})
        self._wa5_send_client(
            raw_from, from_e164,
            "Thank you -- we've received your enquiry and a member of the "
            "Neon Events team will be in touch shortly to discuss your "
            "event and prepare a quote.")
        self._wa5_notify_escalation(lead, from_e164)
        return True

    @api.model
    def _wa5_handoff(self, sess, from_e164, raw_from, client_msg, reason):
        lead = sess.lead_id if sess.lead_id else self._wa5_create_client_lead(
            from_e164, client_msg or "(client asked to speak to the team)",
            "handoff")
        sess.sudo().write({"step": "done", "lead_id": lead.id,
                           "last_notify": fields.Datetime.now()})
        self._wa5_send_client(
            raw_from, from_e164,
            "Thanks for reaching out -- a member of the Neon Events team "
            "will contact you shortly to assist.")
        self._wa5_notify_escalation(lead, from_e164)
        return True

    @api.model
    def _wa5_renotify_minutes(self):
        val = self.env["ir.config_parameter"].sudo().get_param(
            _WA5_RENOTIFY_PARAM, _WA5_RENOTIFY_DEFAULT)
        try:
            return max(0, int(val))
        except (TypeError, ValueError):
            return _WA5_RENOTIFY_DEFAULT

    @api.model
    def _wa5_followup(self, sess, lead, body, raw_from, from_e164):
        """WA-5.2: a returning client's message on an EXISTING lead.
        ALWAYS append to the chatter; DEBOUNCE-gated re-notify of the human
        handling it -- assignee if the lead is owned, else re-escalate
        Munashe -- at most once per wa5_renotify_minutes (kills the rapid
        triple-fire, still alerts a genuine later follow-up). Honest ack:
        only promise contact when a human was (re)notified or already owns
        the lead."""
        self._wa5_append_client_msg(lead, body)
        now = fields.Datetime.now()
        mins = self._wa5_renotify_minutes()
        stale = (not sess.last_notify) or (
            now - sess.last_notify >= timedelta(minutes=mins))
        notified = False
        # WA-5.3 HARD lock: only ONE concurrent follow-up re-notifies (no
        # duplicate ping if two messages land at once).
        if stale:
            if self._wa5_try_lock(lead):
                if lead.user_id:
                    self._wa5_notify_followup_assignee(
                        lead, lead.user_id, body)
                else:
                    self._wa5_notify_escalation(
                        lead, lead.phone or from_e164)
                sess.sudo().write({"last_notify": now})
                notified = True
            else:
                # lock contention (a concurrent follow-up is handling it):
                # the message is already on the chatter; log so ops has a
                # signal rather than a silent skip.
                _logger.warning(
                    "WA-5 followup lock contention on lead %s -- re-notify "
                    "skipped this turn (concurrent handler); message is on "
                    "the chatter.", lead.id)
        if notified or lead.user_id:
            ack = ("Thanks -- we've flagged your follow-up to the team and "
                   "someone will be in touch shortly.")
        else:
            # unowned + debounced: a human was alerted recently; don't
            # imply fresh contact that isn't being triggered this turn.
            ack = "Thanks -- we've added that to your enquiry."
        return self._wa5_send_client(raw_from, from_e164, ack)

    @api.model
    def _wa5_notify_followup_assignee(self, lead, assignee, client_msg):
        """WA-5.2: ping the ASSIGNEE that their client sent a follow-up
        (window-aware; re-engage via wa5_lead_assigned when cold; always
        the Odoo activity). NOT sent to Munashe -- the assignee owns it."""
        bu = self.env["neon.bot.user"].sudo().search(
            [("user_id", "=", assignee.id), ("active", "=", True)], limit=1)
        client = lead.phone or ""
        snippet = " ".join((client_msg or "").split())[:160]
        summary = self._wa5_lead_summary(lead)
        # WA-5.3: same THREE reply-buttons as the assignment notify; the
        # follow-up snippet sits in the body, the links behind the buttons.
        body = (
            "\U0001F4E9 Your WhatsApp client sent a follow-up:\n\"%s\"\n%s\n"
            "Client: %s\n\nTap an option below."
            % (snippet, summary, client))
        decline_payload = self._wa5_payload(
            "assignee_decline", lead.id, assignee.id)
        interactive = {
            "kind": "buttons", "body": body[:1024],
            "buttons": self._wa5_assignee_buttons(lead, assignee)}
        self._wa5_staff_notify(
            bu, self._wa5_first_name(assignee), interactive, body,
            _WA5_TPL_ASSIGNED, "follow-up: " + (snippet or summary),
            decline_payload, lead, _("Client follow-up -- respond"), assignee)

    @api.model
    def _wa5_is_handoff(self, text):
        low = (text or "").lower()
        if any(ph in low for ph in _WA5_HANDOFF_PHRASES):
            return True
        words = set(re.findall(r"[a-z]+", low))
        return bool(words & _WA5_HANDOFF_WORDS)

    # ---- the ONE write the client lane performs --------------------
    @api.model
    def _wa5_create_client_lead(self, from_e164, raw_text, kind):
        """Create ONE raw ``crm.lead`` (sudo) per the locked contract:
        type=lead, stage=lowest-sequence, tag/source/medium=WhatsApp,
        NO contact_name / NO partner_id (humans create the contact at
        quote time), user_id empty (unowned -> escalation backstop)."""
        Lead = self.env["crm.lead"].sudo()
        stage = self.env["crm.stage"].sudo().search(
            [], order="sequence, id", limit=1)
        tag = self.env.ref(
            "neon_channels.crm_tag_whatsapp", raise_if_not_found=False)
        src = self.env.ref(
            "neon_channels.utm_source_whatsapp", raise_if_not_found=False)
        med = self.env.ref(
            "neon_channels.utm_medium_whatsapp", raise_if_not_found=False)
        vals = {
            "type": "lead",
            "name": "WhatsApp enquiry (%s)" % from_e164,
            "phone": from_e164,
            "description": raw_text,
            # ⚠️ crm.lead.user_id DEFAULTS to the creating user; we create
            # via sudo, so without this the lead would be owned by the
            # sudo user. Force EMPTY -> unowned == the escalation backstop
            # (the assignment loop is the only thing that sets user_id).
            "user_id": False,
        }
        if stage:
            vals["stage_id"] = stage.id
        if tag:
            vals["tag_ids"] = [(4, tag.id)]
        if src:
            vals["source_id"] = src.id
        if med:
            vals["medium_id"] = med.id
        deadline = self._wa5_parse_date(raw_text)
        if deadline:
            vals["date_deadline"] = deadline
        lead = Lead.create(vals)
        # mirror the intake thread to the lead's chatter. Markup keeps the
        # <b>/<br/> literal and AUTO-ESCAPES the client text -- a plain str
        # body gets wholesale-escaped + <p>-wrapped by message_post (the
        # &lt;b&gt; leak seen since WA-5).
        try:
            lead.message_post(
                body=Markup("<b>WhatsApp client intake (%s):</b><br/>%s")
                % (from_e164, raw_text or ""),
                message_type="comment", subtype_xmlid="mail.mt_note")
        except Exception as e:  # noqa: BLE001 -- chatter must not break intake
            _logger.warning("WA-5 lead chatter failed (%s): %s", lead.id, e)
        return lead

    @api.model
    def _wa5_parse_date(self, text):
        """Best-effort dd/mm/yyyy (or dd-mm-yy) parse; None if not
        recognisable (spec: date_deadline only "if recognisable")."""
        from datetime import date
        m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", text or "")
        if not m:
            return None
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d)
        except ValueError:
            return None

    # ================================================================
    # Shared WA-5 helpers (used by the lane AND the assignment taps)
    # ================================================================
    @api.model
    def _wa5_secret(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "database.secret") or ""

    @api.model
    def _wa5_payload(self, intent, *parts):
        return wa_payload.encode(self._wa5_secret(), intent, *parts)

    @api.model
    def _wa5_safe(self, text):
        """Structured-free reply dict (the shape ``handle_inbound``
        consumes for a tap result)."""
        return {"text": text, "cta_url": None, "interactive": None,
                "text_fallback": text, "error": None, "provider_key": None}

    @api.model
    def _wa5_wame_link(self, phone):
        digits = "".join(ch for ch in (phone or "") if ch.isdigit())
        return ("https://wa.me/" + digits) if digits else ""

    @api.model
    def _wa5_odoo_lead_link(self, lead):
        base = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url") or ""
        return "%s/web#id=%s&model=crm.lead&view_type=form" % (base, lead.id)

    @api.model
    def _wa5_first_name(self, user):
        return ((user.name or user.login or "there").split() or ["there"])[0]

    @api.model
    def _wa5_lead_summary(self, lead):
        """A clean PLAIN-TEXT one-liner for WhatsApp bodies + template
        {{2}}. crm.lead.description is an Html field, so strip tags
        (html2plaintext) and collapse whitespace -- never leak raw <p>."""
        desc = " ".join(html2plaintext(lead.description or "").split())
        return (desc[:120] or lead.name or "WhatsApp enquiry")

    @api.model
    def _wa5_window_open(self, phone_e164):
        """WA-5.1: True iff the recipient has an INBOUND message within the
        last ~23h -> Meta's 24h customer-service window is open and a
        free-form interactive will deliver. Only an inbound opens it; an
        outbound (template/message) never does."""
        if not phone_e164:
            return False
        cutoff = fields.Datetime.now() - timedelta(hours=_WA5_WINDOW_HOURS)
        return bool(self.env["neon.whatsapp.message"].sudo().search_count([
            ("phone_number", "=", phone_e164),
            ("direction", "=", "inbound"),
            ("create_date", ">=", cutoff)]))

    @api.model
    def _wa5_staff_notify(self, recipient_bu, recipient_name, interactive,
                          body, template_name, template_summary,
                          button_payload, lead, activity_summary,
                          activity_user):
        """WA-5.1 window-aware staff notify -- the ONE primitive behind all
        three notify paths:
          * window OPEN  -> the rich free-form interactive (today's path);
          * window CLOSED -> a UTILITY template (Design Y: name + summary +
            a quick-reply carrying ``button_payload``) that RE-OPENS the
            window so the tap-back + in-window follow-up then work;
          * ALWAYS -> the human-routed Odoo activity (D4 'never lost').
        Audit records the ACTUAL path (interactive vs template) and result
        -- no more blanket state='sent'."""
        partner = recipient_bu.user_id.partner_id if recipient_bu else None
        if recipient_bu and self._wa5_window_open(recipient_bu.phone_number):
            # open window: free-form interactive (best-effort -> never
            # skip the activity fallback).
            try:
                path = self.sudo().send_interactive_or_text(
                    recipient_bu.phone_number, interactive, body)
                self._wa5_audit_out(
                    recipient_bu.phone_number, body, path or "interactive",
                    lead=lead, state="sent")
            except Exception as e:  # noqa: BLE001
                _logger.warning(
                    "WA-5 staff notify (interactive) failed lead %s: %s",
                    lead.id, e)
        elif recipient_bu:
            # closed window: a template re-opens it. send_template honours
            # res.partner.wa_opt_out + writes its OWN (truthful) audit row.
            try:
                res = self.sudo().send_template(
                    recipient_bu.phone_number, template_name,
                    language=_WA5_TPL_LANG,
                    body_params=[recipient_name, template_summary],
                    quick_reply_payloads=[button_payload],
                    recipient_partner=partner,
                    audit_body="[%s] %s" % (template_name, template_summary))
                # capture the real result (no blanket success) -- a
                # suppressed (opt-out) or rejected template is visible; the
                # Odoo activity below is the guaranteed fallback either way.
                if not (res or {}).get("ok"):
                    _logger.warning(
                        "WA-5 staff template %s NOT delivered to %s (%s) -- "
                        "Odoo activity is the fallback (lead %s).",
                        template_name, recipient_bu.phone_number,
                        (res or {}).get("reason"), lead.id)
            except Exception as e:  # noqa: BLE001
                _logger.warning(
                    "WA-5 staff notify (template) failed lead %s: %s",
                    lead.id, e)
        # D4: the activity ALWAYS lands on a human, regardless of channel.
        self._wa5_activity(lead, activity_user, activity_summary, body)

    @api.model
    def _wa5_append_client_msg(self, lead, body):
        """WA-5.0: a follow-up client message on an already-escalated lead
        -> append to the chatter (escaped) so the team/assignee see it,
        WITHOUT re-firing the escalation."""
        try:
            lead.sudo().message_post(
                body=Markup("<b>WhatsApp client follow-up:</b><br/>%s")
                % (body or ""),
                message_type="comment", subtype_xmlid="mail.mt_note")
        except Exception as e:  # noqa: BLE001 -- chatter must not break intake
            _logger.warning(
                "WA-5 follow-up chatter failed (%s): %s", lead.id, e)

    @api.model
    def _wa5_escalation_botuser(self):
        """The single backstop. Resolved by LOGIN via config param
        (default Munashe) -> her active bot.user. Empty recordset if the
        login/mapping is missing (the activity fallback still fires)."""
        login = self.env["ir.config_parameter"].sudo().get_param(
            _WA5_ESCALATION_PARAM, _WA5_ESCALATION_DEFAULT)
        user = self.env["res.users"].sudo().search(
            [("login", "=", login)], limit=1)
        if not user:
            _logger.warning("WA-5: escalation login %s not found", login)
            return self.env["neon.bot.user"].sudo()
        bu = self.env["neon.bot.user"].sudo().search(
            [("user_id", "=", user.id), ("active", "=", True)], limit=1)
        if not bu:
            _logger.warning(
                "WA-5: escalation user %s has no active bot.user", login)
        return bu

    @api.model
    def _wa5_owner_user(self):
        """The OD/owner (Robin), resolved by LOGIN param. Excluded from
        the assignee list BY IDENTITY (not by the superuser group) so a
        superuser who is also a salesperson (Tatenda) stays assignable.
        Empty recordset if the login is unset/missing."""
        login = self.env["ir.config_parameter"].sudo().get_param(
            _WA5_OWNER_PARAM, _WA5_OWNER_DEFAULT)
        if not login:
            return self.env["res.users"].sudo()
        return self.env["res.users"].sudo().search(
            [("login", "=", login)], limit=1)

    @api.model
    def _wa5_assignee_users(self):
        """group_neon_finance_sales ∩ active bot.user, EXCLUDING the
        escalation target (Munashe) and the OD/owner (Robin) -- both BY
        IDENTITY (login params), NOT by the superuser group. A superuser
        who is also a sales-team member (e.g. Tatenda) therefore STAYS
        assignable. Self-maintaining; nobody hardcoded by id."""
        grp = self.env.ref(_WA5_ASSIGNEE_GROUP, raise_if_not_found=False)
        if not grp:
            _logger.warning(
                "WA-5: assignee group %s missing -- empty assignee list",
                _WA5_ASSIGNEE_GROUP)
            return self.env["res.users"].sudo()
        esc = self._wa5_escalation_botuser()
        esc_uid = esc.user_id.id if esc else 0
        owner = self._wa5_owner_user()
        owner_uid = owner.id if owner else 0
        mapped_uids = set(self.env["neon.bot.user"].sudo().search(
            [("active", "=", True)]).mapped("user_id").ids)
        out = self.env["res.users"].sudo()
        for u in grp.sudo().users:
            if u.id not in mapped_uids:
                continue
            # exclude the assigner (Munashe) + the OD/owner (Robin) by
            # identity -- a superuser-salesperson (Tatenda) is NOT dropped.
            if u.id in (esc_uid, owner_uid):
                continue
            out |= u
        # deterministic order so the (Meta-capped) list is stable, not
        # insertion-order roulette.
        return out.sorted(key=lambda u: (u.name or u.login or "").lower())

    @api.model
    def _wa5_can_assign(self, user):
        """D6: authorised-to-assign = Neon Superuser OR the escalation
        target."""
        if user.has_group(_WA5_SUPERUSER_GROUP):
            return True
        esc = self._wa5_escalation_botuser()
        return bool(esc and esc.user_id.id == user.id)

    @api.model
    def _wa5_fallback_human(self):
        """A guaranteed HUMAN recipient for the activity fallback when the
        escalation target can't be resolved. The D4 'never lost' promise
        must reach a person, not the sudo/system user (handle_inbound runs
        sudo -> env.uid is OdooBot). Prefer a Neon Superuser (MD/manager),
        else any assignable salesperson."""
        root_id = self.env.ref("base.user_root").id
        su = self.env.ref(_WA5_SUPERUSER_GROUP, raise_if_not_found=False)
        if su:
            human = su.sudo().users.filtered(
                lambda u: u.active and not u.share and u.id != root_id)
            if human:
                return human[0]
        sales = self._wa5_assignee_users()
        if sales:
            return sales[0]
        owner = self._wa5_owner_user()
        if owner and owner.active and not owner.share \
                and owner.id != root_id:
            return owner
        # ULTIMATE backstop: ANY real internal user, so the D4 activity
        # never fails to land on a human (only impossible on a DB with no
        # internal users at all). Beats a silent no-op on a misconfigured
        # escalation target + empty superuser/sales sets.
        return self.env["res.users"].sudo().search(
            [("active", "=", True), ("share", "=", False),
             ("id", "!=", root_id)], limit=1)

    @api.model
    def _wa5_activity(self, lead, user, summary, note):
        """Guaranteed-delivery fallback (D4): an Odoo to-do on the lead,
        so a handoff/assignment is never lost if WhatsApp send fails. The
        recipient MUST be a human -- if the preferred user is missing or
        resolves to OdooBot/system (the sudo env.uid), route to a human
        fallback and log loudly rather than landing a silent activity on
        the system account."""
        try:
            root_id = self.env.ref("base.user_root").id
            target = user if (user and user.id and user.id != root_id) \
                else None
            if not target:
                target = self._wa5_fallback_human()
            if not target:
                _logger.error(
                    "WA-5: NO human recipient for lead %s activity -- check "
                    "escalation config (%s)", lead.id, _WA5_ESCALATION_PARAM)
                return
            lead.sudo().activity_schedule(
                "mail.mail_activity_data_todo",
                summary=summary, note=note, user_id=target.id)
        except Exception as e:  # noqa: BLE001 -- never break the flow
            _logger.warning("WA-5 activity skipped (lead %s): %s", lead.id, e)

    @api.model
    def _wa5_send_client(self, raw_from, from_e164, text):
        self.sudo().send_message(raw_from, text)
        self._wa5_audit_out(from_e164, text, "text")
        return True

    @api.model
    def _wa5_audit_out(self, phone, body, mtype="text", lead=None,
                       state="sent"):
        self.sudo().create({
            "name": "wa-out-%s" % phone, "direction": "outbound",
            "phone_number": phone, "message_body": body,
            "message_type": mtype, "state": state,
            "lead_id": lead.id if lead else False})

    # ================================================================
    # PART 2 -- HANDOFF NOTIFY + ASSIGNMENT LOOP (mapped staff)
    # ================================================================
    @api.model
    def _wa5_notify_escalation(self, lead, client_e164):
        """Notify the escalation target (window-aware -- WA-5.1). WA-5.4
        (FIX 3a): clean SHORT body + the single Assign button -- the raw
        wa.me/Odoo URLs are removed (the manager is assigning, not chatting
        the client; the cluttered raw links made the button look absent).
        The cold-window template likewise carries only name + summary +
        the Assign quick-reply."""
        esc = self._wa5_escalation_botuser()
        summary = self._wa5_lead_summary(lead)
        body = (
            "\U0001F195 New WhatsApp lead needs an owner:\n%s\nClient: %s\n\n"
            "Tap below to assign a salesperson."
            % (summary, client_e164))
        payload = self._wa5_payload("assign_open", lead.id)
        interactive = {
            "kind": "buttons", "body": body[:1024],
            "buttons": [{"id": payload,
                         "title": "\U0001F465 Assign salesperson"}]}
        self._wa5_staff_notify(
            esc, self._wa5_first_name(esc.user_id) if esc else "team",
            interactive, body, _WA5_TPL_HANDOFF, summary, payload, lead,
            _("New WhatsApp lead -- assign a salesperson"),
            esc.user_id if esc else None)
        return True

    @api.model
    def _wa5_try_lock(self, lead):
        """WA-5.3 HARD idempotency: a Postgres transaction-advisory lock
        keyed on the lead. Concurrent taps / re-entry on the same lead
        SERIALIZE so the idempotency checks below are authoritative ->
        exactly one assign / decline / re-notify per event. Non-blocking
        (returns False if another live transaction holds it); auto-released
        at commit/rollback. Within ONE request the same session re-acquires
        freely -- the protection is across concurrent transactions."""
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            (_WA5_LOCK_NS, int(lead.id)))
        return bool(self.env.cr.fetchone()[0])

    @api.model
    def _wa5_set_owner(self, lead, user_id):
        """WA-5.4: write crm.lead.user_id WITHOUT firing Odoo's native CRM
        assignment notification.

        ROOT CAUSE it fixes: that notification, under the auth='public'
        webhook env, reads crm.lead as the PUBLIC user at the deferred
        flush -> AccessError -> HTTP 403 -> the whole request ROLLS BACK,
        so user_id never persists (each assign_pick re-assigns + re-acks,
        Meta retries on 403; the later decline reads None -> 'already
        declined'). WA-5 already posts its own chatter + activity + the
        WhatsApp notify, so the native email/inbox is redundant.
        tracking_disable kills the field-tracking message; the other two
        keys kill the auto-subscribe ping + the create log."""
        lead.sudo().with_context(
            tracking_disable=True,
            mail_auto_subscribe_no_notify=True,
            mail_create_nolog=True,
        ).write({"user_id": user_id})

    @api.model
    def _wa5_assignee_buttons(self, lead, assignee):
        """WA-5.3: the assignee's THREE reply-buttons -- Chat / Open in
        Odoo / I'm not free. Chat & Odoo are reply-buttons that, on tap,
        make the bot REPLY with the wa.me / Odoo deep-link (a reply-button
        can't itself BE a URL -- D3). Decline carries the user_id for the
        two-factor check."""
        return [
            {"id": self._wa5_payload("assignee_chat", lead.id),
             "title": "\U0001F4AC Chat with client"},
            {"id": self._wa5_payload("assignee_odoo", lead.id),
             "title": "\U0001F4CD Open in Odoo"},
            {"id": self._wa5_payload("assignee_decline", lead.id, assignee.id),
             "title": "\U0001F645 I'm not free"},
        ]

    def _wa5_handle_assign_tap(self, bot_user, intent, parts, reply_title=None):
        """Router for the assignment-loop taps, delegated from the
        Copilot ``handle_tap``. Returns the tap result dict (the ack to
        the tapper); side-notifications to other parties happen inline."""
        if intent == "assign_open":
            return self._wa5_tap_assign_open(bot_user, parts)
        if intent == "assign_pick":
            return self._wa5_tap_assign_pick(bot_user, parts)
        if intent == "assignee_decline":
            return self._wa5_tap_assignee_decline(bot_user, parts)
        if intent == "assignee_chat":
            return self._wa5_tap_assignee_link(bot_user, parts, "chat")
        if intent == "assignee_odoo":
            return self._wa5_tap_assignee_link(bot_user, parts, "odoo")
        return self._wa5_safe(_("I couldn't route that selection."))

    @api.model
    def _wa5_tap_assignee_link(self, bot_user, parts, kind):
        """WA-5.3: a Chat / Open-in-Odoo button tap -> reply to the tapper
        with the wa.me / Odoo deep-link (the link the reply-button can't
        carry directly). Read-only; no state change, no lock needed."""
        lead = self._wa5_lead_from_parts(parts)
        if not lead:
            return self._wa5_safe(_("That lead is no longer available."))
        if kind == "chat":
            link = self._wa5_wame_link(lead.phone or "")
            if not link:
                return self._wa5_safe(
                    _("No client number is on this lead."))
            return self._wa5_safe(
                _("\U0001F4AC Chat with the client here:\n%s") % link)
        return self._wa5_safe(
            _("\U0001F4CD Open the lead in Odoo:\n%s")
            % self._wa5_odoo_lead_link(lead))

    @api.model
    def _wa5_tap_assign_open(self, bot_user, parts):
        if not self._wa5_can_assign(bot_user.user_id):
            return self._wa5_safe(_("Only a manager can assign this lead."))
        lead = self._wa5_lead_from_parts(parts)
        if not lead:
            return self._wa5_safe(
                _("I couldn't find that lead -- it may have changed."))
        users = self._wa5_assignee_users()
        if not users:
            return self._wa5_safe(
                _("No mapped salespeople are available to assign right now "
                  "-- please assign in Odoo: %s")
                % self._wa5_odoo_lead_link(lead))
        # Meta lists cap at 10 rows. No SILENT truncation: log it and say
        # so in the body; the text fallback still lists everyone.
        truncated = len(users) > 10
        if truncated:
            _logger.info(
                "WA-5 assignee list: %d salespeople, showing first 10 "
                "(assign the rest in Odoo) -- no silent truncation.",
                len(users))
        shown = users[:10]
        rows = [{"id": self._wa5_payload("assign_pick", lead.id, u.id),
                 "title": (u.name or u.login)[:24], "description": ""}
                for u in shown]
        body = _("Assign \"%s\" to:") % lead.name
        if truncated:
            body += _(" (showing first 10 of %d -- rest in Odoo)") % len(users)
        interactive = {
            "kind": "list", "body": body[:1024], "button_text": "Choose",
            "sections": [{"title": "Salespeople", "rows": rows}]}
        fallback = body + "\n" + "\n".join(
            "- " + (u.name or u.login) for u in users)
        return {"text": body, "cta_url": None, "interactive": interactive,
                "text_fallback": fallback, "error": None,
                "provider_key": None}

    @api.model
    def _wa5_tap_assign_pick(self, bot_user, parts):
        if not self._wa5_can_assign(bot_user.user_id):
            return self._wa5_safe(_("Only a manager can assign this lead."))
        lead = self._wa5_lead_from_parts(parts)
        assignee = self._wa5_user_from_part(parts, 1)
        if not lead or not assignee:
            return self._wa5_safe(_("That assignment is no longer valid."))
        if assignee not in self._wa5_assignee_users():
            return self._wa5_safe(
                _("That person isn't an assignable salesperson."))
        # WA-5.3 HARD lock: serialize concurrent taps on this lead so the
        # idempotency check below is authoritative (exactly one assign +
        # one notify, even under a rapid double-tap / webhook re-entry).
        if not self._wa5_try_lock(lead):
            return self._wa5_safe(_("That's being processed -- one moment."))
        # idempotency: a repeat tap of the SAME pick is a no-op ack (no
        # second write, no second notify) -- killed the 5x churn.
        if lead.sudo().user_id.id == assignee.id:
            return self._wa5_safe(
                _("%s already has this lead.")
                % (assignee.name or assignee.login))
        self._wa5_set_owner(lead, assignee.id)  # WA-5.4: no native notify
        self._wa5_notify_assignee(lead, assignee)
        return self._wa5_safe(
            _("✅ Assigned to %s. They've been notified.")
            % (assignee.name or assignee.login))

    @api.model
    def _wa5_notify_assignee(self, lead, assignee):
        """Notify the chosen salesperson (window-aware -- WA-5.1). WA-5.3:
        in-window message is THREE reply-buttons (Chat / Open in Odoo /
        I'm not free); the links ride behind the Chat/Odoo buttons, not in
        the body. The cold-window template (1 quick-reply, Meta-approved)
        carries the decline payload."""
        bu = self.env["neon.bot.user"].sudo().search(
            [("user_id", "=", assignee.id), ("active", "=", True)], limit=1)
        client = lead.phone or ""
        summary = self._wa5_lead_summary(lead)
        body = (
            "\U0001F4E9 You've been assigned a WhatsApp lead:\n%s\n"
            "Client: %s\n\nTap an option below."
            % (summary, client))
        interactive = {
            "kind": "buttons", "body": body[:1024],
            "buttons": self._wa5_assignee_buttons(lead, assignee)}
        # the template (cold window) keeps its single approved quick-reply.
        decline_payload = self._wa5_payload(
            "assignee_decline", lead.id, assignee.id)
        self._wa5_staff_notify(
            bu, self._wa5_first_name(assignee), interactive, body,
            _WA5_TPL_ASSIGNED, summary, decline_payload, lead,
            _("New WhatsApp lead assigned to you"), assignee)

    @api.model
    def _wa5_tap_assignee_decline(self, bot_user, parts):
        lead = self._wa5_lead_from_parts(parts)
        assignee = self._wa5_user_from_part(parts, 1)
        if not lead or not assignee:
            return self._wa5_safe(_("That assignment is no longer valid."))
        # two-factor: HMAC proved the payload; now the SENDER (resolved
        # from their phone -> bot_user.user_id) must BE the assigned user.
        if bot_user.user_id.id != assignee.id:
            _logger.warning(
                "WA-5 decline identity mismatch: sender %s != assignee %s "
                "(lead %s)", bot_user.user_id.id, assignee.id, lead.id)
            return self._wa5_safe(
                _("This assignment isn't linked to your number."))
        # WA-5.3 HARD lock: serialize concurrent declines so the FIRST tap
        # alone runs the unassign + bounce (Munashe notified ONCE); a true
        # double-tap can never duplicate.
        if not self._wa5_try_lock(lead):
            return self._wa5_safe(_("That's being processed -- one moment."))
        # WA-5.0 split-states (the prod bug: all three collapsed into a
        # wrong "already reassigned"):
        current = lead.sudo().user_id
        if not current:
            # already unowned -> they (or a double-tap) already declined.
            return self._wa5_safe(
                _("You've already declined this -- it's back with the team."))
        if current.id != assignee.id:
            # a DIFFERENT user now holds it.
            return self._wa5_safe(
                _("That lead has been reassigned to someone else."))
        # the tapper IS the current owner -> decline, clear, bounce.
        self._wa5_set_owner(lead, False)  # WA-5.4: no native notify; unowned
        self._wa5_bounce_to_escalation(lead, assignee)
        return self._wa5_safe(
            _("You've declined -- we've sent it back to the team."))

    @api.model
    def _wa5_bounce_to_escalation(self, lead, declined_by):
        """ALWAYS back to Munashe (never auto-reassign, never unowned-
        and-silent). Window-aware (WA-5.1); same Assign-button shape as
        the first notify."""
        esc = self._wa5_escalation_botuser()
        who = declined_by.name or declined_by.login
        summary = "%s -- declined by %s, please reassign" % (
            self._wa5_lead_summary(lead), who)
        # WA-5.4 (FIX 3a): clean short body + the Assign button; no raw URLs.
        body = (
            "⤴️ %s declined the WhatsApp lead -- it's back with "
            "you to reassign:\n%s\nClient: %s\n\nTap below to reassign."
            % (who, self._wa5_lead_summary(lead), lead.phone or ""))
        payload = self._wa5_payload("assign_open", lead.id)
        interactive = {
            "kind": "buttons", "body": body[:1024],
            "buttons": [{"id": payload,
                         "title": "\U0001F465 Assign salesperson"}]}
        self._wa5_staff_notify(
            esc, self._wa5_first_name(esc.user_id) if esc else "team",
            interactive, body, _WA5_TPL_HANDOFF, summary, payload, lead,
            _("WhatsApp lead declined -- reassign"),
            esc.user_id if esc else None)

    # ---- tiny part-parsers (fail-safe) -----------------------------
    @api.model
    def _wa5_lead_from_parts(self, parts):
        lid = parts[0] if parts else ""
        if not str(lid).isdigit():
            return None
        lead = self.env["crm.lead"].sudo().browse(int(lid))
        return lead if lead.exists() else None

    @api.model
    def _wa5_user_from_part(self, parts, idx):
        if len(parts) <= idx or not str(parts[idx]).isdigit():
            return None
        u = self.env["res.users"].sudo().browse(int(parts[idx]))
        return u if u.exists() else None
