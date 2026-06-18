# -*- coding: utf-8 -*-
"""Crew roster REFERENCE records (from the wages sheet).

Inert canonical crew list — NOT live hr.employee / neon.hr.event.wage /
commercial.job.crew. Faithful roster: one record per real person, with EVERY
raw source spelling preserved in ``aliases``. Names/roles only (NOT pay) ->
readable by all internal users, like the FamCal job-history archive.

The de-dup was resolved with Tatenda (2026-06-18): nicknames/typos merged
(KK=Ranganai, Biriad=Kudzai Mushore, Anorld=Arnold Mutasa, Kevin=Kelvin
Maibeki), Danny is a DISTINCT person "Kelvin Mushore" (NOT Kelvin Maibeki, NOT
Kudzai Mushore), and 9 former crew are kept inactive (active=False) rather than
deleted. Reversible/cleanable (superuser unlink).
"""
from odoo import api, fields, models


class NeonCrewMember(models.Model):
    _name = "neon.crew.member"
    _description = "Crew Member (Wages-Sheet Reference Roster)"
    _order = "is_lead desc, name"
    _rec_name = "name"

    name = fields.Char(string="Name", required=True)  # canonical real name
    aliases = fields.Text(
        string="Aliases",
        help="Every raw source spelling/nickname merged into this person.")
    alias_count = fields.Integer(
        string="# Aliases", compute="_compute_alias_count", store=True)
    role = fields.Selection(
        [("lead", "Lead"), ("permanent", "Permanent"),
         ("freelance", "Freelance"), ("unknown", "Unknown")],
        string="Role", default="unknown", index=True)
    is_lead = fields.Boolean(string="Lead Tech", default=False)
    status = fields.Selection(
        [("active", "Active"), ("former", "Former")],
        string="Status", default="active", index=True)
    source = fields.Char(string="Source", default="wages_sheet", index=True)
    note = fields.Text(string="Note")
    active = fields.Boolean(default=True)  # former crew -> False (default-hidden)

    _sql_constraints = [
        ("name_uniq", "unique(name)", "Crew member name must be unique."),
    ]

    @api.depends("aliases")
    def _compute_alias_count(self):
        for rec in self:
            rec.alias_count = len(
                [a for a in (rec.aliases or "").split("\n") if a.strip()])
