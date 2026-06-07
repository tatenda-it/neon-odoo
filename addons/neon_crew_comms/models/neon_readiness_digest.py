# -*- coding: utf-8 -*-
"""B11 / WA-3 -- manager readiness digest (collector + send).

Reads EXISTING commercial.job fields only (no invented readiness
fields). RAG is derived from operational_status + crew confirmation
(operational_status_color is an Odoo PALETTE index, NOT semantic RAG --
never used here). The digest sends fixed RAG COUNTS via a Meta template;
the variable-length per-job detail lives on the served /neon/readiness
board.

AbstractModel: no table, no ACL row. The manual trigger is manager-gated
(action_send_now); the cron entry (_cron_send) runs as the system and
ships DISABLED.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.neon_channels.models.phone_utils import to_e164

# Meta-approved template (parametrised; approved name/format confirmed at
# go-live). 4 FIXED body vars in order: date, ready, needs-attention,
# not-started; + a STATIC "Open readiness board" URL button.
TPL_DAILY_READINESS = "daily_readiness"
TPL_LANG = "en"

# Recipients + manual-trigger gate: the can_edit_crew set (Gate-1
# decision 2) -- Manager OR Crew Leader.
_DIGEST_GROUPS = (
    "neon_jobs.group_neon_jobs_manager",
    "neon_jobs.group_neon_jobs_crew_leader",
)

# RAG (Gate-1 decision 1, composite). RED = not operationally locked.
_RAG_RED_STATUS = {"planning", "soft_hold"}
# The remaining statuses are "locked"; GREEN needs crew fully confirmed,
# else AMBER (crew gap / no crew on a locked job).
_WINDOW_DAYS = 7


class NeonReadinessDigest(models.AbstractModel):
    _name = "neon.readiness.digest"
    _description = "Manager Readiness Digest (collector + send)"

    # ---- RAG ---------------------------------------------------------
    @api.model
    def _rag(self, job):
        """'red' | 'amber' | 'green' from operational_status + crew."""
        if job.operational_status in _RAG_RED_STATUS:
            return "red"
        if (job.crew_total_count > 0
                and job.crew_confirmed_count >= job.crew_total_count):
            return "green"
        return "amber"

    # ---- collect (shared by the digest counts + the board) ----------
    @api.model
    def collect(self, window_days=_WINDOW_DAYS):
        """Aggregate jobs in [today, today+window] into RAG counts +
        per-job rows. Money fields are deliberately excluded."""
        today = fields.Date.context_today(self)
        end = today + timedelta(days=window_days)
        jobs = self.env["commercial.job"].sudo().search(
            [("event_date", ">=", today), ("event_date", "<=", end)],
            order="event_date, id")
        op_labels = dict(
            self.env["commercial.job"]._fields["operational_status"].selection)
        counts = {"green": 0, "amber": 0, "red": 0}
        rows = []
        for j in jobs:
            rag = self._rag(j)
            counts[rag] += 1
            rows.append({
                "id": j.id,
                "name": j.name or "",
                "event_date": (j.event_date.isoformat()
                               if j.event_date else ""),
                "rag": rag,
                "operational_status": j.operational_status or "",
                "operational_status_label": op_labels.get(
                    j.operational_status, j.operational_status or ""),
                "crew_confirmed": int(j.crew_confirmed_count or 0),
                "crew_total": int(j.crew_total_count or 0),
                "equipment_count": int(j.equipment_count or 0),
                "equipment_summary": (j.equipment_summary or "")[:120],
            })
        return {
            "date_label": today.strftime("%a %d %b %Y"),
            "window_start": today.isoformat(),
            "window_end": end.isoformat(),
            "window_days": window_days,
            "total": len(jobs),
            "counts": counts,
            "jobs": rows,
            "generated_at_display": fields.Datetime.context_timestamp(
                self, fields.Datetime.now()).strftime("%d %b %Y, %H:%M %Z"),
        }

    # ---- recipient phone (manager -> sendable E.164) ----------------
    @api.model
    def _user_phone(self, user):
        """bot.user via user_id -> partner mobile/phone; E.164 or False."""
        bu = self.env["neon.bot.user"].sudo().search(
            [("user_id", "=", user.id), ("active", "=", True)], limit=1)
        if bu:
            e = to_e164(bu.phone_number or "")
            if e:
                return e
        p = user.partner_id
        for raw in (p.mobile, p.phone):
            e = to_e164(raw or "")
            if e:
                return e
        return False

    @api.model
    def _digest_recipients(self):
        gids = []
        for x in _DIGEST_GROUPS:
            g = self.env.ref(x, raise_if_not_found=False)
            if g:
                gids.append(g.id)
        if not gids:
            return self.env["res.users"]
        return self.env["res.users"].sudo().search(
            [("groups_id", "in", gids), ("share", "=", False),
             ("active", "=", True)])

    # ---- send --------------------------------------------------------
    @api.model
    def _send_to_managers(self):
        """Collect; skip empty days (no 'nothing to report' send); else
        send the daily_readiness template to each manager/crew-leader with
        a phone (send_template honours opt-out). Returns a summary."""
        data = self.collect()
        if not data["total"]:
            return {"sent": 0, "skipped": 0, "empty": True}
        c = data["counts"]
        body = [data["date_label"], str(c["green"]), str(c["amber"]),
                str(c["red"])]
        Msg = self.env["neon.whatsapp.message"].sudo()
        sent = skipped = 0
        for u in self._digest_recipients():
            phone = self._user_phone(u)
            if not phone:
                skipped += 1
                continue
            res = Msg.send_template(
                phone, TPL_DAILY_READINESS, language=TPL_LANG,
                body_params=body, recipient_partner=u.partner_id,
                audit_body=("[daily_readiness] %s green=%s amber=%s red=%s"
                            % (data["date_label"], c["green"], c["amber"],
                               c["red"])))
            if res.get("ok"):
                sent += 1
            else:
                skipped += 1
        return {"sent": sent, "skipped": skipped, "empty": False}

    @api.model
    def action_send_now(self):
        """Manual manager-gated trigger (from the board 'Send now')."""
        if not any(self.env.user.has_group(g) for g in _DIGEST_GROUPS):
            raise UserError(_(
                "Only ops (Manager or Crew Leader) can send the readiness "
                "digest."))
        return self._send_to_managers()

    @api.model
    def _cron_send(self):
        """Scheduled entry -- runs as system. CRON ships DISABLED
        (active=False); enable deliberately in Scheduled Actions."""
        return self._send_to_managers()
