# -*- coding: utf-8 -*-
"""B11 / WA-2 -- crew-assignment WhatsApp wiring (bridge).

Extends ``commercial.job.crew`` with the canonical crew->phone resolver,
the per-template rate-limit anchors, and the per-record send helpers.
Confirm/decline STATUS already exists on the base model (state /
action_confirm / decline wizard) -- WA-2 only wires it.
"""
from datetime import timedelta

from odoo import _, api, fields, models

from odoo.addons.neon_channels.models import wa_payload
from odoo.addons.neon_channels.models.phone_utils import to_e164

# Meta-approved template names + language. PARAMETRISED -- the exact
# approved names/format are confirmed at go-live (owner action). The
# body-param ORDER below must match the approved template's variables.
TPL_CREW_ASSIGNMENT = "crew_assignment"
TPL_JOB_REMINDER = "job_reminder"
TPL_LANG = "en"

# Don't re-send the SAME template to the SAME crew member for the SAME
# job within this window (double-click / repeat-notify guard).
_RATE_LIMIT_HOURS = 12


class CommercialJobCrew(models.Model):
    _inherit = "commercial.job.crew"

    # Per-template rate-limit anchors (the base notification_sent Boolean
    # is "ever notified"; these timestamps drive the 12h window).
    notified_on = fields.Datetime(
        string="Assignment Notified On", readonly=True,
        help="Last time the crew_assignment WhatsApp template was sent "
        "for this assignment. Drives the 12h re-notify guard.")
    reminder_on = fields.Datetime(
        string="Reminder Sent On", readonly=True,
        help="Last time the job_reminder WhatsApp template was sent for "
        "this assignment.")

    # ---- crew -> phone resolution (Gate-1 addendum) -----------------
    def _wa_resolve_phone(self):
        """The single sendable WhatsApp number for this crew member,
        tried in authority order, normalised to E.164: (1) the explicit
        bot.user mapping via user_id, (2) the partner mobile then phone,
        (3) the mapped hr.employee mobile/work phone (soft -- only if
        neon_hr is installed). Returns E.164 or False."""
        self.ensure_one()
        if self.user_id:
            bu = self.env["neon.bot.user"].sudo().search(
                [("user_id", "=", self.user_id.id), ("active", "=", True)],
                limit=1)
            if bu:
                e = to_e164(bu.phone_number or "")
                if e:
                    return e
        for raw in (self.partner_id.mobile, self.partner_id.phone):
            e = to_e164(raw or "")
            if e:
                return e
        emp = (self.neon_employee_id
               if "neon_employee_id" in self._fields else False)
        if emp:
            for raw in (emp.mobile_phone, emp.work_phone):
                e = to_e164(raw or "")
                if e:
                    return e
        return False

    def _wa_all_phones(self):
        """The SET of all canonical phones for this crew member (across
        every anchor). Inbound auth: a tap is accepted only if the
        sender's E.164 is in this set (two-factor with the HMAC payload)."""
        self.ensure_one()
        out = set()
        if self.user_id:
            for bu in self.env["neon.bot.user"].sudo().search(
                    [("user_id", "=", self.user_id.id),
                     ("active", "=", True)]):
                e = to_e164(bu.phone_number or "")
                if e:
                    out.add(e)
        for raw in (self.partner_id.mobile, self.partner_id.phone):
            e = to_e164(raw or "")
            if e:
                out.add(e)
        emp = (self.neon_employee_id
               if "neon_employee_id" in self._fields else False)
        if emp:
            for raw in (emp.mobile_phone, emp.work_phone):
                e = to_e164(raw or "")
                if e:
                    out.add(e)
        return out

    # ---- notifiability (recipient filter + rate-limit) -------------
    def _wa_recently(self, when):
        return bool(when and (fields.Datetime.now() - when)
                    < timedelta(hours=_RATE_LIMIT_HOURS))

    def _wa_is_notifiable(self):
        """Eligible for a crew_assignment send: still pending, has a
        phone, not opted out, not already notified within 12h."""
        self.ensure_one()
        if self.state != "pending":
            return False
        if not self._wa_resolve_phone():
            return False
        if self.partner_id.sudo().wa_opt_out:
            return False
        if self._wa_recently(self.notified_on):
            return False
        return True

    # ---- per-record sends ------------------------------------------
    def _wa_role_label(self):
        return dict(self._fields["role"].selection).get(self.role, self.role)

    def _wa_when_label(self):
        d = self.job_id.event_date
        return d.strftime("%a %d %b %Y") if d else _("date TBC")

    def _wa_crew_name(self):
        return (self.partner_id.name
                or (self.user_id.name if self.user_id else _("Crew")))

    def _wa_time_label(self):
        """Best-effort crew call-time for the templates. commercial.job
        carries no time-of-day (only event_date), so source the earliest
        linked event_job's load-in / dispatch / prep time (in the user's
        tz); 'TBC' when none is set. Always non-empty (the send guard
        rejects empty params)."""
        self.ensure_one()
        job = self.job_id
        ejs = (job.event_job_ids
               if "event_job_ids" in job._fields else None)
        candidates = []
        for ej in (ejs or []):
            for fld in ("load_in_start", "dispatch_datetime",
                        "prep_start_datetime"):
                if fld in ej._fields and ej[fld]:
                    candidates.append(ej[fld])
                    break
        if candidates:
            return fields.Datetime.context_timestamp(
                self, min(candidates)).strftime("%H:%M")
        return _("TBC")

    def _wa_send_assignment_notification(self):
        """Send the crew_assignment template (Confirm / Can't-make-it
        quick-reply buttons carrying the HMAC tap-back payloads). Sets
        notification_sent + notified_on on success. Returns the
        send_template result dict.

        PRIVATE (_-prefixed) so it isn't call_kw-able: the ops gate lives
        on the action wrappers / wizard; this must only be reached
        through them or the cron, never by a direct authenticated RPC
        from a non-ops user (WA-2 review fix)."""
        self.ensure_one()
        phone = self._wa_resolve_phone()
        if not phone:
            return {"ok": False, "reason": "no_phone"}
        secret = self.env["ir.config_parameter"].sudo().get_param(
            "database.secret") or ""
        confirm_pl = wa_payload.encode(secret, "crew_confirm", self.id)
        decline_pl = wa_payload.encode(secret, "crew_decline", self.id)
        job = self.job_id
        # crew_assignment approved template = 5 vars IN ORDER:
        # {{1}} name, {{2}} job, {{3}} date, {{4}} time, {{5}} role.
        # The count + order is a contract -- a mismatch is Meta 132000.
        body_params = [self._wa_crew_name(),
                       job.name or job.display_name or "",
                       self._wa_when_label(), self._wa_time_label(),
                       self._wa_role_label()]
        res = self.env["neon.whatsapp.message"].sudo().send_template(
            phone, TPL_CREW_ASSIGNMENT, language=TPL_LANG,
            body_params=body_params,
            quick_reply_payloads=[confirm_pl, decline_pl],
            recipient_partner=self.partner_id,
            audit_body=("[crew_assignment] name=%s job=%s date=%s time=%s "
                        "role=%s" % tuple(body_params)))
        if res.get("ok"):
            self.sudo().write({"notification_sent": True,
                               "notified_on": fields.Datetime.now()})
        return res

    def _wa_send_reminder(self):
        """Send the job_reminder template (URL 'View details' button) to
        a CONFIRMED crew member. Rate-limited on reminder_on. PRIVATE --
        reached only via the ops-gated action / cron (WA-2 review fix)."""
        self.ensure_one()
        if self.state != "confirmed":
            return {"ok": False, "reason": "not_confirmed"}
        if self._wa_recently(self.reminder_on):
            return {"ok": False, "reason": "rate_limited"}
        phone = self._wa_resolve_phone()
        if not phone:
            return {"ok": False, "reason": "no_phone"}
        job = self.job_id
        venue = getattr(job, "venue_id", False)
        venue_label = (venue.name if venue else _("venue TBC"))
        # job_reminder approved template = 4 vars IN ORDER:
        # {{1}} job, {{2}} call-time, {{3}} venue, {{4}} role.
        body_params = [job.name or job.display_name or "",
                       self._wa_time_label(), venue_label,
                       self._wa_role_label()]
        res = self.env["neon.whatsapp.message"].sudo().send_template(
            phone, TPL_JOB_REMINDER, language=TPL_LANG,
            body_params=body_params,
            url_button_param=str(job.id),
            recipient_partner=self.partner_id,
            audit_body=("[job_reminder] job=%s time=%s venue=%s role=%s"
                        % tuple(body_params)))
        if res.get("ok"):
            self.sudo().write({"reminder_on": fields.Datetime.now()})
        return res
