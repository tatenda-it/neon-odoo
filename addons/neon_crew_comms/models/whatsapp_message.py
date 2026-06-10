# -*- coding: utf-8 -*-
"""B11 / WA-2 -- crew tap-back (Piece C, bridge).

Intercepts crew_confirm / crew_decline taps in handle_inbound BEFORE the
Copilot bot.user-resolve path, so it works for crew with no Odoo user /
no bot.user (freelancers). A template quick-reply tap arrives as inbound
type='button' carrying the HMAC payload we set when sending. Two-factor
auth: HMAC payload (can't be forged) AND the sender's E.164 must be one
of the assignment's crew phones. Confirm/decline REUSE the existing
action_confirm / decline wizard. Unknown/expired/tampered/mismatch ->
safe fallback, never a mis-route.
"""
import logging

from odoo import _, api, fields, models

from odoo.addons.neon_channels.models import wa_payload
from odoo.addons.neon_channels.models.phone_utils import to_e164

_logger = logging.getLogger(__name__)


class WhatsAppMessage(models.Model):
    _inherit = "neon.whatsapp.message"

    @api.model
    def handle_inbound(self, message, metadata):
        # Crew tap intercept FIRST (WA-2; covers unmapped freelancers). If
        # it's not a crew tap, fall through.
        handled = self._wa_maybe_crew_tap(message)
        if handled is not None:
            return handled
        # WA-7 crew selection NEXT (MAPPED OD/superuser): a wa7_* tap, or a
        # crew-select turn for a phone with a live cs_* session, or the
        # "select crew" command. Runs BEFORE WA-6 so a cs_* session (which
        # shares the equip-session row) is claimed here, not by the WA-6
        # equip router. Returns None for anything else (incl. WA-6 sessions),
        # so WA-6 / WA-5 / Copilot run unchanged.
        handled = self._wa7_maybe_intercept(message)
        if handled is not None:
            return handled
        # WA-8 availability check NEXT (READ-ONLY; broad mapped-staff gate):
        # a re-check turn for a phone with a live av_check session, or the
        # "free on <date>? <items>" command. Text-only (no taps/intents).
        # Runs BEFORE WA-6 so an av_check session (which shares the equip-
        # session row) is claimed here; returns None for anything else (incl.
        # WA-6 sessions, non-commands, no-date or no-matched-item messages) so
        # WA-6 / WA-5 / Copilot run unchanged.
        handled = self._wa8_maybe_intercept(message)
        if handled is not None:
            return handled
        # WA-6 equipment face NEXT: a wa6_* tap, or a finalize free-text
        # turn for a phone with a live equip session. Disjoint from the
        # crew/WA-5 intents -- returns None for anything else so the WA-5 /
        # Copilot router runs unchanged (no WA-4 regression).
        handled = self._wa6_maybe_intercept(message)
        if handled is not None:
            return handled
        return super().handle_inbound(message, metadata)

    @api.model
    def _wa_maybe_crew_tap(self, message):
        """Returns True if this inbound was a crew_confirm/crew_decline
        tap (handled here), else None (let the base router run)."""
        # Template quick-reply -> type 'button' + button.payload. Also
        # accept an interactive button_reply id defensively.
        payload = None
        mtype = message.get("type")
        if mtype == "button":
            payload = (message.get("button") or {}).get("payload")
        elif mtype == "interactive":
            payload = ((message.get("interactive") or {})
                       .get("button_reply") or {}).get("id")
        if not payload:
            return None
        secret = self.env["ir.config_parameter"].sudo().get_param(
            "database.secret") or ""
        decoded = wa_payload.decode(secret, payload)
        if not decoded or decoded[0] not in ("crew_confirm", "crew_decline"):
            return None
        intent, parts = decoded
        raw_from = message.get("from")
        from_e164 = to_e164(raw_from)
        self._wa_process_crew_tap(intent, parts, from_e164, raw_from, message)
        return True

    # ----------------------------------------------------------------
    def _wa_crew_reply(self, raw_from, from_e164, text):
        self.sudo().send_message(raw_from, text)
        self.sudo().create({
            "name": f"wa-out-{from_e164}", "direction": "outbound",
            "phone_number": from_e164, "message_body": text,
            "message_type": "text", "state": "sent"})
        return True

    @api.model
    def _wa_process_crew_tap(self, intent, parts, from_e164, raw_from,
                             message):
        Crew = self.env["commercial.job.crew"].sudo()
        # audit the inbound tap
        self.sudo().create({
            "name": message.get("id") or f"wa-in-{from_e164}",
            "direction": "inbound", "phone_number": from_e164,
            "message_body": ((message.get("button") or {}).get("text")
                             or intent),
            "message_type": "button", "state": "received",
            "raw_payload": str(message)})
        aid = int(parts[0]) if parts and str(parts[0]).isdigit() else 0
        crew = Crew.browse(aid) if aid else Crew
        if not (crew and crew.exists()):
            return self._wa_crew_reply(
                raw_from, from_e164,
                _("We couldn't find that assignment -- it may have changed. "
                  "Please contact the office."))
        # two-factor: sender phone must be one of the assignment's crew
        # phones (HMAC already proved the payload is genuine).
        if from_e164 not in crew._wa_all_phones():
            _logger.warning(
                "WA crew tap phone mismatch: %s not linked to assignment %s",
                from_e164, crew.id)
            return self._wa_crew_reply(
                raw_from, from_e164,
                _("This confirmation isn't linked to your number. Please "
                  "contact the office."))
        if crew.state != "pending":
            return self._wa_crew_reply(
                raw_from, from_e164,
                _("You've already responded to this assignment (%s). "
                  "Contact the office to change it.") % crew.state)
        if intent == "crew_confirm":
            self._wa_do_confirm(crew)
            reply = _("✅ Thanks %(name)s -- you're confirmed for "
                      "%(job)s.") % {"name": crew.partner_id.name or "",
                                     "job": crew.job_id.name}
        else:
            self._wa_do_decline(crew)
            reply = _("Got it -- we've marked you as unavailable for "
                      "%(job)s. Ops will follow up. If you can share why, "
                      "just reply here.") % {"job": crew.job_id.name}
        return self._wa_crew_reply(raw_from, from_e164, reply)

    def _wa_do_confirm(self, crew):
        """action_confirm under the crew member's identity (ACL fires);
        sudo fallback for freelancers / any ACL edge."""
        try:
            target = (crew.with_user(crew.user_id.id)
                      if crew.user_id else crew)
            target.action_confirm()
        except Exception as e:  # noqa: BLE001
            _logger.warning("WA crew confirm fell back to sudo (%s): %s",
                            crew.id, e)
            crew.sudo().action_confirm()

    def _wa_do_decline(self, crew):
        """Drive the EXISTING decline wizard with a default reason, then
        flag ops (the wizard itself doesn't -- that was stubbed)."""
        reason = _("Can't make it (via WhatsApp -- ops to follow up).")
        try:
            env = (self.env(user=crew.user_id.id)
                   if crew.user_id else self.env.sudo())
            wiz = env["commercial.job.crew.decline.wizard"].create(
                {"crew_id": crew.id, "decline_reason": reason})
            wiz.action_confirm()
        except Exception as e:  # noqa: BLE001
            _logger.warning("WA crew decline fell back to sudo (%s): %s",
                            crew.id, e)
            crew.sudo().write({"state": "declined",
                               "responded_on": fields.Datetime.now(),
                               "decline_reason": reason})
        self._wa_flag_ops_decline(crew, reason)

    def _wa_flag_ops_decline(self, crew, reason):
        """Chatter + a to-do activity on the job for ops reassignment.
        Best-effort -- must never break the decline."""
        job = crew.job_id
        body = _("⚠️ Crew declined via WhatsApp: %(name)s "
                 "(%(role)s) -- %(reason)s") % {
                     "name": crew._wa_crew_name(),
                     "role": crew._wa_role_label(), "reason": reason}
        try:
            job.sudo().message_post(body=body)
        except Exception as e:  # noqa: BLE001
            _logger.warning("WA decline chatter failed (%s): %s", job.id, e)
        try:
            assignee = (job.user_id.id if getattr(job, "user_id", False)
                        else self.env.uid)
            job.sudo().activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Crew declined -- reassign"),
                note=body, user_id=assignee)
        except Exception as e:  # noqa: BLE001
            _logger.warning("WA decline activity skipped (%s): %s", job.id, e)
