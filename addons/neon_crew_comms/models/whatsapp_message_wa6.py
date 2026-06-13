# -*- coding: utf-8 -*-
"""B11 / WA-6 -- Crew + OD equipment face on WhatsApp (bridge).

Two faces, both MAPPED staff, both reusing the proven equipment actions +
WA machinery (NO reimplementation of equipment / reservation / conflict
logic):

  FACE 2 -- FINALIZE (OD or the routed-to crew chief / lead tech). The OD
    initiates from an Odoo header button (mirrors commercial.job
    action_notify_crew) -> a 3-button WhatsApp choice [I'll finalize] /
    [Send to crew chief] / [Open in Odoo]. The finalizer free-texts the
    gear list; a fresh matcher resolves each item to a product.template +
    qty; the interpreted list comes back for Confirm / Fix-an-item; on
    confirm each line is created + allocated via the PROVEN line.create ->
    auto-spawn reservations -> _find_available_units/_bind path. The model
    is UNGATED for create/allocate, so WA-6 OWNS this gate.

  FACE 3 -- WAREHOUSE checkout / check-in (no on-site step). Reuses
    line.action_checkout / event_job.action_checkout_all_equipment and the
    neon.equipment.checkin.wizard headlessly. NARROW per-job gate: only
    THIS event job's lead_tech_id or crew_chief.

ROUTING: intercepted in handle_inbound BEFORE super() (the WA-2 crew
pattern), so a WA-6 tap never reaches the Copilot and a finalize free-text
turn is grabbed only while that staff phone holds a live finalize session
(otherwise it falls through to the Copilot unchanged -- zero WA-4 regress).

TWO-FACTOR everywhere: the HMAC payload (wa_payload) proves integrity; the
SECOND factor is the sender's phone -> resolved Odoo user, re-checked
against the job's role on every turn (a stolen-but-valid payload tapped
from another phone resolves to a non-role user and is refused).

AUDIT: Face-3 write calls run as the REAL tapping user (phone -> bot.user
-> res.users) so neon.equipment.movement.actor_id is the real operator;
the model actions self-escalate (sudo) internally for the privileged
writes. Face-2 creates NO movements (reservations carry no actor), so its
writes run sudo after the gate -- no audit fidelity is lost.
"""
import json
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.neon_channels.models import wa_payload
from odoo.addons.neon_channels.models.phone_utils import to_e164

_logger = logging.getLogger(__name__)

# --- identity (XML ids / login params only -- NEVER a numeric group id;
#     group ids drift between prod and local, see the "group-58" lesson) -
_WA6_OD_PARAM = "neon_channels.wa6_od_login"
_WA6_OD_DEFAULT = "robin@neonhiring.co.zw"
_WA6_SUPERUSER_GROUP = "neon_core.group_neon_superuser"

# --- HARD idempotency lock: per-event-job advisory lock so concurrent
#     confirm taps run the finalize EXACTLY once. FRESH namespace (NOT
#     WA-5's 5593500). Non-blocking; auto-released at commit/rollback.
_WA6_LOCK_NS = 5593600

# --- proactive template (cold window). Like WA-2/WA-5 templates, the
#     exact name/format is confirmed at go-live (Meta approval); in-window
#     interactive is the proven path for the real-phone proof.
_WA6_TPL_INITIATE = "wa6_equip_finalize"
_WA6_TPL_LANG = "en_US"

# --- free-text matcher --------------------------------------------------
# Tokens we never score on. 'x' is a qty marker stripped before tokenising.
_WA6_STOP = {
    "the", "a", "an", "of", "and", "for", "with", "unit", "units", "pcs",
    "pc", "pce", "pieces", "piece", "set", "sets", "x", "plus", "off"}

# Generic equipment nouns that add NO product-distinguishing meaning -- used by
# the confirmed-alias product short-circuit so "smoke machine"/"smoke machines"
# still resolves to the confirmed 'smoke' product (the noun is noise, the slang
# is the signal). NOT in _WA6_STOP because they ARE meaningful tokens elsewhere
# (e.g. token-scoring a real "machine"-named product).
_WA6_GENERIC_NOUN = {"machine", "machines"}

# keyword -> category CODE. Phrase synonyms (with a space) match as a
# substring; single tokens match on a word boundary. Resolved to the live
# neon.equipment.category by code at match time (the 9 seeded codes).
_WA6_CAT_SYNONYMS = {
    "trussing": ["truss", "trussing", "f34", "f44", "goalpost", "goal post",
                 "tower", "base plate", "baseplate", "clamp", "clamps",
                 "totem", "totems"],
    # NOTE (proof #3): bare "led" is REMOVED here -- it is shared by visual
    # (LED screens) AND lighting (LED cans), so it wrongly pulled "led cans"
    # into visual. "led screen" / "led wall" phrases stay; a screen is found by
    # "screen". Bare "wall"/"monitor" dropped too (ambiguous with staging /
    # stage-monitor).
    "visual": ["screen", "screens", "led wall", "ledwall", "led screen",
               "ledscreen", "projector", "projection", "plasma", "tv", "tvs",
               "display", "switcher", "absen", "3x2", "2x3", "4x3"],
    "lighting": ["light", "lights", "lighting", "par", "pars", "wash",
                 "moving head", "mover", "movers", "spot", "beam",
                 "uplighter", "uplighters", "uplight", "blinder", "strobe",
                 "molefay", "molefays", "can", "cans", "zoom", "rgbwauv",
                 "rgbw"],
    "sound": ["sound", "speaker", "speakers", "mic", "mics", "microphone",
              "microphones", "mixer", "qu16", "qu24", "di box", "di", "amp",
              "amplifier", "sub", "subs", "subwoofer", "wedge", "wedges",
              "array", "line array", "foldback", "pa", "monitor wedge"],
    "cabling": ["cable", "cables", "xlr", "distro", "distribution",
                "powercon", "extension", "extensions", "adaptor", "adapter",
                "multicore", "snake", "16a", "32a", "63a", "13a", "plug",
                "iec", "jack", "trs"],
    "laptops": ["laptop", "laptops", "macbook", "lenovo", "notebook", "mac",
                "dell", "thinkpad"],
    "staging": ["stage", "staging", "deck", "decks", "riser", "risers",
                "podium", "rostra", "rostrum", "ramp", "steps", "skirt"],
    "dance_floor": ["dancefloor", "dance floor", "starlit", "parquet",
                    "dance floor panel"],
    "effects": ["haze", "hazer", "smoke", "fog", "fogger", "gel", "gels",
                "confetti", "co2", "sparkular", "cold spark", "bubble",
                "bubbles", "snow"],
}

# --- Resolver v2 (the matcher funnel) -------------------------------------
# pg_trgm category-scoped lexical rank thresholds (Postgres pg_trgm v1.6 live
# on prod). Tuned against the golden corpus at build; constants so re-tuning is
# non-structural. STRONG = auto-accept the top hit; FLOOR = below it there is no
# deterministic winner -> hand the shortlist to the grounded LLM pick.
_WA6_TRGM_STRONG = 0.55   # top sim >= this AND margin >= MARGIN -> 'strong'
_WA6_TRGM_MARGIN = 0.12   # winner must beat #2 by this to auto-accept
_WA6_TRGM_FLOOR = 0.30    # top sim below this -> straight to the shortlist
_WA6_SHORTLIST_K = 6      # how many real names the grounded pick chooses among
# Plurals we must NOT fold (a trailing 's' that is part of the stem). The fold
# also skips '...ss' words, but these are explicit safety pins.
_WA6_PLURAL_KEEP = {"truss", "trussing", "bass", "press", "class", "glass"}

# WA-6.1 Face-3 dispatch -- crew-initiated checkout / check-in commands.
# Matched by EQUALS or STARTSWITH-then-space on the normalised (lowered,
# whitespace-collapsed) body -- NEVER substring -- AND only fired for a
# mapped lead_tech/crew_chief who has >=1 eligible job. So normal chat
# ("can I check out the venue options") never triggers: it neither equals
# nor startswith a command phrase, and even if it did the sender has no
# eligible job. Tight, unambiguous phrases only (no bare "returned").
_WA6_CHECKOUT_COMMANDS = (
    "check out equipment", "check out gear", "checkout", "check out")
_WA6_CHECKIN_COMMANDS = (
    "check in equipment", "check in gear", "return equipment",
    "checkin", "check in")
# WA-6.2 Face-2 dispatch -- OD-initiated finalize command. Same tight
# match (equals / startswith-then-space, never substring). Both spellings
# (Zimbabwe writes British English). "I'll finalize it later" never matches
# (starts with "i'll", not "finalize"); only an OD/superuser with >=1
# eligible job is grabbed -- everyone else falls through unchanged.
_WA6_FINALIZE_COMMANDS = (
    "finalize equipment", "finalise equipment", "finalize", "finalise")


class WhatsAppMessageWA6(models.Model):
    _inherit = "neon.whatsapp.message"

    # ================================================================
    # ENTRY -- called from neon_crew_comms handle_inbound BEFORE super()
    # ================================================================
    @api.model
    def _wa6_maybe_intercept(self, message):
        """Returns True if this inbound is a WA-6 tap (handled here) or a
        finalize free-text turn for a phone with a live session; else None
        so the WA-5 / Copilot router runs unchanged."""
        raw_from = message.get("from")
        from_e164 = to_e164(raw_from)
        mtype = message.get("type")
        # 1) a button / list tap carrying our HMAC payload
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
            if decoded and decoded[0].startswith("wa6_"):
                self._wa6_handle_tap(
                    decoded[0], decoded[1], from_e164, raw_from, message)
                return True
            return None  # not a WA-6 tap -> WA-5 / Copilot handles it
        # 2) free text from a staff member mid-finalize
        if mtype == "text":
            body = ((message.get("text") or {}).get("body") or "")
            # don't hijack an opt-out keyword mid-finalize.
            if body.strip().upper() in {
                    "STOP", "START", "UNSUBSCRIBE", "STOPALL", "UNSTOP",
                    "RESUME"}:
                return None
            sess = self.env["neon.wa.equip.session"]._active_for_phone(
                from_e164)
            if sess:
                self._wa6_handle_text(
                    sess, body, from_e164, raw_from, message)
                return True
            # WA-6.1: no active session -> is this a Face-3 command from a
            # mapped lead_tech/crew_chief who actually HAS eligible gear?
            # Grab ONLY then; a non-command, an unmapped phone, or a mapped
            # user with no eligible job all fall through UNCHANGED (Copilot
            # / client lane) -- the parser never steals a turn.
            cmd = self._wa6_is_command(body)
            if cmd:
                sender = self._wa6_resolve_user(from_e164)
                if sender and sender.id:
                    if cmd == "finalize":
                        # WA-6.2: WhatsApp-initiated finalize is OD/superuser
                        # ONLY. A mapped NON-OD ("finalize" from a crew
                        # member) is NOT grabbed -> falls through to the
                        # Copilot (the Odoo button + routed-chief paths cover
                        # non-OD finalize). Unmapped never reaches here
                        # (sender empty -> client lane). An OD with no
                        # from-scratch job also falls through. The parser
                        # never steals a turn.
                        if self._wa6_can_initiate(sender):
                            jobs = self._wa6_eligible_finalize_jobs(sender)
                            if jobs:
                                self._wa6_start_finalize_flow(
                                    sender, jobs, from_e164, raw_from,
                                    message)
                                return True
                    else:
                        jobs = (self._wa6_eligible_checkout_jobs(sender)
                                if cmd == "checkout"
                                else self._wa6_eligible_checkin_jobs(sender))
                        if jobs:
                            self._wa6_start_pick_flow(
                                cmd, sender, jobs, from_e164, raw_from,
                                message)
                            return True
        return None

    @api.model
    def _wa6_is_command(self, body):
        """Tight Face-3 command match: EQUALS or STARTSWITH-then-space on
        the normalised body. Returns 'checkout' / 'checkin' / None. Never
        substring (so 'can I check out the venue' does NOT match)."""
        norm = " ".join((body or "").strip().lower().split())
        if not norm:
            return None

        def hit(cmds):
            return any(norm == c or norm.startswith(c + " ") for c in cmds)

        if hit(_WA6_CHECKOUT_COMMANDS):
            return "checkout"
        if hit(_WA6_CHECKIN_COMMANDS):
            return "checkin"
        if hit(_WA6_FINALIZE_COMMANDS):
            return "finalize"
        return None

    @api.model
    def _wa6_handle_tap(self, intent, parts, from_e164, raw_from, message):
        self._wa6_audit_in(from_e164, message, intent)
        try:
            if intent in ("wa6_fin_self", "wa6_fin_route", "wa6_fin_odoo"):
                return self._wa6_route_initiate(
                    intent, parts, from_e164, raw_from)
            if intent in ("wa6_confirm", "wa6_fix", "wa6_fixrow"):
                return self._wa6_route_review(
                    intent, parts, from_e164, raw_from)
            if intent in ("wa6_co_all", "wa6_co_item", "wa6_co_line"):
                return self._wa6_route_checkout(
                    intent, parts, from_e164, raw_from)
            if intent in ("wa6_ci_good", "wa6_ci_flag"):
                return self._wa6_route_checkin(
                    intent, parts, from_e164, raw_from)
        except Exception as e:  # noqa: BLE001 -- a tap must never 500
            _logger.error("WA-6 tap routing failed (intent=%s): %s",
                          intent, e, exc_info=True)
            return self._wa6_reply(
                raw_from, from_e164,
                _("Sorry -- something went wrong with that. Please try "
                  "again."))
        return self._wa6_reply(
            raw_from, from_e164, _("I couldn't route that selection."))

    # ================================================================
    # IDENTITY RESOLUTION + GATES
    # ================================================================
    @api.model
    def _wa6_resolve_user(self, from_e164):
        """The Odoo user mapped to this WhatsApp number (active bot.user),
        or an empty recordset. bot.user.phone_number is unique, so there's
        no >1-match ambiguity."""
        empty = self.env["res.users"].sudo().browse()
        if not from_e164:
            return empty
        bots = self.env["neon.bot.user"].sudo().search(
            [("active", "=", True)])
        match = bots.filtered(
            lambda b: to_e164(b.phone_number or "") == from_e164)[:1]
        return match.user_id if match else empty

    @api.model
    def _wa6_user_phone(self, user):
        """The single best sendable E.164 for a user (bot.user first, then
        partner mobile/phone). False if none."""
        if not user or not user.id:
            return False
        for b in self.env["neon.bot.user"].sudo().search(
                [("user_id", "=", user.id), ("active", "=", True)]):
            e = to_e164(b.phone_number or "")
            if e:
                return e
        p = user.partner_id
        for raw in (p.mobile, p.phone):
            e = to_e164(raw or "")
            if e:
                return e
        return False

    @api.model
    def _wa6_od_user(self):
        """The OD/initiator, resolved by LOGIN param (default Robin). Empty
        recordset if unset/missing."""
        login = self.env["ir.config_parameter"].sudo().get_param(
            _WA6_OD_PARAM, _WA6_OD_DEFAULT)
        if not login:
            return self.env["res.users"].sudo().browse()
        return self.env["res.users"].sudo().search(
            [("login", "=", login)], limit=1)

    @api.model
    def _wa6_can_initiate(self, user):
        """Who may initiate / finalize-as-OD: the configured OD login OR a
        Neon Superuser (the away-fallback). Gated on the XML group id, NEVER
        a numeric id."""
        if not user or not user.id:
            return False
        if user.has_group(_WA6_SUPERUSER_GROUP):
            return True
        od = self._wa6_od_user()
        return bool(od and od.id == user.id)

    @api.model
    def _wa6_can_finalize(self, event_job, user):
        """Face 2 gate (the model is ungated -- this IS the safety):
        OD/superuser OR THIS event job's crew_chief / lead_tech. Per-record
        (per-job): a crew chief of job A fails for job B because
        jobB.crew_chief_id != that user."""
        if not user or not user.id or not event_job:
            return False
        if self._wa6_can_initiate(user):
            return True
        ej = event_job.sudo()
        return (ej.crew_chief_id.id == user.id) \
            or (ej.lead_tech_id.id == user.id)

    @api.model
    def _wa6_can_warehouse(self, event_job, user):
        """Face 3 gate -- NARROW per-job: ONLY this event job's lead_tech_id
        or crew_chief (matched per-record). NOT OD/superuser, NOT the broad
        manager/crew_leader groups -- the WhatsApp warehouse surface is the
        two per-job operational roles only (managers do warehouse moves in
        Odoo). The underlying model action re-applies its own broader
        authority at execution (manager/crew_leader/crew-chief) as
        defense-in-depth; in normal config lead_tech is in the crew_leader
        group and crew_chief passes via _is_crew_chief_of_job, so the two
        gates align. (⚠️ DECISION WA-6.)"""
        if not user or not user.id or not event_job:
            return False
        ej = event_job.sudo()
        return (ej.lead_tech_id.id == user.id) \
            or (ej.crew_chief_id.id == user.id)

    @api.model
    def _wa6_route_target(self, event_job):
        """'Send to crew chief' target: crew_chief_id, else lead_tech_id
        (precedence). Empty recordset if neither is set."""
        ej = event_job.sudo()
        return ej.crew_chief_id or ej.lead_tech_id

    # ---- payload + lock --------------------------------------------
    def _wa6_secret(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "database.secret") or ""

    def _wa6_payload(self, intent, *parts):
        return wa_payload.encode(self._wa6_secret(), intent, *parts)

    def _wa6_try_lock(self, event_job):
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            (_WA6_LOCK_NS, int(event_job.id)))
        return bool(self.env.cr.fetchone()[0])

    def _wa6_first_name(self, user):
        return ((user.name or user.login or "there").split()
                or ["there"])[0]

    def _wa6_err(self, e):
        """A UserError's message is safe to surface to the crew member; any
        other exception is logged and returns a generic line."""
        if isinstance(e, UserError):
            return e.args[0] if e.args else str(e)
        _logger.error("WA-6 action failed: %s", e, exc_info=True)
        return _("Sorry -- that didn't go through. Please try again or use "
                 "Odoo.")

    def _wa6_odoo_link(self, model, res_id):
        base = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url") or ""
        return "%s/web#id=%s&model=%s&view_type=form" % (base, res_id, model)

    # ================================================================
    # AUDIT + REPLY HELPERS
    # ================================================================
    def _wa6_audit_in(self, from_e164, message, label):
        self.sudo().create({
            "name": message.get("id") or "wa6-in-%s" % from_e164,
            "direction": "inbound", "phone_number": from_e164 or "",
            "message_body": ((message.get("text") or {}).get("body")
                             or (message.get("button") or {}).get("text")
                             or label),
            "message_type": message.get("type") or "text",
            "state": "received", "raw_payload": str(message)})

    def _wa6_audit_out(self, phone, body, mtype="text"):
        self.sudo().create({
            "name": "wa6-out-%s" % phone, "direction": "outbound",
            "phone_number": phone, "message_body": body,
            "message_type": mtype, "state": "sent"})

    def _wa6_reply(self, raw_from, from_e164, text):
        self.sudo().send_message(raw_from, text)
        self._wa6_audit_out(from_e164 or raw_from, text, "text")
        return True

    def _wa6_send_buttons(self, raw_from, from_e164, body, buttons):
        ok = self.sudo().send_buttons(raw_from, body, buttons)
        if not ok:
            # numbered text fallback (titles only -- ids are HMAC payloads).
            body2 = body + "\n" + "\n".join(
                "%d) %s" % (i + 1, b["title"])
                for i, b in enumerate(buttons))
            self.sudo().send_message(raw_from, body2)
        self._wa6_audit_out(
            from_e164 or raw_from, body, "interactive" if ok else "text")
        return True

    def _wa6_send_list(self, raw_from, from_e164, body, button_text, rows):
        ok = self.sudo().send_list(
            raw_from, body, button_text,
            [{"title": "Options", "rows": rows}])
        if not ok:
            self.sudo().send_message(raw_from, body)
        self._wa6_audit_out(
            from_e164 or raw_from, body, "interactive" if ok else "text")
        return True

    # ================================================================
    # WINDOW-AWARE STAFF NOTIFY (anchored to the event job; never lost)
    # ================================================================
    def _wa6_notify(self, bot_user, interactive, body, template_name,
                    template_params, qr_payloads, event_job,
                    activity_user, activity_summary):
        """Window OPEN -> rich interactive; CLOSED -> a UTILITY template
        (re-opens the window so the quick-reply tap works); ALWAYS an Odoo
        activity on the event job so the finalize hand-off is never lost.
        Reuses WA-5's generic _wa5_window_open + the base send primitives."""
        if bot_user and self._wa5_window_open(bot_user.phone_number):
            try:
                path = self.sudo().send_interactive_or_text(
                    bot_user.phone_number, interactive, body)
                self._wa6_audit_out(
                    bot_user.phone_number, body, path or "interactive")
            except Exception as e:  # noqa: BLE001
                _logger.warning(
                    "WA-6 notify (interactive) failed job %s: %s",
                    event_job.id, e)
        elif bot_user:
            try:
                partner = bot_user.user_id.partner_id
                res = self.sudo().send_template(
                    bot_user.phone_number, template_name,
                    language=_WA6_TPL_LANG, body_params=template_params,
                    quick_reply_payloads=qr_payloads,
                    recipient_partner=partner,
                    audit_body="[%s] %s" % (template_name, activity_summary))
                if not (res or {}).get("ok"):
                    _logger.warning(
                        "WA-6 template %s NOT delivered to %s (%s) -- the "
                        "Odoo activity is the fallback (job %s).",
                        template_name, bot_user.phone_number,
                        (res or {}).get("reason"), event_job.id)
            except Exception as e:  # noqa: BLE001
                _logger.warning(
                    "WA-6 notify (template) failed job %s: %s",
                    event_job.id, e)
        self._wa6_activity(
            event_job, activity_user, activity_summary, body)

    def _wa6_activity(self, event_job, user, summary, note):
        try:
            root_id = self.env.ref("base.user_root").id
            target = user if (user and user.id and user.id != root_id) \
                else None
            if not target:
                return
            event_job.sudo().activity_schedule(
                "mail.mail_activity_data_todo",
                summary=summary, note=note, user_id=target.id)
        except Exception as e:  # noqa: BLE001 -- never break the flow
            _logger.warning(
                "WA-6 activity skipped (job %s): %s", event_job.id, e)

    # ================================================================
    # FACE 2 -- OD INITIATE (called from the event_job Odoo action)
    # ================================================================
    @api.model
    def _wa6_send_initiate(self, event_job, recipient_user):
        """Send the initiator their 3-button finalize choice for this job.
        Returns {ok, reason} for the Odoo action's notification."""
        bu = self.env["neon.bot.user"].sudo().search(
            [("user_id", "=", recipient_user.id), ("active", "=", True)],
            limit=1)
        if not bu:
            return {"ok": False, "reason": "no_botuser"}
        ej = event_job.sudo()
        body = (
            "\U0001F4E6 Equipment finalize for %s (%s) -- %s.\n\n"
            "Choose an option below."
            % (ej.name, ej.partner_id.name or "client",
               ej.event_date or "date TBC"))
        buttons = self._wa6_finalize_buttons(ej)
        interactive = {"kind": "buttons", "body": body[:1024],
                       "buttons": buttons}
        # cold-window template carries the single self-finalize quick-reply
        # (the <=1 reply-button cold-template limit; in-window shows 3).
        self._wa6_notify(
            bu, interactive, body, _WA6_TPL_INITIATE,
            [self._wa6_first_name(recipient_user), ej.name],
            [self._wa6_payload("wa6_fin_self", ej.id)],
            ej, recipient_user,
            _("Finalize equipment for %s") % ej.name)
        return {"ok": True, "reason": "sent"}

    def _wa6_prompt_text(self, event_job):
        return _(
            "Send me the equipment list for %s as one message -- e.g. "
            "\"2x screen 3x2, 2.5 black truss x4, 17a distro x2\". I'll "
            "match each item to the catalogue and show you the list to "
            "confirm.") % event_job.sudo().name

    # ---- initiate-choice taps --------------------------------------
    @api.model
    def _wa6_route_initiate(self, intent, parts, from_e164, raw_from):
        ej = self._wa6_event_job_from_parts(parts)
        if not ej:
            return self._wa6_reply(
                raw_from, from_e164,
                _("That event job is no longer available."))
        sender = self._wa6_resolve_user(from_e164)
        # two-factor: the initiator must BE OD/superuser (the 3-button was
        # sent to them); a stolen payload from another phone resolves to a
        # non-initiator user -> refused.
        if not self._wa6_can_initiate(sender):
            return self._wa6_reply(
                raw_from, from_e164,
                _("Only the OD (or a superuser) can finalize from here."))
        if intent == "wa6_fin_odoo":
            return self._wa6_reply(
                raw_from, from_e164,
                _("\U0001F4CB Open the event job in Odoo:\n%s")
                % self._wa6_odoo_link("commercial.event.job", ej.id))
        if intent == "wa6_fin_self":
            self.env["neon.wa.equip.session"]._start(from_e164, sender, ej)
            return self._wa6_reply(
                raw_from, from_e164, self._wa6_prompt_text(ej))
        # wa6_fin_route -> crew chief / lead tech
        target = self._wa6_route_target(ej)
        if not target:
            return self._wa6_reply(
                raw_from, from_e164,
                _("No crew chief or lead tech is assigned to %s yet -- "
                  "assign one in Odoo first.") % ej.name)
        tphone = self._wa6_user_phone(target)
        if not tphone:
            return self._wa6_reply(
                raw_from, from_e164,
                _("%s has no WhatsApp number mapped -- can't route the "
                  "finalize to them.") % (target.name or target.login))
        self.env["neon.wa.equip.session"]._start(tphone, target, ej)
        tbu = self.env["neon.bot.user"].sudo().search(
            [("user_id", "=", target.id), ("active", "=", True)], limit=1)
        body = (
            "\U0001F4E6 You've been asked to finalize equipment for "
            "%s (%s).\n%s"
            % (ej.name, ej.partner_id.name or "client",
               self._wa6_prompt_text(ej)))
        interactive = {
            "kind": "buttons", "body": body[:1024],
            "buttons": [{"id": self._wa6_payload("wa6_fin_odoo", ej.id),
                         "title": "\U0001F4CB Open in Odoo"}]}
        self._wa6_notify(
            tbu, interactive, body, _WA6_TPL_INITIATE,
            [self._wa6_first_name(target), ej.name],
            [self._wa6_payload("wa6_fin_odoo", ej.id)],
            ej, target, _("Finalize equipment for %s") % ej.name)
        return self._wa6_reply(
            raw_from, from_e164,
            _("✅ Sent to %s to finalize %s.")
            % (target.name or target.login, ej.name))

    # ================================================================
    # FACE 2 -- FINALIZE FSM (free text -> review -> confirm / fix)
    # ================================================================
    @api.model
    def _wa6_handle_text(self, sess, body, from_e164, raw_from, message):
        self._wa6_audit_in(from_e164, message, "wa6-text")
        sess.sudo().write({"last_inbound": fields.Datetime.now()})
        # WA-6.1: a checkout / check-in pick session routes to the pick
        # handler (warehouse gate, re-checked when the buttons are sent /
        # tapped) -- NOT the finalize path below.
        if sess.step in ("co_pick", "ci_pick"):
            return self._wa6_handle_pick(sess, body, from_e164, raw_from)
        # WA-6.2: a finalize-job-pick session routes to its own pick handler
        # (OD gate re-checked there) -- NOT the finalize free-text path.
        if sess.step == "fin_pick":
            return self._wa6_handle_finalize_pick(
                sess, body, from_e164, raw_from)
        # defense: the session's user must still be allowed to finalize it.
        if not self._wa6_can_finalize(sess.event_job_id, sess.user_id):
            sess.sudo().write({"active": False})
            return self._wa6_reply(
                raw_from, from_e164,
                _("You're no longer authorised to finalize this job."))
        if sess.step == "await_items":
            items = self._wa6_match_items(body)
            if not items:
                return self._wa6_reply(
                    raw_from, from_e164,
                    _("I couldn't read any items there. Send the gear list "
                      "as one message, e.g. \"2x screen, truss x4\"."))
            sess._set_buffer(items)
            sess.sudo().write({"step": "review"})
            return self._wa6_present_review(sess, raw_from, from_e164)
        if sess.step == "fixing":
            idx = sess.fix_index
            buf = sess._get_buffer()
            if idx < 0 or idx >= len(buf):
                sess.sudo().write({"step": "review", "fix_index": -1})
                return self._wa6_present_review(sess, raw_from, from_e164)
            if body.strip().upper() == "REMOVE":
                buf.pop(idx)
            else:
                buf[idx] = self._wa6_match_one(body)
            sess._set_buffer(buf)
            sess.sudo().write({"step": "review", "fix_index": -1})
            return self._wa6_present_review(sess, raw_from, from_e164)
        # review + stray free text -> re-show the list with the buttons.
        return self._wa6_present_review(sess, raw_from, from_e164)

    def _wa6_present_review(self, sess, raw_from, from_e164):
        buf = sess._get_buffer()
        if not buf:
            sess.sudo().write({"step": "await_items"})
            return self._wa6_reply(
                raw_from, from_e164,
                _("The list is empty now. Send the gear list again."))
        n_bad = sum(1 for it in buf if it["status"] != "matched")
        tail = (_("Tap Confirm to reserve these, or Fix an item.")
                if not n_bad else
                _("%d item(s) need fixing before I can reserve. Tap Fix an "
                  "item.") % n_bad)
        body = _("Here's what I matched for %s:\n%s\n\n%s") % (
            sess.event_job_id.sudo().name,
            self._wa6_render_buffer(buf), tail)
        buttons = [
            {"id": self._wa6_payload("wa6_confirm", sess.id),
             "title": "✅ Confirm"},
            {"id": self._wa6_payload("wa6_fix", sess.id),
             "title": "✏️ Fix an item"},
        ]
        return self._wa6_send_buttons(raw_from, from_e164, body, buttons)

    def _wa6_render_buffer(self, buf):
        out = []
        for i, it in enumerate(buf, 1):
            if it["status"] == "matched":
                out.append("%d. ✅ %dx %s"
                           % (i, it["qty"], it["product_name"]))
            else:
                sug = ((" — try: %s" % ", ".join(it["suggestions"]))
                       if it.get("suggestions") else "")
                out.append("%d. ⚠️ not found: \"%s\"%s"
                           % (i, it["raw"], sug))
        return "\n".join(out)

    # ---- review taps -----------------------------------------------
    @api.model
    def _wa6_route_review(self, intent, parts, from_e164, raw_from):
        sess = self._wa6_session_from_parts(parts)
        if not sess or not sess.active:
            return self._wa6_reply(
                raw_from, from_e164,
                _("That finalize session has ended. Ask the OD to start it "
                  "again."))
        # two-factor: the tapper's phone must match the session's bound
        # phone (the session was opened only for an authorised holder).
        if from_e164 != sess.phone_number:
            _logger.warning(
                "WA-6 review tap phone mismatch: %s != session %s",
                from_e164, sess.phone_number)
            return self._wa6_reply(
                raw_from, from_e164,
                _("This finalize isn't linked to your number."))
        if not self._wa6_can_finalize(sess.event_job_id, sess.user_id):
            return self._wa6_reply(
                raw_from, from_e164,
                _("You're no longer authorised to finalize this job."))
        if intent == "wa6_fix":
            return self._wa6_tap_fix(sess, raw_from, from_e164)
        if intent == "wa6_fixrow":
            return self._wa6_tap_fixrow(sess, parts, raw_from, from_e164)
        return self._wa6_tap_confirm(sess, raw_from, from_e164)

    def _wa6_tap_fix(self, sess, raw_from, from_e164):
        buf = sess._get_buffer()
        if not buf:
            return self._wa6_present_review(sess, raw_from, from_e164)
        rows = []
        for i, it in enumerate(buf):
            label = (("%dx %s" % (it["qty"], it["product_name"]))
                     if it["status"] == "matched"
                     else ("? %s" % it["raw"]))
            rows.append({"id": self._wa6_payload("wa6_fixrow", sess.id, i),
                         "title": label[:24], "description": ""})
        return self._wa6_send_list(
            raw_from, from_e164, _("Which item should I fix?"),
            "Pick item", rows)

    def _wa6_tap_fixrow(self, sess, parts, raw_from, from_e164):
        if len(parts) < 2 or not str(parts[1]).isdigit():
            return self._wa6_present_review(sess, raw_from, from_e164)
        idx = int(parts[1])
        buf = sess._get_buffer()
        if idx < 0 or idx >= len(buf):
            return self._wa6_present_review(sess, raw_from, from_e164)
        sess.sudo().write({"step": "fixing", "fix_index": idx})
        return self._wa6_reply(
            raw_from, from_e164,
            _("Retype item #%d (e.g. \"2x screen 3x2\"), or reply REMOVE to "
              "drop it. Current: \"%s\".") % (idx + 1, buf[idx]["raw"]))

    def _wa6_tap_confirm(self, sess, raw_from, from_e164):
        buf = sess._get_buffer()
        if not buf:
            return self._wa6_present_review(sess, raw_from, from_e164)
        bad = [it for it in buf if it["status"] != "matched"]
        if bad:
            return self._wa6_reply(
                raw_from, from_e164,
                _("%d item(s) still need fixing: %s. Tap Fix an item first.")
                % (len(bad), ", ".join('"%s"' % b["raw"] for b in bad)))
        # HARD idempotency: one finalize per job per transaction.
        if not self._wa6_try_lock(sess.event_job_id):
            return self._wa6_reply(
                raw_from, from_e164,
                _("That's being processed -- one moment."))
        ej = sess.event_job_id.sudo()
        EqLine = self.env["commercial.event.job.equipment.line"].sudo()
        results = []
        for it in buf:
            # P5.M11 unified path: create the line (auto-spawns the right
            # reservation shape -- N unit rows for serial, ONE COUNT row
            # for quantity) then action_allocate() (binds units / reserves
            # the count). It returns {ok, allocated, requested, reason};
            # the reason already distinguishes "only N in inventory" from
            # "M committed on those dates" (honest short message). Face 2
            # writes NO movements, so sudo here loses no audit fidelity;
            # the gate already ran in the real-user context above.
            line = EqLine.create({
                "event_job_id": ej.id,
                "product_template_id": it["product_id"],
                "quantity_planned": it["qty"]})
            res = line.action_allocate()
            results.append((it["product_name"], it["qty"], res))
        sess.sudo().write({"step": "done", "active": False})
        lines_txt = "\n".join(
            ("✅ %s x%d (reserved %d)"
             % (n, q, res.get("allocated", 0))) if res.get("ok")
            else ("⚠️ %s x%d — %s"
                  % (n, q, res.get("reason") or _("could not reserve")))
            for n, q, res in results)
        any_short = any(not res.get("ok") for _n, _q, res in results)
        tail = (_("\n\nThe ⚠️ lines couldn't be fully reserved -- check in "
                  "Odoo.")) if any_short else ""
        return self._wa6_reply(
            raw_from, from_e164,
            _("✅ Finalized %s:\n%s%s") % (ej.name, lines_txt, tail))

    # ================================================================
    # FACE 2 -- FREE-TEXT MATCHER (built fresh; nothing to reuse)
    # ================================================================
    @api.model
    def _wa6_match_items(self, text):
        raw_items = re.split(r"[,\n;]+|\s+and\s+", text or "", flags=re.I)
        out = []
        for raw in raw_items:
            raw = raw.strip()
            if raw:
                out.append(self._wa6_match_one(raw))
        return out

    @api.model
    def _wa6_parse_qty(self, raw):
        """(qty, desc). 'truss x4'/'x4 truss' -> 4; '4x screen' -> 4;
        'qty 4' -> 4; default 1. A DIMENSION ('3x2', '3 x 2', '6m x 2m') is
        NEVER a qty (proof #3: '3 x 2 screen' must keep the size, not read 3) --
        dimensions are masked out before the qty scan."""
        s = " " + (raw or "").strip().lower() + " "
        # mask dimensions (digit [m] x digit [m]) so they can't be read as qty.
        masked = s
        for dm in re.finditer(
                r"\d+(?:\.\d+)?\s*m?\s*[x×]\s*\d+(?:\.\d+)?\s*m?", s):
            masked = (masked[:dm.start()] + (" " * (dm.end() - dm.start()))
                      + masked[dm.end():])
        m = re.search(r"(?:^|\s)x\s*(\d+)(?=\s|$)", masked)
        if not m:
            m = re.search(r"(?:^|\s)(\d+)\s*x(?=\s|$)", masked)
        if not m:
            m = re.search(r"(?:^|\s)qty\.?\s*(\d+)(?=\s|$)", masked)
        if not m:
            # Resolver v2: a bare LEADING count -- "4 blinders" -> qty 4. Runs on
            # the MASKED string, so a dimension/spec ("3 x 2", "4x100") is
            # already blanked and never read here (its leading int was masked
            # out). Requires the next char after the count to be a letter, so a
            # stray trailing/standalone number is not grabbed.
            m = re.search(r"^\s*(\d+)\s+(?=[a-z])", masked)
        qty = 1
        if m:
            qty = max(1, int(m.group(1)))
            s = s[:m.start()] + " " + s[m.end():]   # indices align (mask kept length)
        return qty, " ".join(s.split())

    @api.model
    def _wa6_parse_dims(self, text):
        """(w, h) floats from a 'N x M' / 'NxM' / 'Nm x Mm' size, else None."""
        m = re.search(
            r"(\d+(?:\.\d+)?)\s*m?\s*[x×]\s*(\d+(?:\.\d+)?)\s*m?",
            (text or "").lower())
        return (float(m.group(1)), float(m.group(2))) if m else None

    @api.model
    def _wa6_family_code(self, desc):
        """The category CODE (string, e.g. 'visual') whose synonyms hit the
        description, else None. Decoupled from the seeded category RECORD so it
        works even when catalogue-loaded products carry no equipment_category_id
        (proof #3 root cause). Phrase synonyms substring-match; single tokens on
        a word boundary."""
        low = " " + (desc or "").lower() + " "
        for code, syns in _WA6_CAT_SYNONYMS.items():
            for syn in syns:
                hit = (syn in low) if (" " in syn) else bool(
                    re.search(r"(?:^|\s)%s(?:\s|$)" % re.escape(syn), low))
                if hit:
                    return code
        return None

    @api.model
    def _wa6_norm_family(self, hint):
        """Normalise an LLM category hint (Robin's visual/lighting/staging
        label) to a known family code, else None (unknown hints are ignored ->
        fall back to synonym derivation)."""
        h = (hint or "").strip().lower()
        if not h:
            return None
        if h in _WA6_CAT_SYNONYMS:
            return h
        return {"video": "visual", "screen": "visual", "screens": "visual",
                "av": "visual", "light": "lighting", "lights": "lighting",
                "stage": "staging", "audio": "sound", "pa": "sound",
                "cables": "cabling", "cable": "cabling", "fx": "effects",
                "special effects": "effects"}.get(h)

    @api.model
    def _wa6_in_family(self, product, code):
        """True if a product belongs to family ``code`` -- by its
        equipment_category_id.code OR (the M-A fix for un-categorised loaded
        products) its NAME/workshop_name hitting a family synonym. Scopes a
        match to the obvious family (a 'screen' query -> the LED SCREEN products,
        NEVER a BOOTH)."""
        if product.equipment_category_id \
                and product.equipment_category_id.code == code:
            return True
        hay = " " + ((product.name or "") + " "
                     + (product.workshop_name or "")).lower() + " "
        for syn in _WA6_CAT_SYNONYMS.get(code, []):
            if (syn in hay) if (" " in syn) else re.search(
                    r"(?:^|\s)%s(?:\s|$)" % re.escape(syn), hay):
                return True
        return False

    @api.model
    def _wa6_category_for(self, desc):
        """The neon.equipment.category whose synonyms hit this description,
        or None. Phrase synonyms match as a substring; single tokens on a
        word boundary."""
        low = " " + (desc or "").lower() + " "
        Cat = self.env["neon.equipment.category"].sudo()
        for code, syns in _WA6_CAT_SYNONYMS.items():
            for syn in syns:
                hit = (syn in low) if (" " in syn) else bool(
                    re.search(r"(?:^|\s)%s(?:\s|$)" % re.escape(syn), low))
                if hit:
                    cat = Cat.search([("code", "=", code)], limit=1)
                    if cat:
                        return cat
        return None

    # ================================================================
    # Resolver v2 -- the matcher funnel helpers (S1 normalise, S2 alias-
    # expand CONFIRMED-only, S4 casing-dup canonicalise, S6 pg_trgm rank,
    # S7 grounded LLM shortlist). Design: docs/phase-11/
    # WA12_resolver_v2_locked_spec.md. Every stage exits _wa6_match_one
    # through the existing hit() closure -> byte-compatible return dict.
    # ================================================================
    @api.model
    def _r2_norm(self, s):
        """S1 normalise: casefold; unify x/separators; join a bare 'NxM' spec
        into one token; safe plural-fold (NOT 'ss', not the KEEP set) so
        'screens'=='screen' but 'truss' stays 'truss'. Returns a space-joined
        token string -- the canonical key for exact-equality + the trgm query."""
        low = (s or "").lower().replace("×", "x").replace(" ", " ")
        toks = []
        for t in re.findall(r"[a-z0-9.]+", low):
            if t in _WA6_STOP:
                continue
            # safe plural fold: alpha, len>3, trailing single 's' (not 'ss'),
            # not an explicit keep-stem.
            if (t.isalpha() and len(t) > 3 and t.endswith("s")
                    and not t.endswith("ss") and t not in _WA6_PLURAL_KEEP):
                t = t[:-1]
            toks.append(t)
        return " ".join(toks)

    @api.model
    def _r2_alias_map(self):
        """S2 gate #1: {phrase: ('product', id) | ('category', code) |
        ('term', text)} for CONFIRMED rows ONLY. proposed/open rows are
        structurally invisible to the matcher. Single read site -> the only
        place the alias store is consulted."""
        out = {}
        Alias = self.env["neon.equipment.alias"].sudo()
        for a in Alias.search([("state", "=", "confirmed")]):
            if a.product_template_id:
                out[a.phrase] = ("product", a.product_template_id.id)
            elif a.category_id:
                out[a.phrase] = ("category", a.category_id.code)
            elif a.term:
                out[a.phrase] = ("term", a.term)
        return out

    @api.model
    def _r2_alias_expand(self, desc):
        """S2: apply the CONFIRMED alias map to a description. Whole-word,
        plural-tolerant ('cans' matches a 'can' alias and vice versa), longest
        phrase first (so a multi-word alias wins over a contained single word).
        Returns (kind, value, new_desc):
          ('product', id, desc)   -> terminal: resolve straight to that product
          ('category', code, desc)-> forced family scope, keep matching within
          ('term', text, new_desc)-> desc rewritten (phrase -> term), continue
          (None, None, desc)      -> no confirmed alias hit."""
        amap = self._r2_alias_map()
        if not amap:
            return (None, None, desc)
        low = " " + (desc or "").lower() + " "
        for phrase in sorted(amap, key=len, reverse=True):
            # plural-tolerant whole-word: optional trailing 's' on the phrase.
            pat = r"(?<![a-z0-9])%ss?(?![a-z0-9])" % re.escape(phrase)
            if not re.search(pat, low):
                continue
            kind, value = amap[phrase]
            if kind == "term":
                new = re.sub(pat, " %s " % value, low).strip()
                return ("term", value, " ".join(new.split()))
            if kind == "category":
                return ("category", value, desc)
            # product: short-circuit ONLY when the alias phrase dominates the
            # desc (the desc is essentially just the slang, modulo stopwords +
            # generic equipment nouns) -- so "totem" / "smoke machine" -> the
            # product, but "totem clamp adapter" keeps matching normally rather
            # than being hijacked by a bare 'totem' alias. The generic-noun set
            # lets "smoke" fire for "smoke machine" (live-wire finding): "smoke"
            # confirmed -> VERTICAL SMOKE MACHINES, and "machine(s)" carries no
            # product-distinguishing meaning.
            residue = re.sub(pat, " ", low)
            residue_toks = [t for t in re.findall(r"[a-z0-9.]+", residue)
                            if t not in _WA6_STOP and t not in _WA6_GENERIC_NOUN]
            if not residue_toks:
                return ("product", value, desc)
        return (None, None, desc)

    @api.model
    def _r2_pick_canonical(self, prods):
        """S4/S5 casing-dup collapse. Given products that are EXACT logical
        matches, return (representative, distinct_others). Pure casing/space
        dups (same _r2_norm) collapse to ONE representative -- the most-
        UPPERCASE spelling, ties broken by lowest id -- so a pure-case dup is
        NOT a false 'weak'. Genuinely-distinct names (different _r2_norm) are
        returned as `distinct_others` for the caller to surface as suggestions."""
        if not prods:
            return (prods, prods.browse())
        by_norm = {}
        for p in prods:
            by_norm.setdefault(self._r2_norm(p.name), p)  # first seen per norm
        # representative of the FIRST norm group: prefer most uppercase, low id.
        first_norm = self._r2_norm(prods[0].name)
        group = prods.filtered(lambda p: self._r2_norm(p.name) == first_norm)
        rep = sorted(
            group, key=lambda p: (-sum(1 for c in (p.name or "") if c.isupper()),
                                  p.id))[0]
        distinct = prods.browse(
            [v.id for k, v in by_norm.items() if k != first_norm])
        return (rep, distinct)

    @api.model
    def _r2_trgm_rank(self, query_norm, cand_ids, k=None):
        """S6: pg_trgm category-scoped lexical rank. Returns [(id, sim)] desc,
        deterministic tie-break by id, capped at k. Family-scoped by cand_ids
        (cross-category structurally impossible). Degrades to [] on ANY SQL
        surprise -> never 500s mid-quote."""
        if not query_norm or not cand_ids:
            return []
        k = k or _WA6_SHORTLIST_K
        # product_template.name is a TRANSLATABLE field -> stored as jsonb
        # ({"en_US": "..."}) in Odoo 17, NOT plain text; workshop_name is a
        # plain Char (character varying). So name must be extracted via ->> ; a
        # raw lower(name) fails with "invalid input syntax for type json". Pull
        # the company language value, fall back to the first json value.
        lang = (self.env.lang or self.env.company.partner_id.lang
                or "en_US")
        # Run inside a SAVEPOINT: a failed cr.execute (e.g. pg_trgm missing)
        # aborts the cursor, and WITHOUT a savepoint every subsequent query in
        # the request raises InFailedSqlTransaction. The savepoint contains the
        # failure so we degrade to [] cleanly and the outer txn survives.
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    """
                    SELECT pt.id,
                           GREATEST(
                             similarity(lower(coalesce(
                               pt.name ->> %(lang)s,
                               (SELECT je.value FROM jsonb_each_text(pt.name) je
                                LIMIT 1),
                               '')), %(q)s),
                             similarity(lower(coalesce(pt.workshop_name, '')),
                                        %(q)s)
                           ) AS sim
                    FROM   product_template pt
                    WHERE  pt.id IN %(ids)s
                    ORDER  BY sim DESC, pt.id ASC
                    LIMIT  %(k)s
                    """,
                    {"q": query_norm, "ids": tuple(cand_ids), "k": k,
                     "lang": lang})
                rows = self.env.cr.fetchall()
            return [(r[0], float(r[1])) for r in rows]
        except Exception:  # noqa: BLE001 -- any SQL issue -> graceful empty
            _logger.exception("r2 trgm rank failed; degrading to []")
            return []

    @api.model
    def _r2_grounded_pick(self, desc, fam, ranked):
        """S7: the grounded LLM shortlist -- the firewall. Hand the LLM a FIXED
        numbered list of REAL product names (the S6 top-K within `fam`) and ask
        for an INDEX. The reply is validated in-range AND re-checked in-family
        before it can become a product_id; any non-index / out-of-range / out-
        of-family / LLM-down reply -> None (caller falls to discovery). NEVER
        invents, NEVER crosses category. Returns {product_id, product_name} or
        None."""
        ids = [pid for pid, _sim in ranked][:_WA6_SHORTLIST_K]
        if not ids:
            return None
        Product = self.env["product.template"].sudo()
        prods = [Product.browse(i) for i in ids]
        prods = [p for p in prods if p.exists()]
        if not prods:
            return None
        opts = "\n".join("  %d. %s" % (i, p.name) for i, p in enumerate(prods))
        messages = [
            {"role": "system", "content": (
                "You match a sales rep's equipment phrase to ONE item from a "
                "FIXED numbered list of real products this company stocks, or "
                "none. Reply with ONLY JSON: {\"index\": <integer or null>}. "
                "index MUST be one of the shown numbers. Do NOT invent a "
                "product, do NOT return a name. If none of the listed options "
                "is what the phrase means, return {\"index\": null}. Every "
                "listed product is in the '%s' family -- never pick across "
                "families." % fam)},
            {"role": "user", "content": (
                "Phrase: \"%s\"\nOptions:\n%s" % (desc, opts))},
        ]
        try:
            data = self._wa12_llm_json(self._wa12_llm_chat(messages)) or {}
        except Exception:  # noqa: BLE001 -- LLM down -> discovery
            return None
        idx = data.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(prods)):
            return None
        p = prods[idx]
        if not p.exists() or not self._wa6_in_family(p, fam):
            return None  # defence in depth
        return {"product_id": p.id, "product_name": p.name}

    @api.model
    def _wa6_match_one(self, raw, category_hint=None):
        """Resolve one free-text item to {product_id, qty, status,
        suggestions, confidence, family}. Resolver v2 funnel (S0-S8; design
        docs/phase-11/WA12_resolver_v2_locked_spec.md). NEVER auto-invents and
        NEVER crosses category. ``confidence``: 'exact' (typed name /
        dimensional-exact / confirmed product-alias), 'strong' (a clear trgm
        winner), 'weak' (thin/tied/nearest/LLM-grounded -- human-confirming
        consumers list alternatives), 'none'. Return dict is byte-compatible
        with the prior matcher (same keys + value-domain).

        S0 parse  -> S1 normalise -> S2 alias-expand (CONFIRMED only) ->
        S3 family-derive -> S4 dimensional -> S5 exact-name ->
        S6 pg_trgm category-scoped rank -> S7 grounded LLM shortlist ->
        S8 discovery/custom."""
        # S0 -- parse qty/desc (dims masked; bare-leading-count -> qty).
        qty, desc = self._wa6_parse_qty(raw)
        fam = ""  # bound up-front (the hit() closure reads it on every exit).

        def hit(pid, pname, conf, sugg):
            return {"raw": raw, "qty": qty, "product_id": pid,
                    "product_name": pname, "category": "",
                    "status": "matched" if pid else "not_found",
                    "suggestions": sugg, "confidence": conf, "family": fam}

        Product = self.env["product.template"].sudo()
        # Single-item matching EXCLUDES the Packages family: a rep naming a piece
        # of gear ("smoke machine") never means a bundled DJ/wedding PACKAGE that
        # merely lists that item in its name -- packages are reached only when a
        # rep explicitly asks for a package (a separate, future path). Without
        # this, "smoke machine" leaked to 3 PACKAGE products (live-wire finding
        # 614-617). Code resolved once; absent on a fresh DB -> no exclusion.
        pkg = self.env["neon.equipment.category"].sudo().search(
            [("code", "=", "packages")], limit=1)
        pdomain = [("is_workshop_item", "=", True)]
        if pkg:
            pdomain.append(("equipment_category_id", "!=", pkg.id))
        allp = Product.search(pdomain)

        # S2 -- CONFIRMED alias expansion (before family derivation). A product
        # alias is terminal; a category alias forces the family; a term alias
        # rewrites desc and we continue. proposed/open rows are invisible.
        forced_fam = ""
        kind, value, desc = self._r2_alias_expand(desc)
        if kind == "product":
            p = Product.browse(value)
            if p.exists():
                fam = self._wa6_family_code(p.name) or ""
                return hit(p.id, p.name, "exact", [])
        elif kind == "category":
            forced_fam = value

        # S1 -- normalise (after any term rewrite). want = canonical key.
        want = self._r2_norm(desc)
        tokens = [t for t in re.findall(r"[a-z0-9.]+", desc.lower())
                  if t and t not in _WA6_STOP]

        # S5a -- EXACT name equality across ALL families (the typed name IS the
        # id), preserved as a global fast path (F2): a fully-typed catalogue name
        # wins even when no family synonym fires. Casing/space dups collapse to a
        # canonical rep, so a pure-case dup is still 'exact' (not a false weak).
        if want:
            exact = allp.filtered(
                lambda p: self._r2_norm(p.name) == want
                or (p.workshop_name and self._r2_norm(p.workshop_name) == want))
            if exact:
                fam = self._wa6_family_code(desc) or ""
                rep, distinct = self._r2_pick_canonical(exact)
                return hit(rep.id, rep.name, "exact",
                           [p.name for p in distinct[:3]])

        # S3 -- derive the family. forced_fam (confirmed cat alias) wins, then
        # the LLM hint, then the synonym-derived family. Never widened to all.
        fam = (forced_fam or self._wa6_norm_family(category_hint)
               or self._wa6_family_code(desc) or "")

        if fam:
            cands = allp.filtered(lambda p: self._wa6_in_family(p, fam))
            if not cands:
                return hit(False, "", "none", [])  # family empty (M-B)

            # S4 -- dimensional (only with a size). Exact stocked size is the
            # rule; pure casing/space dups collapse to one canonical rep (NOT a
            # false 'weak'); no stocked size -> nearest-by-area (weak, the
            # exception -> confirm / custom-price path).
            dims = self._wa6_parse_dims(desc)
            if dims:
                target = dims[0] * dims[1]
                sized = [(p, self._wa6_parse_dims(p.name)) for p in cands]
                sized = [(p, d) for p, d in sized if d]
                exactd = cands.browse([p.id for p, d in sized if d == dims])
                if exactd:
                    rep, distinct = self._r2_pick_canonical(exactd)
                    return hit(rep.id, rep.name, "exact",
                               [p.name for p in distinct[:3]])
                if sized:
                    sized.sort(key=lambda pd: abs(pd[1][0] * pd[1][1] - target))
                    return hit(sized[0][0].id, sized[0][0].name, "weak",
                               [p.name for p, _ in sized[:3]])

            # S5 -- exact normalised-name equality within the family.
            if want:
                exact = cands.filtered(
                    lambda p: self._r2_norm(p.name) == want
                    or (p.workshop_name
                        and self._r2_norm(p.workshop_name) == want))
                if exact:
                    rep, distinct = self._r2_pick_canonical(exact)
                    return hit(rep.id, rep.name, "exact",
                               [p.name for p in distinct[:3]])

            # S6 -- pg_trgm category-scoped lexical rank. A clear winner is
            # 'strong'; otherwise the rank still informs the shortlist (S7).
            ranked = self._r2_trgm_rank(want, cands.ids)
            if ranked:
                top_id, top_sim = ranked[0]
                second = ranked[1][1] if len(ranked) > 1 else 0.0
                if top_sim >= _WA6_TRGM_STRONG \
                        and (top_sim - second) >= _WA6_TRGM_MARGIN:
                    p = Product.browse(top_id)
                    return hit(p.id, p.name, "strong", [])

            # S6b -- DETERMINISTic within-family token tier (the baseline
            # scorer, restored). A bare family word ("screen") or a thin trgm
            # hit still resolves by token overlap, so the matcher is not
            # LLM-dependent for the common case (and tests with the LLM muted
            # still resolve). Strong = >=2 distinct word hits + a clear margin;
            # else weak with alternatives. Runs BEFORE the LLM pick.
            def tscore(p):
                hay = ((p.name or "") + " " + (p.workshop_name or "")).lower()
                return sum(1 for t in tokens if t in hay)
            tranked = cands.sorted(
                key=lambda p: (-tscore(p), (p.name or "").lower()))
            tbest = tranked[:1]
            if tbest and tscore(tbest) > 0:
                def wscore(p):
                    hw = re.findall(r"[a-z0-9.]+",
                                    ((p.name or "") + " "
                                     + (p.workshop_name or "")).lower())
                    return sum(1 for t in tokens if len(t) >= 3
                               and any(w == t or w.startswith(t) for w in hw))
                s1 = wscore(tbest)
                s2 = wscore(tranked[1]) if len(tranked) > 1 else 0
                conf = "strong" if (s1 >= 2 and s1 > s2) else "weak"
                return hit(tbest.id, tbest.name, conf,
                           [p.name for p in tranked[:3]] if conf == "weak"
                           else [])

            # S7 -- grounded LLM shortlist (only when fam known + trgm gave a
            # ranking but token overlap found nothing). Validated back to a real
            # in-family id; else falls through to discovery. NEVER invents.
            if ranked:
                picked = self._r2_grounded_pick(desc, fam, ranked)
                if picked:
                    return hit(picked["product_id"], picked["product_name"],
                               "weak", [Product.browse(i).name
                                        for i, _s in ranked[:3]])

            # S8 (family-known) -- nothing scored: discovery suggestions.
            return hit(False, "", "none", [p.name for p in cands[:3]])

        # S8 (no family) -- conservative all-items token scorer (baseline
        # behaviour; lone winner capped at weak/strong by wscore3). No LLM here,
        # no cross-category risk (no family was ever asserted). Never invents.
        def score3(p):
            hay = ((p.name or "") + " " + (p.workshop_name or "")).lower()
            return sum(1 for t in tokens if t in hay)
        ranked = allp.sorted(key=lambda p: (-score3(p), (p.name or "").lower()))
        best = ranked[:1]
        if best and score3(best) > 0:
            def wscore3(p):
                hw = re.findall(r"[a-z0-9.]+",
                                ((p.name or "") + " "
                                 + (p.workshop_name or "")).lower())
                return sum(1 for t in tokens if len(t) >= 3
                           and any(w == t or w.startswith(t) for w in hw))
            s1 = wscore3(best)
            s2 = wscore3(ranked[1]) if len(ranked) > 1 else 0
            conf = "strong" if (s1 >= 2 and s1 > s2) else "weak"
            return hit(best.id, best.name, conf,
                       [p.name for p in ranked[:3]] if conf == "weak" else [])
        return hit(False, "", "none", [])

    # ================================================================
    # WA-6.1 -- Face-3 crew-initiated dispatch (command -> list -> pick ->
    # send the checkout/check-in buttons). The previously-missing trigger.
    # ================================================================
    @api.model
    def _wa6_eligible_checkout_jobs(self, user):
        """Event jobs where this user is THIS job's lead_tech/crew_chief
        (warehouse gate) AND there is gear allocated-not-yet-out (>=1
        reservation in state 'confirmed'). No date gate -- the chief is
        trusted on timing; terminal jobs drop out naturally (no live
        confirmed holds)."""
        EJ = self.env["commercial.event.job"].sudo()
        jobs = EJ.search(["|", ("lead_tech_id", "=", user.id),
                          ("crew_chief_id", "=", user.id)])
        return jobs.filtered(
            lambda ej: self._wa6_can_warehouse(ej, user)
            and ej.equipment_line_ids.reservation_ids.filtered(
                lambda r: r.state == "confirmed"))

    @api.model
    def _wa6_eligible_checkin_jobs(self, user):
        """Event jobs where this user is lead_tech/crew_chief AND gear is
        still OUT: a fulfilled reservation whose serial unit is checked_out
        /transferred, OR a quantity COUNT reservation with no 'checkin'
        movement yet (so a quantity job CLEARS the list once checked in --
        incl. after a partial check-in, since the checkin movement exists)."""
        EJ = self.env["commercial.event.job"].sudo()
        Move = self.env["neon.equipment.movement"].sudo()
        jobs = EJ.search(["|", ("lead_tech_id", "=", user.id),
                          ("crew_chief_id", "=", user.id)])

        def has_out(ej):
            if not self._wa6_can_warehouse(ej, user):
                return False
            for r in ej.equipment_line_ids.reservation_ids.filtered(
                    lambda r: r.state == "fulfilled"):
                if r.unit_id:
                    if r.unit_id.state in ("checked_out", "transferred"):
                        return True
                elif not Move.search_count([
                        ("reservation_id", "=", r.id),
                        ("movement_type", "=", "checkin")]):
                    return True
            return False
        return jobs.filtered(has_out)

    @api.model
    def _wa6_start_pick_flow(self, cmd, sender, jobs, from_e164, raw_from,
                             message):
        """Open the list-then-pick session and send the numbered list of
        the crew member's OWN eligible jobs. 1 job is still listed (no
        silent auto-assume)."""
        self._wa6_audit_in(from_e164, message, cmd)
        jobs = jobs.sorted(key=lambda j: j.id)
        step = "co_pick" if cmd == "checkout" else "ci_pick"
        self.env["neon.wa.equip.session"]._start_pick(
            from_e164, sender, step, jobs.ids)
        verb = "check out" if cmd == "checkout" else "check in"
        lines = "\n".join(
            "%d. %s" % (i + 1, j.sudo().name)
            for i, j in enumerate(jobs))
        return self._wa6_reply(
            raw_from, from_e164,
            _("Your jobs ready to %(v)s:\n%(l)s\n\nReply with the number "
              "to %(v)s that job.") % {"v": verb, "l": lines})

    def _wa6_handle_pick(self, sess, body, from_e164, raw_from):
        """A number reply during co_pick/ci_pick -> resolve to that job +
        send the checkout/check-in buttons (the dispatch). A re-typed
        command restarts; anything else re-shows the list."""
        is_checkin = sess.step == "ci_pick"   # capture BEFORE any write
        job_ids = sess._get_buffer()
        norm = (body or "").strip()
        # a re-typed command restarts the relevant flow (if still eligible)
        recmd = self._wa6_is_command(body)
        if recmd:
            sender = sess.user_id
            jobs = (self._wa6_eligible_checkin_jobs(sender)
                    if recmd == "checkin"
                    else self._wa6_eligible_checkout_jobs(sender))
            if jobs:
                return self._wa6_start_pick_flow(
                    recmd, sender, jobs, from_e164, raw_from,
                    {"type": "text", "text": {"body": body}})
        if norm.isdigit() and 1 <= int(norm) <= len(job_ids):
            ej = self.env["commercial.event.job"].sudo().browse(
                job_ids[int(norm) - 1]).exists()
            if not ej:
                return self._wa6_reply(
                    raw_from, from_e164,
                    _("That job is no longer available -- text the command "
                      "again."))
            sess.sudo().write({"event_job_id": ej.id, "step": "done",
                               "active": False})
            if is_checkin:
                return self._wa6_send_checkin_buttons(ej, raw_from, from_e164)
            return self._wa6_send_checkout_buttons(ej, raw_from, from_e164)
        # not a number in range -> re-show the list
        verb = "check in" if is_checkin else "check out"
        lines = "\n".join(
            "%d. %s" % (i + 1, self.env["commercial.event.job"].sudo()
                        .browse(jid).name)
            for i, jid in enumerate(job_ids))
        return self._wa6_reply(
            raw_from, from_e164,
            _("Reply with a number from your list to %(v)s:\n%(l)s")
            % {"v": verb, "l": lines})

    def _wa6_send_checkout_buttons(self, ej, raw_from, from_e164):
        body = _("%s -- ready to check out. Choose:") % ej.sudo().name
        buttons = [
            {"id": self._wa6_payload("wa6_co_all", ej.id),
             "title": "📦 Check out all"},
            {"id": self._wa6_payload("wa6_co_item", ej.id),
             "title": "📋 Item-by-item"}]
        return self._wa6_send_buttons(raw_from, from_e164, body, buttons)

    def _wa6_send_checkin_buttons(self, ej, raw_from, from_e164):
        body = _("%s -- checking gear back in. Choose:") % ej.sudo().name
        buttons = [
            {"id": self._wa6_payload("wa6_ci_good", ej.id),
             "title": "✅ All returned good"},
            {"id": self._wa6_payload("wa6_ci_flag", ej.id),
             "title": "⚠️ Flag an item"}]
        return self._wa6_send_buttons(raw_from, from_e164, body, buttons)

    # ================================================================
    # WA-6.2 -- OD WhatsApp-initiated finalize (command -> list -> pick ->
    # the EXISTING 3-button choice). Mirrors WA-6.1 exactly; the Odoo header
    # button stays as the SECONDARY entry. Reuses wa6_fin_* intents (no
    # neon_channels touch). Strictly FROM-SCRATCH (empty equipment lines).
    # ================================================================
    @api.model
    def _wa6_eligible_finalize_jobs(self, user):
        """Event jobs in the planning/prep window with NO equipment lines
        yet -- the from-scratch finalize set. 'No finalized equipment' has
        no boolean flag in the schema; an empty equipment_line_ids IS the
        signal -- the WhatsApp finalize BUILDS the lines (Face-2 confirm is
        the only line-create path), so a job that already carries lines
        (pre-seeded from a quote/template OR previously finalized) is edited
        in Odoo, never re-finalized here. Listed ORG-WIDE: initiate
        authority (_wa6_can_initiate) is OD/superuser, not per-job, unlike
        the Face-3 warehouse gate. (⚠️ DECISION WA-6.2.)"""
        return self.env["commercial.event.job"].sudo().search(
            [("state", "in", ("planning", "prep")),
             ("equipment_line_ids", "=", False)], order="id")

    @api.model
    def _wa6_start_finalize_flow(self, sender, jobs, from_e164, raw_from,
                                 message):
        """Open the list-then-pick session (step fin_pick) and send the
        numbered list of jobs awaiting a from-scratch finalize. 1 job is
        still listed (no silent auto-assume) -- mirrors WA-6.1."""
        self._wa6_audit_in(from_e164, message, "finalize")
        jobs = jobs.sorted(key=lambda j: j.id)
        self.env["neon.wa.equip.session"]._start_pick(
            from_e164, sender, "fin_pick", jobs.ids)
        lines = "\n".join(
            "%d. %s" % (i + 1, j.sudo().name)
            for i, j in enumerate(jobs))
        return self._wa6_reply(
            raw_from, from_e164,
            _("Jobs ready to finalize equipment:\n%s\n\nReply with the "
              "number to finalize that job.") % lines)

    def _wa6_handle_finalize_pick(self, sess, body, from_e164, raw_from):
        """A number reply during fin_pick -> resolve to that job and SEND
        the existing 3-button finalize choice (handing off to the proven
        Face-2 _wa6_route_initiate flow). A re-typed 'finalize' restarts;
        anything else re-shows the list. Defense: the picker must STILL be
        OD/superuser (re-checked, not trusted from session open)."""
        sender = sess.user_id
        if not self._wa6_can_initiate(sender):
            sess.sudo().write({"active": False})
            return self._wa6_reply(
                raw_from, from_e164,
                _("You're no longer authorised to finalize from here."))
        job_ids = sess._get_buffer()
        norm = (body or "").strip()
        # a re-typed finalize command restarts the pick (if still eligible)
        if self._wa6_is_command(body) == "finalize":
            jobs = self._wa6_eligible_finalize_jobs(sender)
            if jobs:
                return self._wa6_start_finalize_flow(
                    sender, jobs, from_e164, raw_from,
                    {"type": "text", "text": {"body": body}})
        if norm.isdigit() and 1 <= int(norm) <= len(job_ids):
            ej = self.env["commercial.event.job"].sudo().browse(
                job_ids[int(norm) - 1]).exists()
            if not ej:
                return self._wa6_reply(
                    raw_from, from_e164,
                    _("That job is no longer available -- text "
                      "\"finalize\" again."))
            # HARDENING (⚠️ DECISION WA-6.2): re-check the FROM-SCRATCH
            # contract at PICK time, not just at list time. The buffered
            # list can be up to the session TTL (12h) old, and a concurrent
            # Odoo finalize (or manual lines) could have made this job no
            # longer from-scratch in the interval. Mirrors WA-6's
            # re-check-every-turn discipline; never re-finalize a job that
            # already carries gear (which would duplicate equipment lines).
            if ej.equipment_line_ids or ej.state not in ("planning", "prep"):
                sess.sudo().write({"active": False})
                return self._wa6_reply(
                    raw_from, from_e164,
                    _("%s isn't awaiting a from-scratch finalize anymore "
                      "(it already has equipment, or has moved on). Edit it "
                      "in Odoo, or text \"finalize\" for the current list.")
                    % ej.name)
            # close the pick session; the 3-button choice goes out and the
            # [I'll finalize] tap opens a FRESH finalize session (await_items)
            # via _wa6_route_initiate -> _start -- identical to the Odoo
            # header-button path from here on.
            sess.sudo().write({"event_job_id": ej.id, "step": "done",
                               "active": False})
            return self._wa6_send_finalize_buttons(ej, raw_from, from_e164)
        # not a number in range -> re-show the list
        lines = "\n".join(
            "%d. %s" % (i + 1, self.env["commercial.event.job"].sudo()
                        .browse(jid).name)
            for i, jid in enumerate(job_ids))
        return self._wa6_reply(
            raw_from, from_e164,
            _("Reply with a number from your list to finalize:\n%s") % lines)

    def _wa6_finalize_buttons(self, ej):
        """The 3 finalize-choice buttons, shared by the Odoo-button initiate
        (_wa6_send_initiate, wrapped for the window-aware notify) and the
        WA-6.2 command pick (_wa6_send_finalize_buttons, sent in-window).
        Same titles + wa6_fin_* intents, so the downstream tap routing is
        byte-identical."""
        ej = ej.sudo()
        return [
            {"id": self._wa6_payload("wa6_fin_self", ej.id),
             "title": "✅ I'll finalize"},
            {"id": self._wa6_payload("wa6_fin_route", ej.id),
             "title": "\U0001F464 Send to crew chief"},
            {"id": self._wa6_payload("wa6_fin_odoo", ej.id),
             "title": "\U0001F4CB Open in Odoo"}]

    def _wa6_send_finalize_buttons(self, ej, raw_from, from_e164):
        """WA-6.2 -- emit the 3-button finalize choice in-window (mirrors
        WA-6.1's _wa6_send_checkout_buttons). The OD is live in-chat here
        (they just texted), so no cold-window template / Odoo activity is
        needed; the [I'll finalize] tap opens the proven Face-2 session."""
        ej = ej.sudo()
        body = (
            "\U0001F4E6 Equipment finalize for %s (%s) -- %s.\nChoose:"
            % (ej.name, ej.partner_id.name or "client",
               ej.event_date or "date TBC"))
        return self._wa6_send_buttons(
            raw_from, from_e164, body, self._wa6_finalize_buttons(ej))

    # ================================================================
    # FACE 3 -- WAREHOUSE CHECKOUT (run as the real tapping user)
    # ================================================================
    @api.model
    def _wa6_route_checkout(self, intent, parts, from_e164, raw_from):
        sender = self._wa6_resolve_user(from_e164)
        if intent == "wa6_co_line":
            line = self._wa6_line_from_parts(parts)
            if not line:
                return self._wa6_reply(
                    raw_from, from_e164,
                    _("That equipment line is no longer available."))
            if not self._wa6_can_warehouse(line.event_job_id, sender):
                return self._wa6_reply(
                    raw_from, from_e164,
                    _("Only this job's lead tech or crew chief can check "
                      "out its gear."))
            try:
                line.with_user(sender.id).action_checkout()
            except Exception as e:  # noqa: BLE001
                return self._wa6_reply(raw_from, from_e164, self._wa6_err(e))
            return self._wa6_reply(
                raw_from, from_e164,
                _("\U0001F4E6 Checked out: %s.")
                % line.sudo().product_template_id.name)
        ej = self._wa6_event_job_from_parts(parts)
        if not ej:
            return self._wa6_reply(
                raw_from, from_e164,
                _("That event job is no longer available."))
        if not self._wa6_can_warehouse(ej, sender):
            return self._wa6_reply(
                raw_from, from_e164,
                _("Only this job's lead tech or crew chief can check out "
                  "its gear."))
        if intent == "wa6_co_all":
            try:
                ej.with_user(sender.id).action_checkout_all_equipment()
            except Exception as e:  # noqa: BLE001
                return self._wa6_reply(raw_from, from_e164, self._wa6_err(e))
            return self._wa6_reply(
                raw_from, from_e164,
                _("\U0001F4E6 Checked out all gear for %s.") % ej.sudo().name)
        # wa6_co_item -> list the checkout-eligible lines
        lines = ej.sudo().equipment_line_ids.filtered(
            lambda l: l.state in ("planned", "partial"))
        if not lines:
            return self._wa6_reply(
                raw_from, from_e164,
                _("No lines on %s are ready to check out (allocate units "
                  "first).") % ej.sudo().name)
        rows = [{"id": self._wa6_payload("wa6_co_line", l.id),
                 "title": (l.product_template_id.name or "")[:24],
                 "description": _("%d planned") % l.quantity_planned}
                for l in lines]
        return self._wa6_send_list(
            raw_from, from_e164,
            _("Check out which item for %s?") % ej.sudo().name,
            "Check out", rows)

    # ================================================================
    # FACE 3 -- WAREHOUSE CHECK-IN
    # ================================================================
    @api.model
    def _wa6_route_checkin(self, intent, parts, from_e164, raw_from):
        ej = self._wa6_event_job_from_parts(parts)
        if not ej:
            return self._wa6_reply(
                raw_from, from_e164,
                _("That event job is no longer available."))
        sender = self._wa6_resolve_user(from_e164)
        if not self._wa6_can_warehouse(ej, sender):
            return self._wa6_reply(
                raw_from, from_e164,
                _("Only this job's lead tech or crew chief can check in its "
                  "gear."))
        if intent == "wa6_ci_flag":
            # ⚠️ DECISION (WA-6): a non-good check-in REQUIRES a condition
            # photo (model constraint) + maybe a resolution path. Capturing
            # + attaching a WhatsApp media photo is a separate capability the
            # channel layer doesn't have, so the exception path bounces to
            # the Odoo check-in wizard (which enforces the photo) rather than
            # reimplementing media ingestion over WhatsApp. The happy path
            # (all good) stays one tap.
            return self._wa6_reply(
                raw_from, from_e164,
                _("⚠️ To flag damaged / poor / missing gear you'll "
                  "need to add a condition photo -- open %s in Odoo and use "
                  "\"Check In Equipment\" to record it:\n%s")
                % (ej.sudo().name,
                   self._wa6_odoo_link("commercial.event.job", ej.id)))
        # wa6_ci_good -> headless check-in wizard, all condition=good.
        # default_get (NOT fired by create()) builds the lines from the
        # checked-out units, so call it explicitly, then create + confirm.
        Wizard = self.env["neon.equipment.checkin.wizard"].with_user(
            sender.id).with_context(default_event_job_id=ej.id)
        try:
            vals = Wizard.default_get(
                ["event_job_id", "line_id", "to_location_text",
                 "checkin_line_ids"])
            wiz = Wizard.create(vals)
            if not wiz.checkin_line_ids:
                return self._wa6_reply(
                    raw_from, from_e164,
                    _("Nothing is checked out for %s right now.")
                    % ej.sudo().name)
            n = len(wiz.checkin_line_ids)
            wiz.action_confirm()
        except Exception as e:  # noqa: BLE001
            return self._wa6_reply(raw_from, from_e164, self._wa6_err(e))
        return self._wa6_reply(
            raw_from, from_e164,
            _("✅ Checked in (all good): %d unit(s) for %s.")
            % (n, ej.sudo().name))

    # ---- tiny fail-safe part parsers -------------------------------
    @api.model
    def _wa6_event_job_from_parts(self, parts):
        if not parts or not str(parts[0]).isdigit():
            return None
        ej = self.env["commercial.event.job"].sudo().browse(int(parts[0]))
        return ej if ej.exists() else None

    @api.model
    def _wa6_line_from_parts(self, parts):
        if not parts or not str(parts[0]).isdigit():
            return None
        line = self.env["commercial.event.job.equipment.line"].sudo().browse(
            int(parts[0]))
        return line if line.exists() else None

    @api.model
    def _wa6_session_from_parts(self, parts):
        if not parts or not str(parts[0]).isdigit():
            return None
        s = self.env["neon.wa.equip.session"].sudo().browse(int(parts[0]))
        return s if s.exists() else None
