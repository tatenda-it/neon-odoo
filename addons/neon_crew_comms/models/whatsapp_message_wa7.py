# -*- coding: utf-8 -*-
"""B11 / WA-7 -- Crew selection on WhatsApp (the last laptop seam).

The OD (wa6_od_login) or a Neon Superuser picks the team + the crew chief
from their phone, list-then-pick THREE times in one session:

  (1) JOB    -- numbered event jobs in planning/prep whose PARENT
               commercial.job has NO crew yet (from-scratch only; editing
               an existing team stays in Odoo).
  (2) PEOPLE -- numbered ACTIVE mapped bot.users; multi-select reply
               "1, 3, 4"; read back the named team.
  (3) CHIEF  -- the picked people (all carry a user_id by pool definition,
               so _check_crew_chief_has_user is satisfied up front); reply
               one number.

Confirm [Confirm team][Change] -> create commercial.job.crew rows on the
PARENT job (default role 'tech', is_crew_chief on the chosen one) AS THE
REAL ACTING USER (the resolved OD/superuser, who holds can_edit_crew --
honest create_uid, NO bare sudo). crew_chief_id recomputes on the event
job (the seam WA-6 reads). Then offer [Notify the crew] -> fires the
EXISTING WA-2 crew_assignment confirm/decline to each picked person. D4:
NOTHING fires on save; WA-2 only on the explicit Notify tap.

Reuses the WA-6 bridge helpers + the neon.wa.equip.session row (new cs_*
steps; WA-7's intercept runs BEFORE WA-6's and claims only cs_* sessions,
so WA-6 is untouched). Reuses the wa7_confirm/wa7_change/wa7_notify intents
(neon_channels 17.0.1.18.0). Two-factor everywhere: HMAC payload + sender
phone -> resolved OD/superuser, re-checked on every turn.
"""
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.neon_channels.models import wa_payload
from odoo.addons.neon_channels.models.phone_utils import to_e164

_logger = logging.getLogger(__name__)

# Tight crew-select commands. EQUALS or STARTSWITH-then-space on the
# normalised body -- NEVER substring (so "can you select crew options"
# starts with "can", not "select crew", and is NOT grabbed).
_WA7_SELECT_COMMANDS = ("select crew", "assign crew", "pick crew")

# Fresh advisory-lock namespace (NOT WA-5's 5593500 / WA-6's 5593600).
_WA7_LOCK_NS = 5593700

_WA7_DEFAULT_ROLE = "tech"
_WA7_CS_STEPS = ("cs_job", "cs_people", "cs_chief", "cs_confirm")


class WhatsAppMessageWA7(models.Model):
    _inherit = "neon.whatsapp.message"

    # ================================================================
    # ENTRY -- called from handle_inbound BEFORE _wa6_maybe_intercept
    # ================================================================
    @api.model
    def _wa7_maybe_intercept(self, message):
        """True if this inbound is a WA-7 tap (wa7_*), a crew-select turn
        for a phone with a live cs_* session, or the select-crew command
        from an entitled OD/superuser with >=1 eligible job. Else None so
        WA-6 / WA-5 / Copilot run unchanged. Claims ONLY cs_* sessions, so
        the shared equip-session row stays disjoint from WA-6."""
        raw_from = message.get("from")
        from_e164 = to_e164(raw_from)
        mtype = message.get("type")
        # 1) a button tap carrying our HMAC payload
        payload = None
        if mtype == "button":
            payload = (message.get("button") or {}).get("payload")
        elif mtype == "interactive":
            inter = message.get("interactive") or {}
            for k in ("button_reply", "list_reply"):
                if inter.get(k):
                    payload = inter[k].get("id")
                    break
        if payload:
            decoded = wa_payload.decode(self._wa6_secret(), payload)
            if decoded and decoded[0] in (
                    "wa7_confirm", "wa7_change", "wa7_notify"):
                self._wa7_handle_tap(
                    decoded[0], decoded[1], from_e164, raw_from, message)
                return True
            return None  # not a WA-7 tap
        # 2) free text
        if mtype == "text":
            body = ((message.get("text") or {}).get("body") or "")
            if body.strip().upper() in {
                    "STOP", "START", "UNSUBSCRIBE", "STOPALL", "UNSTOP",
                    "RESUME"}:
                return None
            sess = self.env["neon.wa.equip.session"]._active_for_phone(
                from_e164)
            if sess and sess.step in _WA7_CS_STEPS:
                self._wa7_handle_text(
                    sess, body, from_e164, raw_from, message)
                return True
            if sess:
                return None  # a live WA-6 session owns this phone
            # no live session -> is this the select-crew command from an
            # OD/superuser who actually HAS a from-scratch job? Grab ONLY
            # then; a non-command, unmapped, non-OD, or no-eligible-job all
            # fall through UNCHANGED (WA-6 / Copilot / client lane).
            if self._wa7_is_command(body):
                sender = self._wa6_resolve_user(from_e164)
                if sender and sender.id and self._wa6_can_initiate(sender):
                    jobs = self._wa7_eligible_jobs()
                    if jobs:
                        self._wa7_start_select(
                            sender, jobs, from_e164, raw_from, message)
                        return True
        return None

    @api.model
    def _wa7_is_command(self, body):
        """Tight select-crew match: EQUALS or STARTSWITH-then-space on the
        normalised body. True / False. Never substring."""
        norm = " ".join((body or "").strip().lower().split())
        if not norm:
            return False
        return any(norm == c or norm.startswith(c + " ")
                   for c in _WA7_SELECT_COMMANDS)

    # ================================================================
    # ELIGIBILITY + CANDIDATE POOL
    # ================================================================
    @api.model
    def _wa7_eligible_jobs(self):
        """Event jobs in planning/prep whose PARENT commercial.job has NO
        crew rows yet -- the from-scratch set. Org-wide (OD authority is not
        per-job). Crew is created on the parent; listing event jobs mirrors
        the WA-6.2 finalize face. (⚠️ DECISION WA-7.)"""
        return self.env["commercial.event.job"].sudo().search(
            [("state", "in", ("planning", "prep")),
             ("commercial_job_id.crew_assignment_ids", "=", False)],
            order="id")

    @api.model
    def _wa7_candidate_users(self):
        """The candidate pool (D1): ACTIVE mapped bot.users -> their
        res.users, deduped, ordered by name. Every pool member has a user_id
        (bot.user.user_id is required), so all are chief-eligible up front."""
        bots = self.env["neon.bot.user"].sudo().search(
            [("active", "=", True), ("user_id", "!=", False)])
        return bots.mapped("user_id").sorted(
            key=lambda u: (u.name or "").lower())

    # ================================================================
    # FLOW -- start + the three picks (NUMBER replies)
    # ================================================================
    @api.model
    def _wa7_start_select(self, sender, jobs, from_e164, raw_from, message):
        """Open the crew-select session (step cs_job) + send the numbered
        list of from-scratch jobs. 1 job is still listed (no auto-assume)."""
        self._wa6_audit_in(from_e164, message, "select crew")
        jobs = jobs.sorted(key=lambda j: j.id)
        self.env["neon.wa.equip.session"]._start_pick(
            from_e164, sender, "cs_job", jobs.ids)
        lines = "\n".join(
            "%d. %s (%s)" % (
                i + 1, j.sudo().name,
                j.sudo().commercial_job_id.partner_id.name or "client")
            for i, j in enumerate(jobs))
        return self._wa6_reply(
            raw_from, from_e164,
            _("Jobs needing a crew:\n%s\n\nReply with the number to pick a "
              "job.") % lines)

    @api.model
    def _wa7_handle_text(self, sess, body, from_e164, raw_from, message):
        self._wa6_audit_in(from_e164, message, "wa7-text")
        sess.sudo().write({"last_inbound": fields.Datetime.now()})
        # defense: the holder must STILL be OD/superuser (re-checked).
        if not self._wa6_can_initiate(sess.user_id):
            sess.sudo().write({"active": False})
            return self._wa6_reply(
                raw_from, from_e164,
                _("You're no longer authorised to assign crew from here."))
        # a re-typed select-crew command restarts (if still eligible)
        if self._wa7_is_command(body):
            jobs = self._wa7_eligible_jobs()
            if jobs:
                return self._wa7_start_select(
                    sess.user_id, jobs, from_e164, raw_from,
                    {"type": "text", "text": {"body": body}})
        if sess.step == "cs_job":
            return self._wa7_pick_job(sess, body, from_e164, raw_from)
        if sess.step == "cs_people":
            return self._wa7_pick_people(sess, body, from_e164, raw_from)
        if sess.step == "cs_chief":
            return self._wa7_pick_chief(sess, body, from_e164, raw_from)
        # cs_confirm -> awaiting a button tap; stray text re-shows it.
        return self._wa7_present_confirm(sess, raw_from, from_e164)

    def _wa7_pick_job(self, sess, body, from_e164, raw_from):
        job_ids = sess._get_buffer()  # list of eligible event_job ids
        EJ = self.env["commercial.event.job"].sudo()
        norm = (body or "").strip()
        if not (norm.isdigit() and 1 <= int(norm) <= len(job_ids)):
            lines = "\n".join(
                "%d. %s" % (i + 1, EJ.browse(jid).name)
                for i, jid in enumerate(job_ids))
            return self._wa6_reply(
                raw_from, from_e164,
                _("Reply with a number from the list:\n%s") % lines)
        ej = EJ.browse(job_ids[int(norm) - 1]).exists()
        if not ej:
            return self._wa6_reply(
                raw_from, from_e164,
                _("That job is no longer available -- text \"select crew\" "
                  "again."))
        # re-check from-scratch: the parent must still have NO crew.
        if ej.commercial_job_id.crew_assignment_ids:
            sess.sudo().write({"active": False})
            return self._wa6_reply(
                raw_from, from_e164,
                _("%s already has a crew -- edit it in Odoo. Text \"select "
                  "crew\" for the current list.") % ej.name)
        pool = self._wa7_candidate_users()
        if not pool:
            sess.sudo().write({"active": False})
            return self._wa6_reply(
                raw_from, from_e164,
                _("No mapped staff are available to assign. Map crew "
                  "WhatsApp numbers in Odoo first."))
        sess._set_buffer({"event_job_id": ej.id,
                          "job_id": ej.commercial_job_id.id,
                          "pool": pool.ids})
        sess.sudo().write({"step": "cs_people", "event_job_id": ej.id})
        lines = "\n".join(
            "%d. %s" % (i + 1, u.name) for i, u in enumerate(pool))
        return self._wa6_reply(
            raw_from, from_e164,
            _("Team for %(job)s — reply with the numbers, e.g. \"1, 3, 4\":"
              "\n%(l)s") % {"job": ej.name, "l": lines})

    @api.model
    def _wa7_parse_multi(self, body, n):
        """Parse "1, 3, 4" / "1,3,4" / "1 3 4" -> ordered UNIQUE 1-based
        indices within [1, n]; [] if none valid."""
        out = []
        for tok in re.findall(r"\d+", body or ""):
            v = int(tok)
            if 1 <= v <= n and v not in out:
                out.append(v)
        return out

    def _wa7_pick_people(self, sess, body, from_e164, raw_from):
        buf = sess._get_buffer()
        pool = buf.get("pool") or []
        Users = self.env["res.users"].sudo()
        picks = self._wa7_parse_multi(body, len(pool))
        if not picks:
            lines = "\n".join(
                "%d. %s" % (i + 1, Users.browse(uid).name)
                for i, uid in enumerate(pool))
            return self._wa6_reply(
                raw_from, from_e164,
                _("Reply with the team numbers from the list, e.g. "
                  "\"1, 3, 4\":\n%s") % lines)
        picked = [pool[i - 1] for i in picks]
        buf["picked"] = picked
        sess._set_buffer(buf)
        sess.sudo().write({"step": "cs_chief"})
        team = ", ".join(Users.browse(uid).name for uid in picked)
        chief_lines = "\n".join(
            "%d. %s" % (i + 1, Users.browse(uid).name)
            for i, uid in enumerate(picked))
        return self._wa6_reply(
            raw_from, from_e164,
            _("Team: %(team)s.\n\nWho's the crew chief? Reply one number:\n"
              "%(l)s") % {"team": team, "l": chief_lines})

    def _wa7_pick_chief(self, sess, body, from_e164, raw_from):
        buf = sess._get_buffer()
        picked = buf.get("picked") or []
        Users = self.env["res.users"].sudo()
        norm = (body or "").strip()
        if not (norm.isdigit() and 1 <= int(norm) <= len(picked)):
            chief_lines = "\n".join(
                "%d. %s" % (i + 1, Users.browse(uid).name)
                for i, uid in enumerate(picked))
            return self._wa6_reply(
                raw_from, from_e164,
                _("Reply one number for the crew chief:\n%s") % chief_lines)
        buf["chief"] = picked[int(norm) - 1]
        sess._set_buffer(buf)
        sess.sudo().write({"step": "cs_confirm"})
        return self._wa7_present_confirm(sess, raw_from, from_e164)

    # ================================================================
    # CONFIRM / CHANGE / NOTIFY (button taps -- wa7_* intents)
    # ================================================================
    def _wa7_present_confirm(self, sess, raw_from, from_e164):
        buf = sess._get_buffer()
        picked = buf.get("picked") or []
        chief = buf.get("chief")
        ej = self.env["commercial.event.job"].sudo().browse(
            buf.get("event_job_id")).exists()
        if not ej or not picked:
            sess.sudo().write({"active": False})
            return self._wa6_reply(
                raw_from, from_e164,
                _("That crew selection expired -- text \"select crew\" to "
                  "start again."))
        Users = self.env["res.users"].sudo()
        roster = ", ".join(
            ("%s (chief)" % Users.browse(uid).name) if uid == chief
            else Users.browse(uid).name for uid in picked)
        if buf.get("created"):
            body = _("✅ Crew set for %(job)s: %(roster)s.\n\nNotify them "
                     "now?") % {"job": ej.name, "roster": roster}
            buttons = [{"id": self._wa6_payload("wa7_notify", sess.id),
                        "title": "📣 Notify the crew"}]
        else:
            body = _("Team for %(job)s: %(roster)s.\n\nConfirm?") % {
                "job": ej.name, "roster": roster}
            buttons = [
                {"id": self._wa6_payload("wa7_confirm", sess.id),
                 "title": "✅ Confirm team"},
                {"id": self._wa6_payload("wa7_change", sess.id),
                 "title": "✏️ Change"}]
        return self._wa6_send_buttons(raw_from, from_e164, body, buttons)

    @api.model
    def _wa7_handle_tap(self, intent, parts, from_e164, raw_from, message):
        self._wa6_audit_in(from_e164, message, intent)
        try:
            sess = self._wa7_session_from_parts(parts)
            if not sess or not sess.active:
                return self._wa6_reply(
                    raw_from, from_e164,
                    _("That crew selection has ended. Text \"select crew\" "
                      "to start again."))
            # two-factor: tapper's phone == session phone AND still OD/su.
            if from_e164 != sess.phone_number:
                _logger.warning("WA-7 tap phone mismatch: %s != %s",
                                from_e164, sess.phone_number)
                return self._wa6_reply(
                    raw_from, from_e164,
                    _("This crew selection isn't linked to your number."))
            if not self._wa6_can_initiate(sess.user_id):
                return self._wa6_reply(
                    raw_from, from_e164,
                    _("You're no longer authorised to assign crew."))
            if intent == "wa7_change":
                buf = sess._get_buffer()
                # refresh the pool -- a member may have gone inactive since
                # the job pick; offer the CURRENT active mapped users + clear
                # the prior picked/chief for a clean re-pick.
                pool = self._wa7_candidate_users().ids
                buf["pool"] = pool
                buf.pop("created", None)
                buf.pop("picked", None)
                buf.pop("chief", None)
                sess._set_buffer(buf)
                sess.sudo().write({"step": "cs_people"})
                lines = "\n".join(
                    "%d. %s" % (i + 1, self.env["res.users"].sudo()
                                .browse(uid).name)
                    for i, uid in enumerate(pool))
                return self._wa6_reply(
                    raw_from, from_e164,
                    _("Re-pick the team — reply with the numbers, e.g. "
                      "\"1, 3, 4\":\n%s") % lines)
            if intent == "wa7_notify":
                return self._wa7_do_notify(sess, raw_from, from_e164)
            return self._wa7_do_confirm(sess, raw_from, from_e164)
        except Exception as e:  # noqa: BLE001 -- a tap must never 500
            _logger.error("WA-7 tap routing failed (intent=%s): %s",
                          intent, e, exc_info=True)
            return self._wa6_reply(
                raw_from, from_e164,
                _("Sorry -- something went wrong. Please try again."))

    def _wa7_try_lock(self, job_id):
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            (_WA7_LOCK_NS, int(job_id)))
        return bool(self.env.cr.fetchone()[0])

    def _wa7_do_confirm(self, sess, raw_from, from_e164):
        buf = sess._get_buffer()
        job = self.env["commercial.job"].sudo().browse(
            buf.get("job_id")).exists()
        ej = self.env["commercial.event.job"].sudo().browse(
            buf.get("event_job_id")).exists()
        picked = buf.get("picked") or []
        chief = buf.get("chief")
        if not job or not ej or not picked or not chief:
            sess.sudo().write({"active": False})
            return self._wa6_reply(
                raw_from, from_e164,
                _("That crew selection expired -- text \"select crew\" "
                  "again."))
        # defense: the chief MUST be one of the picked people (guards a
        # stale/tampered buffer -- otherwise ZERO is_crew_chief rows get
        # created and crew_chief_id would resolve empty).
        if chief not in picked:
            sess.sudo().write({"active": False})
            return self._wa6_reply(
                raw_from, from_e164,
                _("That crew selection got out of sync -- text \"select "
                  "crew\" to start again."))
        # HARD idempotency: take the per-job advisory lock FIRST, THEN
        # re-check + create -- so two concurrent confirm taps can't both pass
        # the from-scratch check in the window before the lock is held.
        if not self._wa7_try_lock(job.id):
            return self._wa6_reply(
                raw_from, from_e164,
                _("That's being processed -- one moment."))
        # from-scratch re-check UNDER THE LOCK: the list can be up to the TTL
        # old; a concurrent Odoo crew edit must never be double-assigned.
        if job.crew_assignment_ids:
            sess.sudo().write({"active": False})
            return self._wa6_reply(
                raw_from, from_e164,
                _("%s already has a crew now -- edit it in Odoo.") % ej.name)
        # create AS THE REAL ACTING USER (holds can_edit_crew); the row
        # create_uid is the OD, not OdooBot. Default role 'tech', is_crew_
        # chief on the one chosen. partner_id auto-fills from user_id.
        sender = sess.user_id
        # SILENT create (D4): suppress the create-log + tracking + follower
        # notifications so assigning crew over WhatsApp never fires emails
        # (the row's own create-log/tracking; the capacity-gate chatter on an
        # active job is the job's internal log, not a crew notification). The
        # audit is create_uid (the real OD via with_user) + assigned_on. WA-2
        # confirm/decline still goes out ONLY on the explicit [Notify] tap.
        Crew = self.env["commercial.job.crew"].with_user(sender.id) \
            .with_context(mail_create_nosubscribe=True, mail_create_nolog=True,
                          mail_notify_force_send=False, tracking_disable=True)
        vals_list = [{"job_id": job.id, "user_id": uid,
                      "role": _WA7_DEFAULT_ROLE,
                      "is_crew_chief": (uid == chief)} for uid in picked]
        try:
            Crew.create(vals_list)
        except Exception as e:  # noqa: BLE001
            return self._wa6_reply(
                raw_from, from_e164,
                _("Couldn't create the crew: %s") % (
                    e.args[0] if isinstance(e, UserError) and e.args
                    else _("please assign it in Odoo.")))
        buf["created"] = True
        sess._set_buffer(buf)
        sess.sudo().write({"step": "cs_confirm"})
        return self._wa7_present_confirm(sess, raw_from, from_e164)

    def _wa7_do_notify(self, sess, raw_from, from_e164):
        buf = sess._get_buffer()
        job = self.env["commercial.job"].sudo().browse(
            buf.get("job_id")).exists()
        ej = self.env["commercial.event.job"].sudo().browse(
            buf.get("event_job_id")).exists()
        if not job:
            return self._wa6_reply(
                raw_from, from_e164,
                _("That crew selection expired."))
        picked = set(buf.get("picked") or [])
        crew = job.crew_assignment_ids.sudo()
        if picked:
            crew = crew.filtered(lambda c: c.user_id.id in picked)
        sent, skipped = [], []
        for c in crew:
            if not c._wa_is_notifiable():
                skipped.append(c._wa_crew_name())
                continue
            res = c._wa_send_assignment_notification()
            (sent if res.get("ok") else skipped).append(c._wa_crew_name())
        sess.sudo().write({"step": "done", "active": False})
        msg = _("📣 Notified %(n)d crew member(s): %(who)s.") % {
            "n": len(sent), "who": ", ".join(sent) or "—"}
        if skipped:
            msg += _("\nNot sent (no number / opted out / already): %s.") % (
                ", ".join(skipped))
        return self._wa6_reply(raw_from, from_e164, msg)

    @api.model
    def _wa7_session_from_parts(self, parts):
        if not parts or not str(parts[0]).isdigit():
            return None
        s = self.env["neon.wa.equip.session"].sudo().browse(int(parts[0]))
        return s if s.exists() else None
