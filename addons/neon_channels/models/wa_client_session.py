# -*- coding: utf-8 -*-
"""B11 / WA-5 -- client intake lane session state.

A deliberately tiny, single-purpose state row: ONE per CLIENT phone (an
UNMAPPED WhatsApp number), tracking where that stranger is in the canned
intake flow. Created/written via ``sudo`` from the client lane (the
client has no Odoo user). NO business data lives here -- just the step
and a link to the raw ``crm.lead`` once one is created, so the lead
itself stays the single source of truth.

Why a dedicated model (Gate-1 decision D2): the only multi-turn state in
the client lane is "this number tapped Request-a-quote and the next text
is the event details". A row makes that explicit and the sandbox test
deterministic, and the table is "free" -- WA-5 is a ``-u`` deploy anyway
for the WhatsApp tag / utm source+medium data records.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# A client session idle longer than this is treated as a fresh
# conversation (Meta's own 24h customer-service window; nothing
# proactive ever fires, so this is purely "did they go quiet and come
# back days later" hygiene -> restart cleanly at the greeting).
_WA5_SESSION_TTL_HOURS = 24


class WaClientSession(models.Model):
    _name = "neon.wa.client.session"
    _description = "WhatsApp Client Intake Session"
    _order = "write_date desc"

    phone_number = fields.Char(
        string="Client Phone (E.164)", required=True, index=True)
    step = fields.Selection(
        [("greeted", "Greeted"),
         ("awaiting_quote", "Awaiting quote details"),
         ("done", "Done")],
        string="Step", default="greeted", required=True)
    lead_id = fields.Many2one(
        "crm.lead", string="Lead", ondelete="set null")
    last_inbound = fields.Datetime(string="Last Inbound")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("phone_uniq", "unique(phone_number)",
         "One client intake session per phone number."),
    ]

    @api.model
    def _get_or_start(self, phone_e164):
        """Get the live session for this client phone, or start a fresh
        one. A stale session (idle > TTL) is reset to ``greeted`` (and
        its lead link cleared) so a returning stranger restarts cleanly
        rather than being stuck mid-flow."""
        sess = self.sudo().search(
            [("phone_number", "=", phone_e164)], limit=1)
        now = fields.Datetime.now()
        if not sess:
            return self.sudo().create({
                "phone_number": phone_e164, "step": "greeted",
                "last_inbound": now})
        if sess.last_inbound and (
                now - sess.last_inbound > timedelta(
                    hours=_WA5_SESSION_TTL_HOURS)):
            sess.write({"step": "greeted", "lead_id": False})
        sess.write({"last_inbound": now})
        return sess
