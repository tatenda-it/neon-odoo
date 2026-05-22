# -*- coding: utf-8 -*-
"""neon.lms.operating.authority -- the 6 authority domains.

Per schema sketch section 5.9. Each authority specifies the
tracks a learner must complete (all of them) to be granted
that authority on the operational floor. Phase 7e M10+ wires
these into the gate engine as a 5th gate condition.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class NeonLMSOperatingAuthority(models.Model):
    _name = "neon.lms.operating.authority"
    _description = "Neon LMS Operating Authority"
    _order = "name asc"

    name = fields.Char(
        string="Name",
        required=True,
        translate=True,
    )
    code = fields.Char(
        string="Code",
        required=True,
        index=True,
        help="Unique identifier (e.g., stop_work, electrical, "
             "generator, rigging, working_at_height, "
             "outdoor_public).",
    )
    description = fields.Text(
        translate=True,
    )
    requires_track_ids = fields.Many2many(
        "neon.lms.track",
        "neon_lms_authority_track_rel",
        "authority_id",
        "track_id",
        string="Required Tracks",
        required=True,
        help="Learner must reach state='certified' on ALL "
             "these tracks before this authority is granted.",
    )
    requires_practical_signoff = fields.Boolean(
        string="Requires Practical Signoff",
        default=False,
        help="True for authorities like working_at_height "
             "that need an extra practical evaluation beyond "
             "track completion.",
    )

    _sql_constraints = [
        ("authority_code_unique",
         "UNIQUE(code)",
         "Authority code must be unique."),
    ]

    @api.constrains("requires_track_ids")
    def _check_requires_track_ids_nonempty(self):
        """Every authority must require at least one track --
        an authority granted without any prerequisite is a
        configuration error.
        """
        for rec in self:
            if not rec.requires_track_ids:
                raise ValidationError(_(
                    "Operating authority '%s' must require at "
                    "least one track."
                ) % rec.name)
