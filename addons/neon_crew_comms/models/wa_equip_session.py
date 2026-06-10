# -*- coding: utf-8 -*-
"""B11 / WA-6 -- equipment-finalize conversation state (mapped staff).

The WA-5 client session (neon.wa.client.session) is keyed to an UNMAPPED
client phone + a crm.lead -- the wrong shape for WA-6, where the actor is
MAPPED staff (OD / crew chief / lead tech) finalizing an EVENT JOB over a
multi-turn free-text flow (send items -> review interpreted list ->
confirm / fix). So WA-6 gets its own tiny state row.

⚠️ DECISION (WA-6): a DEDICATED session model rather than extending
neon.wa.client.session. The client session carries no event_job link, no
finalizer user, and no parsed-line buffer, and its TTL/step semantics are
client-intake specific. A separate model keeps the two surfaces from
coupling (a client-lane change can't break a finalize mid-flow) and makes
the WA-6 FSM test deterministic. ONE active row per staff phone (unique),
reused/rebound on each new initiate -- same single-row-per-phone shape as
the client session.

Written/read via sudo from the bridge handlers (the webhook env is the
public/sudo user). The buffer is JSON: the matched/not-found line list the
finalizer is reviewing. perm_unlink=0 (operational audit hygiene, mirrors
the client session) -- reset in place, never delete.
"""
import json
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# A finalize conversation idle longer than this is stale -- the next
# inbound from that phone is treated as unrelated (falls through to the
# Copilot) rather than resumed mid-flow. Generous: a crew chief may take a
# while to gather the gear list.
_WA6_SESSION_TTL_HOURS = 12


class WaEquipSession(models.Model):
    _name = "neon.wa.equip.session"
    _description = "WhatsApp Equipment Finalize Session"
    _order = "write_date desc"

    phone_number = fields.Char(
        string="Staff Phone (E.164)", required=True, index=True)
    user_id = fields.Many2one(
        "res.users", string="Finalizer",
        help="The mapped staff member authorised to finalize this job's "
        "equipment over WhatsApp (the OD, or the routed-to crew chief / "
        "lead tech). The two-factor + finalize gate is re-checked on every "
        "turn against THIS user and event job.")
    event_job_id = fields.Many2one(
        "commercial.event.job", string="Event Job", ondelete="cascade")
    step = fields.Selection(
        [("await_items", "Awaiting item list"),
         ("review", "Reviewing interpreted list"),
         ("fixing", "Fixing one item"),
         ("co_pick", "Awaiting checkout job pick"),
         ("ci_pick", "Awaiting check-in job pick"),
         ("fin_pick", "Awaiting finalize job pick"),
         ("done", "Done")],
        string="Step", default="await_items", required=True)
    buffer = fields.Text(
        string="Buffer (JSON)",
        help="Step-dependent: in review/fixing it is the matched/not-found "
        "finalize line list; in co_pick/ci_pick (WA-6.1) and fin_pick "
        "(WA-6.2) it is the ordered list of eligible event_job ids the "
        "staff member is picking from.")
    fix_index = fields.Integer(
        string="Row Being Fixed", default=-1,
        help="0-based index into the buffer that the next free-text patch "
        "applies to (step=fixing). -1 when not fixing.")
    last_inbound = fields.Datetime(string="Last Inbound")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("phone_uniq", "unique(phone_number)",
         "One equipment-finalize session per staff phone number."),
    ]

    # ---- buffer helpers (single source of truth for JSON shape) -----
    def _get_buffer(self):
        self.ensure_one()
        try:
            return json.loads(self.buffer or "[]")
        except (ValueError, TypeError):
            return []

    def _set_buffer(self, items):
        self.ensure_one()
        self.sudo().write({"buffer": json.dumps(items or [])})

    @api.model
    def _active_for_phone(self, phone_e164):
        """The live (non-stale) finalize session for this staff phone, or
        an empty recordset. A session idle past the TTL is deactivated and
        NOT returned, so a much-later inbound falls through to the Copilot
        rather than being swallowed as a finalize reply."""
        sess = self.sudo().search(
            [("phone_number", "=", phone_e164), ("active", "=", True)],
            limit=1)
        if not sess:
            return self.browse()
        if sess.step == "done":
            return self.browse()
        if sess.last_inbound and (
                fields.Datetime.now() - sess.last_inbound
                > timedelta(hours=_WA6_SESSION_TTL_HOURS)):
            sess.write({"active": False})
            return self.browse()
        return sess

    @api.model
    def _start(self, phone_e164, user, event_job):
        """Open (or rebind) the single session for this staff phone to a
        fresh await_items state on the given event job. Reuses the unique
        row -- a new initiate supersedes any prior conversation.

        active_test=False: the unique(phone_number) constraint spans active
        AND inactive rows, but a default search hides inactive ones -- so a
        prior FINISHED session (active=False, e.g. a chief who finalized an
        earlier job) must be FOUND and rebound here, not re-created (which
        would trip the unique constraint)."""
        sess = self.sudo().with_context(active_test=False).search(
            [("phone_number", "=", phone_e164)], limit=1)
        vals = {
            "user_id": user.id if user else False,
            "event_job_id": event_job.id if event_job else False,
            "step": "await_items", "buffer": "[]", "fix_index": -1,
            "active": True, "last_inbound": fields.Datetime.now()}
        if sess:
            sess.write(vals)
        else:
            vals["phone_number"] = phone_e164
            sess = self.sudo().create(vals)
        return sess

    @api.model
    def _start_pick(self, phone_e164, user, step, job_ids):
        """WA-6.1 — open (or rebind) the single session into a checkout/
        check-in list-then-pick state. ``step`` is 'co_pick' or 'ci_pick';
        ``job_ids`` is the ordered list of the crew member's eligible event
        jobs (stored in buffer; the reply lists them numbered, the next
        number reply picks one). active_test=False to rebind a prior
        finished session (same unique-phone reasoning as _start)."""
        sess = self.sudo().with_context(active_test=False).search(
            [("phone_number", "=", phone_e164)], limit=1)
        vals = {
            "user_id": user.id if user else False,
            "event_job_id": False, "step": step,
            "buffer": json.dumps(list(job_ids or [])), "fix_index": -1,
            "active": True, "last_inbound": fields.Datetime.now()}
        if sess:
            sess.write(vals)
        else:
            vals["phone_number"] = phone_e164
            sess = self.sudo().create(vals)
        return sess
