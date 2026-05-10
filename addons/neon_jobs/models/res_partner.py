# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    is_venue = fields.Boolean(
        string="Is a Venue",
        default=False,
        help="Mark this partner as a venue. Enables room sub-records and "
        "filters this partner into venue selection on Commercial Jobs.",
    )
    room_ids = fields.One2many(
        "venue.room",
        "venue_id",
        string="Rooms",
    )
    room_count = fields.Integer(
        string="Room Count",
        compute="_compute_room_count",
    )

    @api.depends("room_ids")
    def _compute_room_count(self):
        for rec in self:
            rec.room_count = len(rec.room_ids)
