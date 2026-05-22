# -*- coding: utf-8 -*-
"""slide.channel inherit -- Neon program extension.

Single channel record carries the Neon training program
identity + program state. Tracks (the 7 sub-courses) are
children via neon_track_ids o2m.
"""
from odoo import api, fields, models, _


_NEON_PROGRAM_STATES = [
    ("draft", "Draft"),
    ("active", "Active"),
    ("archived", "Archived"),
]


class SlideChannelNeonLMS(models.Model):
    _inherit = "slide.channel"

    neon_program_state = fields.Selection(
        _NEON_PROGRAM_STATES,
        string="Neon Program State",
        default="draft",
        tracking=True,
        help="Lifecycle state of the Neon training program. "
             "Draft (in setup), Active (open for enrollment), "
             "Archived (closed). M1 ships state=draft on the "
             "seeded channel; admin promotes to active when "
             "M7 enrollment is wired.",
    )
    neon_track_ids = fields.One2many(
        "neon.lms.track",
        "channel_id",
        string="Neon Tracks",
        help="The 7 sub-courses under this Neon channel.",
    )
    neon_total_tracks = fields.Integer(
        compute="_compute_neon_total_tracks",
        store=True,
        help="Cached count of associated tracks (target: 7).",
    )
    neon_capstone_cert_type_id = fields.Many2one(
        "neon.training.certification.type",
        string="Capstone Cert Type",
        help="The capstone cert issued on full program "
             "completion. Populated by M9 seed (cert_type_"
             "neon_technical). Nullable in M1.",
    )

    @api.depends("neon_track_ids")
    def _compute_neon_total_tracks(self):
        for rec in self:
            rec.neon_total_tracks = len(rec.neon_track_ids)
