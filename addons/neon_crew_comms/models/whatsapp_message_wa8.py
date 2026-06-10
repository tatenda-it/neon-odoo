# -*- coding: utf-8 -*-
"""B11 / WA-8 -- Face 1: sales availability check on WhatsApp (PURE READ).

An entitled, MAPPED staff member texts a tight command + a date (+ optional
times) + a gear list -- e.g. "free on 14 Aug? 2.5 black truss x4, distro x2"
-- and the bot answers a traffic-light availability PER ITEM for that
time-window, distinguishing a true inventory shortfall from a dates clash and
naming the competing event. NEVER books, holds, writes, or quotes money.

TEXT-ONLY MVP (Tatenda 2026-06-10): no interactive buttons -> NO wa8_* intents
-> neon_channels is UNTOUCHED. The locked edit loop survives as TYPED turns on
a sticky session:
  * items stay in the session (av_check step);
  * typing a new DATE or TIME re-checks the SAME items (read-only every pass);
  * NO time given -> a CONSERVATIVE FULL-DAY window (fails safe -- never
    under-counts a clash; warns "committed" rather than promising "free");
  * day-before edit lock -- a date that is today or already past is refused
    (re-checks are for upcoming dates).
A fresh command (new items) starts a new check; a stale session (idle > the
WA-8 soft 2h TTL) falls through to the Copilot.

ENGINE REUSE (no neon_jobs change; no reimplementation):
  supply    = ConflictEngine(env)._available_for_product(product_id)
              (serial: active units - transferred/non-good; quantity:
               quantity_on_hand, or 0 if the representing unit is blocked)
  committed = neon.equipment.reservation._committed_qty_for_product(
              product_id, w_from, w_to)   -- non-cancelled holds overlapping
              the window; serial counts 1 each, quantity counts N; a transfer-
              destination reservation is a normal dated hold (counted for free)
  available = max(0, supply - committed)
The line-bound _qty_supply / _available_qty_for_window / _short_reason all
ensure_one() a commercial.event.job.equipment.line WA-8 never creates, so WA-8
composes the SAME two primitives directly and mirrors the _short_reason
wording inline -- the engine stays the single source of truth.

TIMEZONE: users speak Harare time (Africa/Harare, UTC+2, no DST); reservations
store naive UTC. The parser builds the window in LOCAL time then converts to
UTC before the overlap query (a midnight-local window is not off-by-2h vs a
stored UTC reservation).

ENTITLEMENT (read-only, pre-authorised by the locked design -- NOT a new
access-power gate): OD/superuser, the Neon sales / manager / crew-leader tiers,
this-job crew chiefs / lead techs, and -- the accepted fallback -- ANY active
mapped staff member. Two factors: the command's HMAC isn't needed (text-only,
nothing to tamper); the inbound phone -> resolved mapped user IS the identity,
re-checked every turn. Intercepted in handle_inbound BETWEEN WA-7 and WA-6;
claims ONLY av_check sessions, so WA-6/WA-7 are untouched, and the tight parser
never steals a turn (a non-command, a no-date message, or zero matched items
all fall through to the Copilot unchanged).
"""
import logging
import re
from datetime import datetime, time as dtime, timedelta

import pytz

from odoo import _, api, fields, models

from odoo.addons.neon_channels.models.phone_utils import to_e164
# The shared matcher's stopword set -- reused so WA-8's confidence
# tokeniser folds the SAME noise words as _wa6_match_one (single source).
from .whatsapp_message_wa6 import _WA6_STOP

_logger = logging.getLogger(__name__)

# Tight availability commands. EQUALS or STARTSWITH-then-space on the
# normalised (lowered, whitespace-collapsed) body -- NEVER substring, AND only
# fired when a date parses out of the message AND >=1 item matches the
# catalogue. So "are you free on friday?" (starts with "are"), "available for
# lunch?" (no date), and "free on monday to chat" (no matched gear) all fall
# through to the Copilot. Longest-first so "available on" wins over "available".
_WA8_COMMANDS = (
    "check availability", "availability", "available on", "available for",
    "available", "free on", "free for", "avail")

# WA-8's session is much shorter-lived than the 12h finalize TTL: an
# availability check is a quick planning question, so a phone idle past this
# falls through to the Copilot (a later unrelated message is never swallowed as
# a re-check). Soft override in the intercept; the model's global 12h stays.
_WA8_TTL_HOURS = 2

_WA8_TZ = "Africa/Harare"

# A reply-button-free face, so only av_check is WA-8's.
_WA8_STEPS = ("av_check",)

# Opt-out keywords we never hijack mid-flow (mirrors WA-6/WA-7).
_WA8_OPTOUT = {"STOP", "START", "UNSUBSCRIBE", "STOPALL", "UNSTOP", "RESUME"}

# Affirmatives that confirm a pending low-confidence suggestion ("yes" ->
# check the suggested product). Tight equals-set, never substring.
_WA8_YES = {"yes", "y", "yeah", "yep", "yup", "ok", "okay", "sure",
            "yes please", "check it", "check that", "go ahead"}

# A time RANGE: "2-6pm", "2pm-6pm", "10am-2pm", "14:00-18:00", "2 to 6pm".
# A single time or a bare "9-5" (ambiguous) deliberately falls back to a
# conservative full day (see _wa8_parse_window).
_WA8_TIME_RANGE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:-|–|—|to|until|till)\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)

_WA8_YEAR = re.compile(r"\b\d{4}\b")


class WhatsAppMessageWA8(models.Model):
    _inherit = "neon.whatsapp.message"

    # ================================================================
    # ENTRY -- called from handle_inbound BETWEEN WA-7 and WA-6
    # ================================================================
    @api.model
    def _wa8_maybe_intercept(self, message):
        """True if this inbound is a WA-8 availability turn -- a re-check for
        a phone with a live av_check session, or the availability command from
        an entitled mapped user that resolves to a real check. Else None so
        WA-6 / WA-5 / Copilot run unchanged. WA-8 is TEXT-ONLY: a button /
        interactive tap is never ours (no wa8_* intents)."""
        mtype = message.get("type")
        if mtype != "text":
            return None
        raw_from = message.get("from")
        from_e164 = to_e164(raw_from)
        body = ((message.get("text") or {}).get("body") or "")
        if body.strip().upper() in _WA8_OPTOUT:
            return None
        sess = self.env["neon.wa.equip.session"]._active_for_phone(from_e164)
        if sess:
            if sess.step in _WA8_STEPS:
                if self._wa8_session_stale(sess):
                    # idle past the WA-8 soft TTL -> drop it and let a fresh
                    # command (below) or the Copilot take this message.
                    sess.sudo().write({"active": False})
                else:
                    self._wa8_handle_text(
                        sess, body, from_e164, raw_from, message)
                    return True
            else:
                return None  # a WA-6 / WA-7 session owns this phone
        # no live WA-8 session -> is this the availability command from an
        # entitled mapped user, resolving to a real check?
        if self._wa8_is_command(body):
            sender = self._wa6_resolve_user(from_e164)
            if sender and sender.id and self._wa8_can_check(sender):
                if self._wa8_run(sender, body, from_e164, raw_from, message,
                                 has_cmd=True):
                    return True
        return None

    @api.model
    def _wa8_is_command(self, body):
        """Tight availability match: EQUALS or STARTSWITH-then-space on the
        normalised body. True / False. Never substring."""
        norm = " ".join((body or "").strip().lower().split())
        if not norm:
            return False
        return any(norm == c or norm.startswith(c + " ")
                   for c in _WA8_COMMANDS)

    @api.model
    def _wa8_strip_command(self, norm):
        """Remove the matched command prefix from a normalised-lower body;
        the remainder is the date (+ optional times) + items."""
        for c in sorted(_WA8_COMMANDS, key=len, reverse=True):
            if norm == c:
                return ""
            if norm.startswith(c + " "):
                return norm[len(c) + 1:].strip()
        return norm

    def _wa8_session_stale(self, sess):
        if not sess.last_inbound:
            return False
        return (fields.Datetime.now() - sess.last_inbound
                > timedelta(hours=_WA8_TTL_HOURS))

    # ================================================================
    # ENTITLEMENT (read-only; broad + pre-authorised)
    # ================================================================
    @api.model
    def _wa8_can_check(self, user):
        """WA-8 is PURE READ (availability only, never money), so entitlement
        is broad + pre-authorised by the locked design: the OD/superuser, the
        Neon sales / manager / crew-leader tiers, this-job crew chiefs / lead
        techs, and -- the accepted fallback -- ANY active mapped staff member.
        Since _wa6_resolve_user only returns a user that HAS an active
        bot.user, the mapped-staff fallback already covers every resolvable
        sender; the explicit role checks document intent + survive any future
        tightening of that fallback. (⚠️ DECISION WA-8: widened past WA-6/7's
        OD-only gate -- read-only, no money, so NOT a new access-power gate,
        per the user-approved spec.)"""
        if not user or not user.id:
            return False
        if self._wa6_can_initiate(user):  # OD login / Neon Superuser
            return True
        for g in ("neon_jobs.group_neon_jobs_user",
                  "neon_jobs.group_neon_jobs_manager",
                  "neon_jobs.group_neon_jobs_crew_leader"):
            if user.has_group(g):
                return True
        ej = self.env["commercial.event.job"].sudo().search(
            ["|", ("crew_chief_id", "=", user.id),
             ("lead_tech_id", "=", user.id)], limit=1)
        if ej:
            return True
        # mapped-staff fallback: an active bot.user mapping = entitled.
        return bool(self.env["neon.bot.user"].sudo().search(
            [("user_id", "=", user.id), ("active", "=", True)], limit=1))

    # ================================================================
    # RUN A CHECK (command message: parse window + items -> answer)
    # ================================================================
    def _wa8_run(self, sender, body, from_e164, raw_from, message, has_cmd,
                 audit=True):
        """Parse a full availability message (command + date + items). If it
        resolves to a REAL check -- a parseable date AND >=1 matched item --
        open the sticky av_check session and answer; True. Otherwise it did
        NOT look like an availability check: False, and the caller falls
        through (the tight parser never steals a turn)."""
        norm = " ".join((body or "").strip().lower().split())
        rest = self._wa8_strip_command(norm) if has_cmd else norm
        tz = self._wa8_tz(sender)
        now = fields.Datetime.now()
        win, items_text = self._wa8_extract_request(rest, now, tz)
        items = self._wa6_match_items(items_text) if items_text else []
        self._wa8_prepare(items)   # tag _wa8_confirmed (Face-1 confidence)
        if not (win.get("ok")
                and any(it["status"] == "matched" for it in items)):
            return False
        if audit:
            self._wa6_audit_in(from_e164, message, "wa8-check")
        if self._wa8_locked(win, now, tz):
            self._wa6_reply(raw_from, from_e164, self._wa8_lock_msg(win))
            return True
        # open (or rebind) the sticky session: the CONFIDENT matches are the
        # sticky item list (a later date/time re-checks them); the low-
        # confidence ones are PENDING suggestions a "yes" promotes; the full
        # window is kept so "yes" (and a bare TIME) re-use it. Read-only.
        confident = [it for it in items if it.get("_wa8_confirmed")]
        pending = [it for it in items
                   if it.get("status") == "matched"
                   and not it.get("_wa8_confirmed")]
        self.env["neon.wa.equip.session"]._start_av(
            from_e164, sender,
            {"items": confident, "pending": pending,
             "last_window": self._wa8_win_store(win)})
        self._wa8_reply_answer(items, win, raw_from, from_e164)
        return True

    @api.model
    def _wa8_handle_text(self, sess, body, from_e164, raw_from, message):
        """A turn on a live av_check session. A fresh availability command
        replaces the items + window (new check); anything else is treated as
        a new DATE/TIME and re-checks the SAME sticky items (the typed edit
        loop). Two-factor: the holder must STILL be entitled (re-checked)."""
        self._wa6_audit_in(from_e164, message, "wa8-text")
        sess.sudo().write({"last_inbound": fields.Datetime.now()})
        sender = sess.user_id
        if not self._wa8_can_check(sender):
            sess.sudo().write({"active": False})
            return self._wa6_reply(
                raw_from, from_e164,
                _("You're no longer authorised to check availability here."))
        buf = sess._get_buffer()
        buf = buf if isinstance(buf, dict) else {}
        norm = " ".join((body or "").strip().lower().split())
        # "yes" -> confirm the pending low-confidence suggestion(s): promote
        # them to sticky CONFIRMED items + answer them at the last window.
        if norm in _WA8_YES and buf.get("pending"):
            promoted = buf.get("pending") or []
            for it in promoted:
                it["_wa8_confirmed"] = True
            items = (buf.get("items") or []) + promoted
            buf["items"] = items
            buf["pending"] = []
            sess._set_buffer(buf)
            win = buf.get("last_window")
            if not win:
                return self._wa6_reply(
                    raw_from, from_e164, self._wa8_reprompt_text())
            return self._wa8_reply_answer(items, win, raw_from, from_e164)
        if self._wa8_is_command(body):
            # a fresh command -> a brand-new check (new items + window).
            if self._wa8_run(sender, body, from_e164, raw_from, message,
                             has_cmd=True, audit=False):
                return True
            return self._wa6_reply(
                raw_from, from_e164, self._wa8_reprompt_text())
        # otherwise: a bare date/time -> re-check the SAME sticky items.
        items = buf.get("items")
        tz = self._wa8_tz(sender)
        now = fields.Datetime.now()
        win = self._wa8_parse_window(body, now, tz)
        # a bare TIME ("2-6pm") carries no date -> re-use the last checked
        # date so "change the time" works without re-typing the date.
        last = buf.get("last_window") or {}
        if not win.get("ok") and last.get("local_date") \
                and self._wa8_time_match(body):
            win = self._wa8_parse_window(
                last["local_date"] + " " + body, now, tz)
        if not (win.get("ok") and items):
            return self._wa6_reply(
                raw_from, from_e164, self._wa8_reprompt_text())
        if self._wa8_locked(win, now, tz):
            return self._wa6_reply(
                raw_from, from_e164, self._wa8_lock_msg(win))
        # a non-"yes" turn lapses any pending suggestion (it was for the prior
        # window); refresh the window + answer the sticky items.
        buf["pending"] = []
        buf["last_window"] = self._wa8_win_store(win)
        sess._set_buffer(buf)
        return self._wa8_reply_answer(items, win, raw_from, from_e164)

    def _wa8_reprompt_text(self):
        return _(
            "Send a date to re-check the same gear (e.g. \"20 Aug\" or "
            "\"20 Aug 2-6pm\"), or \"free on <date>? <items>\" for a new "
            "check.")

    # ================================================================
    # AVAILABILITY MATH (compose the two existing engine primitives)
    # ================================================================
    def _wa8_availability(self, product_id, w_from, w_to):
        """(supply, committed, available) for the product over the UTC window.
        supply: window-independent stock (ConflictEngine); committed: the sum
        of non-cancelled holds overlapping the window (serial=1, quantity=N --
        transfer-aware for free); available = max(0, supply - committed)."""
        from odoo.addons.neon_jobs.models.neon_equipment_conflict import (
            ConflictEngine,
        )
        supply = ConflictEngine(self.env)._available_for_product(product_id)
        committed = self.env["neon.equipment.reservation"].sudo() \
            ._committed_qty_for_product(product_id, w_from, w_to)
        return supply, committed, max(0, supply - committed)

    def _wa8_competing_events(self, product_id, w_from, w_to, limit=3):
        """Distinct event-job names of the non-cancelled holds that overlap
        the window (same domain as _committed_qty_for_product) -- so a tight /
        short answer can name what it clashes with."""
        res = self.env["neon.equipment.reservation"].sudo().search([
            ("product_template_id", "=", product_id),
            ("state", "in", ("soft_hold", "confirmed", "fulfilled")),
            ("reserve_from", "<", w_to),
            ("reserve_to", ">", w_from),
        ])
        names = []
        for r in res:
            nm = r.event_job_id.sudo().name
            if nm and nm not in names:
                names.append(nm)
            if len(names) >= limit:
                break
        return names

    # ================================================================
    # FACE-1 CONFIDENCE (WA-8.1) -- a STRICTER acceptance ON TOP of the
    # shared matcher. Face 2's loose matching is safe behind its confirm
    # step; Face 1 answers directly, so a fuzzy hit whose product is a
    # DIFFERENT KIND of thing ("smoke machine" -> "...REMOTES") must be a
    # suggestion, not a silent answer. We do NOT retune _wa6_match_one.
    # ================================================================
    def _wa8_prepare(self, items):
        """Tag each matched item with _wa8_confirmed: True = answer it
        directly; False = offer it as a suggestion. not-found items stay
        not-found. Mutates + returns the list."""
        Prod = self.env["product.template"].sudo()
        for it in items:
            it["_wa8_confirmed"] = bool(
                it.get("status") == "matched" and it.get("product_id")
                and self._wa8_is_confident(
                    it["raw"], Prod.browse(it["product_id"])))
        return items

    def _wa8_is_confident(self, raw, product):
        """Confident == the matched product IS the kind of thing the user
        named: its HEAD NOUN (the last noun-like word of the name, ignoring
        numbers / dimensions / model codes) appears in the query (case +
        plural folded). Robust to dimension mismatches like '2.5' vs '2.5m'
        (head-noun, not full token containment). Empty head -> trust the
        matcher (nothing noun-like to disambiguate on)."""
        qdesc = self._wa6_parse_qty(raw)[1]
        qtoks = {self._wa8_fold(t) for t in self._wa8_words(qdesc)}
        head = self._wa8_head_noun(product.name or product.workshop_name or "")
        if not head:
            return True
        return self._wa8_fold(head) in qtoks

    @api.model
    def _wa8_words(self, text):
        """Significant query tokens (matcher-consistent: [a-z0-9.]+ minus the
        shared stopwords) -- keeps dimensions like '2.5'."""
        return [t for t in re.findall(r"[a-z0-9.]+", (text or "").lower())
                if t not in _WA6_STOP]

    @api.model
    def _wa8_head_noun(self, name):
        """The product's head noun: the LAST purely-alphabetic word (len>=3,
        non-stopword) of the name -- so model codes ('f34'), dimensions
        ('2.5m'), units and bare numbers are skipped as modifiers."""
        head = ""
        for t in re.findall(r"[a-z]+", (name or "").lower()):
            if len(t) >= 3 and t not in _WA6_STOP:
                head = t
        return head

    @staticmethod
    def _wa8_fold(t):
        """Case + naive-plural fold so 'remotes' == 'remote', 'mics' == 'mic'
        symmetrically on both query and product head."""
        t = (t or "").lower()
        return t[:-1] if (len(t) > 3 and t.endswith("s")) else t

    def _wa8_win_store(self, win):
        """Serialise a window for the session buffer (datetimes -> Odoo
        strings; the availability domain accepts the strings verbatim, so the
        stored dict is itself a valid 'win' for re-rendering on 'yes')."""
        def s(v):
            return v if isinstance(v, str) else fields.Datetime.to_string(v)
        return {"w_from": s(win["w_from"]), "w_to": s(win["w_to"]),
                "had_time": bool(win.get("had_time")),
                "time_label": win.get("time_label", ""),
                "date_label": win["date_label"],
                "local_date": win["local_date"]}

    # ================================================================
    # ANSWER RENDERING
    # ================================================================
    def _wa8_render_answer(self, items, win):
        out = []
        for it in items:
            if it.get("status") != "matched":
                sug = ((" — try: %s" % ", ".join(it["suggestions"]))
                       if it.get("suggestions") else "")
                out.append("⚠️ not found: \"%s\"%s" % (it["raw"], sug))
                continue
            if not it.get("_wa8_confirmed"):
                # WA-8.1: a low-confidence fuzzy match is NEVER answered
                # silently in this no-confirm face -- it is offered as a
                # suggestion (a 'yes' promotes + checks it).
                out.append(
                    "🔎 I don't have \"%s\" by that exact name — closest: "
                    "%s. Reply \"yes\" to check it, or refine."
                    % (it["raw"], it["product_name"]))
                continue
            pid = it["product_id"]
            req = it["qty"]
            name = it["product_name"]
            supply, committed, available = self._wa8_availability(
                pid, win["w_from"], win["w_to"])
            if available > req:
                # a spare exists -> genuinely free.
                out.append(
                    "🟢 %dx %s — free (%d available)" % (req, name, available))
            elif available == req:
                # WA-8.1: exact capacity = TIGHT, no spare (free == needed).
                comp = (self._wa8_competing_events(
                    pid, win["w_from"], win["w_to"]) if committed else [])
                clash = ((" — also booked elsewhere: %s" % ", ".join(comp))
                         if comp else "")
                out.append(
                    "🟡 %dx %s — tight, no spare (exactly %d available)%s"
                    % (req, name, available, clash))
            elif supply < req:
                # short on inventory regardless of dates.
                out.append(
                    "🔴 %dx %s — only %d in inventory (need %d)"
                    % (req, name, supply, req))
            else:
                # short because committed on these dates (mirrors
                # _short_reason's wording) -- name the clash.
                comp = self._wa8_competing_events(
                    pid, win["w_from"], win["w_to"])
                clash = ((" — clashes with %s" % ", ".join(comp))
                         if comp else "")
                out.append(
                    "🔴 %dx %s — %d already committed on these dates "
                    "(%d of %d available)%s"
                    % (req, name, supply - available, available, req, clash))
        return "\n".join(out)

    def _wa8_reply_answer(self, items, win, raw_from, from_e164):
        label = win["date_label"] + (
            " " + win["time_label"] if win.get("had_time")
            else " (full day)")
        body = _("📅 Availability for %(label)s:\n%(ans)s\n\n%(foot)s") % {
            "label": label, "ans": self._wa8_render_answer(items, win),
            "foot": self._wa8_reprompt_text()}
        return self._wa6_reply(raw_from, from_e164, body)

    # ================================================================
    # WINDOW PARSING (Harare-local -> naive UTC) + the day-before lock
    # ================================================================
    def _wa8_tz(self, user):
        name = (user.tz if user and user.tz else "") or _WA8_TZ
        try:
            return pytz.timezone(name)
        except Exception:  # noqa: BLE001
            return pytz.timezone(_WA8_TZ)

    def _wa8_local_today(self, now_utc, tz):
        return pytz.utc.localize(now_utc).astimezone(tz).date()

    @api.model
    def _wa8_time_match(self, text):
        """The FIRST plausible clock range (hours 0-23, minutes 0-59) in the
        text -- SKIPPING earlier regex hits that aren't valid times, so a
        hyphenated date like '2026-09-08' (whose '26-09' is not a clock range)
        does not swallow a real trailing '8-11am'. Returns
        (match, sh, sm, eh, em) or None."""
        for m in _WA8_TIME_RANGE.finditer(text or ""):
            try:
                h1, h2 = int(m.group(1)), int(m.group(4))
                m1 = int(m.group(2) or 0)
                m2 = int(m.group(5) or 0)
            except (TypeError, ValueError):
                continue
            if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
                continue
            ap1 = (m.group(3) or m.group(6) or "").lower()  # inherit end's ap
            ap2 = (m.group(6) or m.group(3) or "").lower()
            return (m, self._wa8_apply_ampm(h1, ap1), m1,
                    self._wa8_apply_ampm(h2, ap2), m2)
        return None

    @staticmethod
    def _wa8_apply_ampm(h, ap):
        if ap == "pm" and h != 12:
            return h + 12
        if ap == "am" and h == 12:
            return 0
        return h

    def _wa8_parse_window(self, text, now_utc, tz):
        """Parse a Harare-local window-text (date + optional time range) into
        a UTC window. NO time -> a conservative FULL DAY. Returns
        {ok, w_from, w_to (naive UTC), had_time, date_label, time_label,
        local_date(iso)} or {ok: False}."""
        text = (text or "").strip()
        if not text:
            return {"ok": False}
        had_time = False
        sh = sm = eh = em = None
        date_text = text
        tm = self._wa8_time_match(text)
        if tm:
            m, sh, sm, eh, em = tm
            had_time = True
            date_text = (text[:m.start()] + " " + text[m.end():]).strip()
        local_today = self._wa8_local_today(now_utc, tz)
        base = datetime(local_today.year, local_today.month, local_today.day)
        try:
            from dateutil import parser as dtparser
            d = dtparser.parse(date_text, dayfirst=True, fuzzy=True,
                               default=base)
        except (ValueError, OverflowError, TypeError):
            return {"ok": False}
        local_date = d.date()
        # year roll: a bare (no explicit 4-digit year) date that lands before
        # today is assumed to mean NEXT year. An explicit past year is left
        # alone (it then trips the day-before lock).
        if local_date < local_today and not _WA8_YEAR.search(date_text):
            try:
                local_date = local_date.replace(year=local_date.year + 1)
            except ValueError:
                pass
        time_label = ""
        if had_time and eh is not None:
            start_local = datetime.combine(local_date, dtime(sh % 24, sm))
            end_local = datetime.combine(local_date, dtime(eh % 24, em))
            if end_local <= start_local:
                had_time = False  # ambiguous (e.g. "9-5") -> fail safe
        if had_time:
            time_label = "%02d:%02d–%02d:%02d" % (sh % 24, sm, eh % 24, em)
        else:
            start_local = datetime.combine(local_date, dtime(0, 0, 0))
            end_local = datetime.combine(local_date, dtime(23, 59, 59))
        w_from = tz.localize(start_local).astimezone(
            pytz.utc).replace(tzinfo=None)
        w_to = tz.localize(end_local).astimezone(
            pytz.utc).replace(tzinfo=None)
        return {"ok": True, "w_from": w_from, "w_to": w_to,
                "had_time": had_time, "time_label": time_label,
                "date_label": local_date.strftime("%d %b %Y"),
                "local_date": local_date.isoformat()}

    def _wa8_extract_request(self, rest, now_utc, tz):
        """``rest`` = the message after the command. Returns
        (window_dict, items_text). The clean documented form is
        'free on <date>? <items>' (a ? / : / newline separator); without a
        separator the date (+ any time range) is peeled off the front and the
        leftover tokens are the items (best-effort)."""
        rest = (rest or "").strip()
        for sep in ("?", ":", "\n"):
            if sep in rest:
                win_text, items_text = rest.split(sep, 1)
                return (self._wa8_parse_window(win_text, now_utc, tz),
                        items_text.strip())
        # no separator: peel the date (+ time range) via fuzzy_with_tokens.
        work = rest
        timed = ""
        tm = self._wa8_time_match(work)
        if tm:
            m = tm[0]
            timed = work[m.start():m.end()]
            work = (work[:m.start()] + " " + work[m.end():]).strip()
        local_today = self._wa8_local_today(now_utc, tz)
        base = datetime(local_today.year, local_today.month, local_today.day)
        try:
            from dateutil import parser as dtparser
            _d, tokens = dtparser.parse(
                work, dayfirst=True, fuzzy_with_tokens=True, default=base)
        except (ValueError, OverflowError, TypeError):
            return {"ok": False}, ""
        items_text = " ".join(t.strip() for t in tokens if t.strip())
        date_only = work
        for t in tokens:
            ts = t.strip()
            if ts:
                date_only = date_only.replace(ts, " ", 1)
        win_text = (date_only + " " + timed).strip()
        return self._wa8_parse_window(win_text, now_utc, tz), items_text

    def _wa8_locked(self, win, now_utc, tz):
        """The day-before edit lock: a window whose date is today or already
        past is refused (re-checks are for upcoming dates)."""
        checked = fields.Date.to_date(win["local_date"])
        return self._wa8_local_today(now_utc, tz) >= checked

    def _wa8_lock_msg(self, win):
        return _(
            "🔒 %s is today or already past — availability checks are for "
            "upcoming dates. Send a future date.") % win["date_label"]
