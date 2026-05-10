# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class VenueRoom(models.Model):
    _name = "venue.room"
    _description = "Venue Room"
    _order = "venue_id, name"

    name = fields.Char(string="Room Name", required=True)
    venue_id = fields.Many2one(
        "res.partner",
        string="Venue",
        required=True,
        domain=[("is_venue", "=", True)],
        ondelete="cascade",
    )
    capacity = fields.Integer(string="Capacity (pax)")
    floor = fields.Char(string="Floor")
    notes = fields.Text(string="Notes")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "unique_room_per_venue",
            "UNIQUE (name, venue_id)",
            "A room with this name already exists at this venue.",
        ),
    ]

    def name_get(self):
        result = []
        for rec in self:
            display = rec.name
            if rec.venue_id:
                display = f"{rec.venue_id.name} — {rec.name}"
            result.append((rec.id, display))
        return result
