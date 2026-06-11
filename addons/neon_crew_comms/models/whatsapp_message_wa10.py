# -*- coding: utf-8 -*-
"""B11 / WA-10 -- post-event feedback loop (the corpus builder).

On CHECK-IN LANDING (the neon_jobs check-in wizard's action_confirm calls
``_wa10_on_checkin`` once per job; guarded by event_job.wa10_prompted) WA-10
pushes a short feedback prompt to THREE voices, each in their own language:

  * SALES owner  -- relays how the CLIENT felt (client_relayed=True);
  * OD           -- operations read;
  * ALL assigned crew with a mapped bot.user -- ground truth.

Each prompt is sentiment buttons (wa10_fb:<event_job_id>:<role>:<sentiment>);
a tap records a commercial.event.feedback row (channel='whatsapp', the
extended P3.M7 model) and offers a free-text note (a short fb_notes session
UPDATES the same row). A signed tap days later still records (stateless).
A "feedback" PULL command lists the sender's role-eligible WRAPPED events to
give feedback on out of band.

Discipline (Gate-1 amended):
  * EVERY write runs ``with_user(<the real voice>)`` -- honest create_uid,
    NEVER sudo (the crew create/write ir.rule scopes it to own whatsapp rows).
  * find-or-update is ONE-per-(event, author, role); a pg advisory xact lock
    (fresh namespace 5593800) kills the concurrent-tap race.
  * the feedback CREATE sends NOTHING (mail suppressed) -- the only outbound
    is this check-in push + the tap acknowledgements. Sends only ever reach
    resolved STAFF users; never a client/partner phone.
  * recipients = exactly the sales owner + OD + assigned crew of THIS job.
"""
import logging
import zlib

from odoo import _, api, fields, models

from odoo.addons.neon_channels.models import wa_payload
from odoo.addons.neon_channels.models.phone_utils import to_e164

_logger = logging.getLogger(__name__)

# Fresh advisory-lock namespace (NOT WA-5 5593500 / WA-6 5593600 /
# WA-7 5593700) -- per-(event, author, role) find-or-update serialisation.
_WA10_LOCK_NS = 5593800

# Tight PULL command -- equals / startswith-then-space on the normalised
# body, NEVER substring (so "any feedback on the lights?" is NOT grabbed).
_WA10_COMMANDS = ("feedback", "give feedback", "event feedback")

# event_job states that count as WRAPPED (eligible for feedback).
_WA10_WRAPPED_STATES = ("completed", "closed", "returned")

_WA10_FB_STEPS = ("fb_pull", "fb_notes")
_WA10_OPTOUT = {"STOP", "START", "UNSUBSCRIBE", "STOPALL", "UNSTOP", "RESUME"}

# role -> the sentiment buttons (label, sentiment-value). crew/crew_chief get
# All-good / I-have-notes; sales + OD get a 3-way.
_WA10_BUTTONS = {
    "sales": [("\U0001F60A Happy", "positive"), ("\U0001F610 OK", "neutral"),
              ("\U0001F61E Unhappy", "negative")],
    "od": [("\U0001F44D Smooth", "positive"), ("\U0001F610 Mixed", "neutral"),
           ("⚠️ Issues", "negative")],
    "crew": [("\U0001F44D All good", "positive"),
             ("\U0001F4AC I have notes", "neutral")],
    "crew_chief": [("\U0001F44D All good", "positive"),
                   ("\U0001F4AC I have notes", "neutral")],
}
_WA10_PROMPT = {
    "sales": "\U0001F4CB %s wrapped. How did the CLIENT feel about it?",
    "od": "\U0001F4CB %s wrapped. How did operations go?",
    "crew": "\U0001F4CB %s wrapped. How did it go on the ground?",
    "crew_chief": "\U0001F4CB %s wrapped. How did it go on the ground?",
}


class WhatsAppMessageWA10(models.Model):
    _inherit = "neon.whatsapp.message"

    # ================================================================
    # PUSH on check-in landing (called from the neon_jobs wizard, sudo)
    # ================================================================
    @api.model
    def _wa10_on_checkin(self, event_job, actor_uid=None):
        """Fire the post-event feedback prompts for this job's three voices,
        ONCE (guarded by event_job.wa10_prompted). Best-effort per recipient;
        always lands an Odoo activity so a prompt is never lost. Sends reach
        ONLY resolved staff users -- never a client/partner phone."""
        ej = event_job.sudo()
        if not ej or not ej.exists() or ej.wa10_prompted:
            return False
        voices = self._wa10_voices(ej)
        for v in voices:
            try:
                self._wa10_send_prompt(v, ej)
            except Exception as e:  # noqa: BLE001 -- never break the check-in
                _logger.warning("WA-10 prompt failed (job %s, %s): %s",
                                ej.id, v.get("role"), e)
        ej.write({"wa10_prompted": True})
        return True

    @api.model
    def _wa10_resolve_sales_owner(self, job):
        """The sales rep / opportunity owner of a commercial.job: the CRM
        lead's salesperson, else the job creator (not OdooBot), else the
        first jobs-manager. Empty recordset if none (the sales voice is then
        skipped -- never messages OdooBot)."""
        job = job.sudo()
        if (job.crm_lead_id and job.crm_lead_id.user_id
                and job.crm_lead_id.user_id.active):
            return job.crm_lead_id.user_id
        root_id = self.env.ref("base.user_root").id
        if (job.create_uid and job.create_uid.id != root_id
                and job.create_uid.active):
            return job.create_uid
        grp = self.env.ref("neon_jobs.group_neon_jobs_manager",
                           raise_if_not_found=False)
        if grp:
            mgr = grp.sudo().users.filtered(
                lambda u: u.active and u.id != root_id)[:1]
            if mgr:
                return mgr
        return self.env["res.users"].sudo().browse()

    @api.model
    def _wa10_voices(self, event_job):
        """The list of {user, role} to prompt: sales owner, OD, and each
        assigned crew member WITH an active mapped bot.user. Deduped by user
        (a person filling two roles is prompted once, in the first-listed
        role: sales > od > crew)."""
        ej = event_job.sudo()
        job = ej.commercial_job_id
        out, seen = [], set()
        # defensive: only ACTIVE staff are ever prompted (a deactivated rep /
        # OD / crew member is skipped -- no stale prompt to a reassigned
        # number). The sales-owner resolver already returns active-only.
        sales = self._wa10_resolve_sales_owner(job)
        if sales and sales.id and sales.active and sales.id not in seen:
            out.append({"user": sales, "role": "sales"})
            seen.add(sales.id)
        od = self._wa6_od_user()
        if od and od.id and od.active and od.id not in seen:
            out.append({"user": od, "role": "od"})
            seen.add(od.id)
        BU = self.env["neon.bot.user"].sudo()
        for c in job.crew_assignment_ids.sudo():
            u = c.user_id
            if not u or not u.active or u.id in seen:
                continue
            if not BU.search([("user_id", "=", u.id), ("active", "=", True)],
                             limit=1):
                continue
            out.append({"user": u,
                        "role": "crew_chief" if c.is_crew_chief else "crew"})
            seen.add(u.id)
        return out

    def _wa10_send_prompt(self, voice, event_job):
        """In-window -> sentiment buttons; ALWAYS an Odoo activity fallback so
        the prompt is never lost (a cold-window wa10 Meta template is a noted
        follow-on, not built here)."""
        user, role = voice["user"], voice["role"]
        ej = event_job.sudo()
        phone = self._wa6_user_phone(user)
        body = _(_WA10_PROMPT[role]) % ej.name
        if phone and self._wa5_window_open(phone):
            try:
                ok = self.sudo().send_buttons(
                    phone, body, self._wa10_prompt_buttons(ej, role))
                self._wa6_audit_out(
                    phone, body, "interactive" if ok else "text")
            except Exception as e:  # noqa: BLE001
                _logger.warning("WA-10 send_buttons failed (job %s): %s",
                                ej.id, e)
        self._wa6_activity(
            ej, user, _("Post-event feedback — %s") % ej.name, body)
        return True

    def _wa10_prompt_buttons(self, event_job, role):
        ej = event_job.sudo()
        return [{"id": self._wa6_payload("wa10_fb", ej.id, role, sentiment),
                 "title": label}
                for (label, sentiment) in _WA10_BUTTONS.get(role, [])]

    # ================================================================
    # ENTRY -- intercept (called from handle_inbound, after WA-8/before WA-6)
    # ================================================================
    @api.model
    def _wa10_maybe_intercept(self, message):
        """True if this inbound is a WA-10 tap (wa10_*), a feedback-session
        turn (fb_pull/fb_notes) for this phone, or the "feedback" command from
        an entitled mapped staffer. Else None -> the next router runs."""
        raw_from = message.get("from")
        from_e164 = to_e164(raw_from)
        mtype = message.get("type")
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
            if decoded and decoded[0] in ("wa10_fb", "wa10_notes", "wa10_pull"):
                self._wa10_handle_tap(
                    decoded[0], decoded[1], from_e164, raw_from, message)
                return True
            return None
        if mtype == "text":
            body = ((message.get("text") or {}).get("body") or "")
            if body.strip().upper() in _WA10_OPTOUT:
                return None
            sess = self.env["neon.wa.equip.session"]._active_for_phone(
                from_e164)
            if sess and sess.step in _WA10_FB_STEPS:
                self._wa10_handle_text(sess, body, from_e164, raw_from, message)
                return True
            if sess:
                return None  # a live non-WA10 session owns this phone
            if self._wa10_is_command(body):
                sender = self._wa6_resolve_user(from_e164)
                if sender and sender.id:
                    events = self._wa10_eligible_events(sender)
                    if events:
                        self._wa10_start_pull(
                            sender, events, from_e164, raw_from, message)
                        return True
        return None

    @api.model
    def _wa10_is_command(self, body):
        norm = " ".join((body or "").strip().lower().split())
        if not norm:
            return False
        return any(norm == c or norm.startswith(c + " ")
                   for c in _WA10_COMMANDS)

    # ================================================================
    # TAPS -- wa10_fb (sentiment) + wa10_notes (open the note session)
    # ================================================================
    @api.model
    def _wa10_handle_tap(self, intent, parts, from_e164, raw_from, message):
        self._wa6_audit_in(from_e164, message, intent)
        try:
            sender = self._wa6_resolve_user(from_e164)
            if not sender or not sender.id:
                return self._wa6_reply(
                    raw_from, from_e164,
                    _("We couldn't match your number to a team member."))
            if intent == "wa10_fb":
                return self._wa10_tap_fb(sender, parts, from_e164, raw_from)
            if intent == "wa10_notes":
                return self._wa10_tap_notes(sender, parts, from_e164, raw_from)
        except Exception as e:  # noqa: BLE001 -- a tap must never 500
            _logger.error("WA-10 tap failed (intent=%s): %s", intent, e,
                          exc_info=True)
        return self._wa6_reply(
            raw_from, from_e164, _("Sorry — that didn't go through."))

    def _wa10_tap_fb(self, sender, parts, from_e164, raw_from):
        # parts = [event_job_id, role, sentiment]
        if len(parts) < 3 or not str(parts[0]).isdigit():
            return self._wa6_reply(raw_from, from_e164,
                                   _("That feedback link expired."))
        ej = self.env["commercial.event.job"].sudo().browse(
            int(parts[0])).exists()
        role, sentiment = parts[1], parts[2]
        if not ej:
            return self._wa6_reply(raw_from, from_e164,
                                   _("That event is no longer available."))
        # two-factor: the tapper's RESOLVED role for this event must match the
        # tapped role (a crew member can't record as 'sales'/'od').
        actual = self._wa10_role_for(sender, ej)
        if not actual or actual != role:
            return self._wa6_reply(
                raw_from, from_e164,
                _("This feedback prompt isn't for your role on %s.") % ej.name)
        rec = self._wa10_record(ej, role, sender, sentiment, body=None)
        if not rec:
            return self._wa6_reply(
                raw_from, from_e164,
                _("Couldn't log that — please try from Odoo."))
        # open a short note session so the next free text UPDATES this row.
        self.env["neon.wa.equip.session"]._start_fb(
            from_e164, sender, "fb_notes",
            {"event_job_id": ej.id, "role": role, "fb_id": rec.id})
        return self._wa6_send_buttons(
            raw_from, from_e164,
            _("Thanks — logged for %s. Add a sentence if you like (just reply), "
              "or tap Done.") % ej.name,
            [{"id": self._wa6_payload("wa10_notes", rec.id, "done"),
              "title": "✅ Done"}])

    def _wa10_tap_notes(self, sender, parts, from_e164, raw_from):
        # wa10_notes:<fb_id>:done -> close the note session.
        sess = self.env["neon.wa.equip.session"]._active_for_phone(from_e164)
        if sess and sess.step == "fb_notes":
            sess.sudo().write({"step": "done", "active": False})
        return self._wa6_reply(
            raw_from, from_e164, _("\U0001F44D Thanks for the feedback."))

    # ================================================================
    # FREE TEXT -- fb_pull pick / search, fb_notes capture
    # ================================================================
    @api.model
    def _wa10_handle_text(self, sess, body, from_e164, raw_from, message):
        self._wa6_audit_in(from_e164, message, "wa10-text")
        sess.sudo().write({"last_inbound": fields.Datetime.now()})
        sender = sess.user_id
        if sess.step == "fb_notes":
            return self._wa10_capture_note(sess, body, from_e164, raw_from)
        # fb_pull: a number picks an event; else a date/name search.
        return self._wa10_pull_pick(sess, body, from_e164, raw_from, message)

    def _wa10_capture_note(self, sess, body, from_e164, raw_from):
        buf = sess._get_buffer()
        buf = buf if isinstance(buf, dict) else {}
        fb = self.env["commercial.event.feedback"].sudo().browse(
            buf.get("fb_id") or 0).exists()
        text = " ".join((body or "").split())
        if fb and text:
            try:
                fb.with_user(sess.user_id.id).with_context(
                    tracking_disable=True, mail_create_nolog=True,
                    mail_notify_force_send=False).write(
                        {"feedback_text": text})
            except Exception as e:  # noqa: BLE001
                _logger.warning("WA-10 note write failed (fb %s): %s",
                                fb.id, e)
        sess.sudo().write({"step": "done", "active": False})
        return self._wa6_reply(
            raw_from, from_e164,
            _("Got it — added to your feedback. Thank you!"))

    def _wa10_pull_pick(self, sess, body, from_e164, raw_from, message):
        buf = sess._get_buffer()
        buf = buf if isinstance(buf, dict) else {}
        ids = buf.get("event_ids") or []
        norm = (body or "").strip()
        EJ = self.env["commercial.event.job"].sudo()
        if norm.isdigit() and 1 <= int(norm) <= len(ids):
            ej = EJ.browse(ids[int(norm) - 1]).exists()
            if not ej:
                return self._wa6_reply(raw_from, from_e164,
                                       _("That event is no longer available."))
            return self._wa10_send_pick_prompt(sess, ej, from_e164, raw_from)
        # not a number -> a name/date search over the sender's wrapped events
        hits = self._wa10_search_events(sess.user_id, norm)
        if hits:
            return self._wa10_present_list(sess, hits, from_e164, raw_from)
        return self._wa6_reply(
            raw_from, from_e164,
            _("Reply with a number from the list, or part of an event name."))

    def _wa10_send_pick_prompt(self, sess, ej, from_e164, raw_from):
        """A picked wrapped event -> resolve the sender's role for it and send
        that role's sentiment buttons; close the pull session (the buttons
        drive the record + note from here)."""
        role = self._wa10_role_for(sess.user_id, ej)
        if not role:
            return self._wa6_reply(
                raw_from, from_e164,
                _("You're not on %s, so there's no feedback to give there.")
                % ej.name)
        sess.sudo().write({"step": "done", "active": False})
        return self._wa6_send_buttons(
            raw_from, from_e164,
            _(_WA10_PROMPT[role]) % ej.name,
            self._wa10_prompt_buttons(ej, role))

    # ================================================================
    # PULL -- list the sender's role-eligible WRAPPED events
    # ================================================================
    @api.model
    def _wa10_eligible_events(self, user, limit=10):
        """Wrapped events the user has a voice on, most-recent first: the
        sales owner's jobs, the OD's all, a crew member's assigned jobs."""
        EJ = self.env["commercial.event.job"].sudo()
        base = [("state", "in", list(_WA10_WRAPPED_STATES))]
        if self._wa6_can_initiate(user):       # OD / superuser -> all
            evs = EJ.search(base, order="event_date desc, id desc", limit=limit)
            return evs
        evs = EJ.search(base, order="event_date desc, id desc")
        out = evs.filtered(lambda e: self._wa10_role_for(user, e))
        return out[:limit]

    @api.model
    def _wa10_search_events(self, user, term, limit=10):
        if not term:
            return self.env["commercial.event.job"].sudo().browse()
        EJ = self.env["commercial.event.job"].sudo()
        evs = EJ.search(
            [("state", "in", list(_WA10_WRAPPED_STATES)),
             ("name", "ilike", term)],
            order="event_date desc, id desc")
        return evs.filtered(lambda e: self._wa10_role_for(user, e))[:limit]

    @api.model
    def _wa10_role_for(self, user, event_job):
        """The user's feedback role on this event (sales > crew_chief/crew >
        od), or None if they have no voice on it. The two-factor check for a
        tap and the PULL pick."""
        if not user or not user.id:
            return None
        ej = event_job.sudo()
        job = ej.commercial_job_id
        owner = self._wa10_resolve_sales_owner(job)
        if owner and owner.id == user.id:
            return "sales"
        for c in job.crew_assignment_ids.sudo():
            if c.user_id.id == user.id:
                return "crew_chief" if c.is_crew_chief else "crew"
        if self._wa6_can_initiate(user):       # OD / superuser
            return "od"
        return None

    @api.model
    def _wa10_start_pull(self, sender, events, from_e164, raw_from, message):
        self._wa6_audit_in(from_e164, message, "feedback")
        return self._wa10_present_list(
            self.env["neon.wa.equip.session"]._start_fb(
                from_e164, sender, "fb_pull", {"event_ids": events.ids}),
            events, from_e164, raw_from)

    def _wa10_present_list(self, sess, events, from_e164, raw_from):
        sess.sudo().write({"buffer": self._wa10_dump({"event_ids": events.ids})})
        lines = "\n".join(
            "%d. %s (%s)" % (i + 1, e.sudo().name,
                             e.sudo().event_date or "—")
            for i, e in enumerate(events))
        return self._wa6_reply(
            raw_from, from_e164,
            _("Wrapped events you can give feedback on:\n%s\n\nReply a number "
              "(or part of an event name to search).") % lines)

    @api.model
    def _wa10_dump(self, buf):
        import json
        return json.dumps(buf or {})

    # ================================================================
    # RECORD -- find-or-update one-per-(event, author, role) under a lock
    # ================================================================
    def _wa10_try_lock(self, event_job_id, user_id, role):
        key = zlib.crc32(
            ("%s:%s:%s" % (event_job_id, user_id, role)).encode("utf-8")
        ) & 0x7FFFFFFF
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s, %s)",
                            (_WA10_LOCK_NS, key))
        return bool(self.env.cr.fetchone()[0])

    def _wa10_record(self, event_job, role, user, sentiment, body=None):
        """Find-or-update THIS user's whatsapp feedback row for (event, role)
        and write it AS the real user (honest create_uid; the crew ir.rule
        scopes a crew member to their own whatsapp rows). Advisory-locked so a
        concurrent double-tap updates one row, never two. Mail suppressed ->
        zero send on save. Returns the row (or empty on failure)."""
        ej = event_job.sudo()
        Fb = self.env["commercial.event.feedback"]
        if not self._wa10_try_lock(ej.id, user.id, role):
            # a concurrent tap holds it -> it will record; treat as success
            existing = Fb.sudo().search(
                [("event_job_id", "=", ej.id), ("captured_by", "=", user.id),
                 ("wa_role", "=", role), ("channel", "=", "whatsapp")], limit=1)
            return existing
        existing = Fb.sudo().search(
            [("event_job_id", "=", ej.id), ("captured_by", "=", user.id),
             ("wa_role", "=", role), ("channel", "=", "whatsapp")], limit=1)
        vals = {"sentiment": sentiment}
        text = " ".join((body or "").split()) if body else None
        if text:
            vals["feedback_text"] = text
        ctx = dict(mail_create_nosubscribe=True, mail_create_nolog=True,
                   mail_notify_force_send=False, tracking_disable=True)
        try:
            if existing:
                existing.with_user(user.id).with_context(**ctx).write(vals)
                return existing
            vals.update({
                "event_job_id": ej.id, "channel": "whatsapp", "wa_role": role,
                "captured_by": user.id, "client_relayed": role == "sales",
                "feedback_text": (text or self._wa10_default_text(role,
                                                                  sentiment))})
            return Fb.with_user(user.id).with_context(**ctx).create(vals)
        except Exception as e:  # noqa: BLE001
            _logger.error("WA-10 record failed (job %s role %s user %s): %s",
                          ej.id, role, user.id, e, exc_info=True)
            return Fb.browse()

    @api.model
    def _wa10_default_text(self, role, sentiment):
        """feedback_text is required on the model; a sentiment-only tap seeds
        a readable placeholder the optional note then replaces."""
        labels = {"positive": "positive", "neutral": "ok / mixed",
                  "negative": "negative"}
        return "[%s via WhatsApp] %s" % (role, labels.get(sentiment, sentiment))

    # ---- tiny part parsers -----------------------------------------
    @api.model
    def _wa10_event_from_parts(self, parts):
        if not parts or not str(parts[0]).isdigit():
            return None
        ej = self.env["commercial.event.job"].sudo().browse(int(parts[0]))
        return ej if ej.exists() else None
