# -*- coding: utf-8 -*-
"""neon.lms.track -- the 7 sub-courses.

Per schema sketch section 5.2. Each track has its own modules,
sub-cert outcome, and operating authority grants.

M3 adds Foundations strict-gate enforcement methods + integrity
constraints; M1 ships fields + seed data.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class NeonLMSTrack(models.Model):
    _name = "neon.lms.track"
    _description = "Neon LMS Track (Sub-Course)"
    _order = "sequence asc, id asc"

    code = fields.Char(
        string="Code",
        required=True,
        index=True,
        help="Unique identifier (e.g., TRK_FOUND_SAFETY). "
             "Used by data files + cross-module references.",
    )
    name = fields.Char(
        string="Name",
        required=True,
        translate=True,
    )
    description = fields.Text(
        translate=True,
    )
    channel_id = fields.Many2one(
        "slide.channel",
        string="Channel",
        required=True,
        ondelete="restrict",
        index=True,
    )
    module_ids = fields.One2many(
        "neon.lms.module",
        "track_id",
        string="Modules",
    )
    module_count = fields.Integer(
        compute="_compute_module_count",
        store=True,
    )
    sequence = fields.Integer(default=10)
    is_foundation_gate = fields.Boolean(
        string="Foundation Gate",
        default=False,
        help="True for the Foundations & Safety track only. "
             "Drives strict-sequencing rule -- all other "
             "tracks gate on this being certified.",
    )
    prerequisite_track_ids = fields.Many2many(
        "neon.lms.track",
        "neon_lms_track_prereq_rel",
        "track_id",
        "prereq_track_id",
        string="Prerequisite Tracks",
        help="Tracks that must reach state='certified' for a "
             "learner before this track unlocks. Empty for "
             "Foundations; contains Foundations for the 6 "
             "non-foundation tracks.",
    )
    sub_cert_type_id = fields.Many2one(
        "neon.training.certification.type",
        string="Sub-Cert Type",
        help="The cert auto-issued on track completion. "
             "Nullable in M1; populated by M9 seed extension.",
    )
    operating_authority_ids = fields.Many2many(
        "neon.lms.operating.authority",
        "neon_lms_track_authority_rel",
        "track_id",
        "authority_id",
        string="Operating Authorities Granted",
        help="Authority records granted when this track "
             "reaches certified state. Reverse M2M populated "
             "by M2 seed (mapping file).",
    )
    min_overall_score = fields.Float(
        string="Minimum Overall Score",
        default=0.8,
        help="Required across quiz + scenario averages to "
             "transition to certified. 0-1 scale.",
    )

    _sql_constraints = [
        ("track_code_unique",
         "UNIQUE(code)",
         "Track code must be unique."),
    ]

    @api.depends("module_ids")
    def _compute_module_count(self):
        for rec in self:
            rec.module_count = len(rec.module_ids)

    # ============================================================
    # M3 -- Foundations strict-gate enforcement
    # ============================================================
    @api.constrains("is_foundation_gate", "prerequisite_track_ids")
    def _check_foundation_gate_prereqs(self):
        """Foundation gate track must have NO prerequisites
        (it IS the gate). Non-foundation tracks must include
        the foundation track in their prerequisites.
        Validates seed integrity at install/upgrade time.
        """
        Track = self.env["neon.lms.track"]
        for rec in self:
            if rec.is_foundation_gate:
                if rec.prerequisite_track_ids:
                    raise ValidationError(_(
                        "Foundation-gate track '%(name)s' "
                        "cannot have prerequisite tracks -- "
                        "it IS the gate. Found: %(prereqs)s."
                    ) % {
                        "name": rec.name,
                        "prereqs": ", ".join(
                            rec.prerequisite_track_ids
                            .mapped("name")),
                    })
                continue
            # Non-foundation track. Must include the
            # foundation track in prereqs (if any foundation
            # exists in the system).
            foundation = Track.sudo().search(
                [("is_foundation_gate", "=", True)], limit=1)
            if foundation and foundation not in rec.prerequisite_track_ids:
                raise ValidationError(_(
                    "Non-foundation track '%(name)s' must "
                    "include the foundation track '%(found)s' "
                    "in prerequisite_track_ids."
                ) % {
                    "name": rec.name,
                    "found": foundation.name,
                })

    def _can_user_start(self, user):
        """Return True if the given user can start this track.

        Foundation gate: always True (it IS the prerequisite).
        Other tracks: True only when all prerequisite tracks
        have a completion record in state='certified' for
        this user.

        Defensive against M7's completion model not yet being
        installed -- returns conservative False in that case
        (gate is strict; missing model = not certified).
        """
        self.ensure_one()
        if self.is_foundation_gate:
            return True
        if not self.prerequisite_track_ids:
            # Non-foundation track with no prereqs declared --
            # constraint should have caught this but be
            # defensive.
            return True
        Completion = self.env.get(
            "neon.lms.track.completion")
        if Completion is None:
            # M7 model not yet installed -- gate strict.
            return False
        certified_tracks = Completion.sudo().search([
            ("enrollment_id.partner_id", "=", user.partner_id.id),
            ("state", "=", "certified"),
        ]).mapped("track_id")
        return all(p in certified_tracks
                   for p in self.prerequisite_track_ids)

    def _reason_user_cannot_start(self, user):
        """Human-readable explanation of why a user can't
        start this track. Returns empty string when start
        is allowed.
        """
        self.ensure_one()
        if self._can_user_start(user):
            return ""
        if not self.prerequisite_track_ids:
            return _(
                "Track unavailable -- the LMS completion "
                "model is not yet active. Contact the "
                "training admin.")
        return _(
            "Complete these tracks first: %s"
        ) % ", ".join(self.prerequisite_track_ids.mapped("name"))
