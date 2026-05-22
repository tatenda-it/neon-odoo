# -*- coding: utf-8 -*-
"""neon.lms.enrollment -- Phase 7e learner enrollment.

Inherits Odoo stdlib slide.channel.partner (the enrollment
model) and adds Neon-specific state + track completion
linkage.

Per schema sketch section 4 Option B (parallel completion
architecture): neon.lms.track.completion and neon.lms.module.
completion are the source of truth for learner state. Stdlib
slide_partner stays as the Odoo eLearning surface but doesn't
drive Neon progression. Sync verification between the two is
deferred to M14 smoke.
"""
import logging

from odoo import api, fields, models, SUPERUSER_ID, _

_logger = logging.getLogger(__name__)


_NEON_ENROLLMENT_STATES = [
    ("enrolled", "Enrolled"),
    ("in_progress", "In Progress"),
    ("completed", "Completed"),
    ("certified", "Certified"),
]


class NeonLMSEnrollment(models.Model):
    _inherit = "slide.channel.partner"

    neon_state = fields.Selection(
        _NEON_ENROLLMENT_STATES,
        string="Neon State",
        default="enrolled",
        tracking=True,
        help="Neon-specific enrollment lifecycle. "
             "Computed forward by M8 workflow from "
             "track_completion progression.",
    )
    neon_track_completion_ids = fields.One2many(
        "neon.lms.track.completion",
        "enrollment_id",
        string="Track Completions",
        help="One record per track. Materialised on enroll "
             "by M8 (deferred -- M7 ships the relation, M8 "
             "wires materialisation).",
    )
    neon_modules_completed = fields.Integer(
        compute="_compute_neon_modules_completed",
        store=False,
    )
    neon_modules_total = fields.Integer(
        compute="_compute_neon_modules_total",
        store=False,
    )
    neon_overall_progress = fields.Float(
        compute="_compute_neon_overall_progress",
        store=False,
    )
    neon_completion_date = fields.Datetime(
        readonly=True,
        copy=False,
    )
    neon_capstone_cert_id = fields.Many2one(
        "neon.training.certification",
        string="Capstone Certification",
        ondelete="set null",
        copy=False,
        help="Populated by M8 when neon_state transitions "
             "to 'certified' (all 7 tracks certified).",
    )
    neon_granted_authority_ids = fields.Many2many(
        "neon.lms.operating.authority",
        "neon_lms_enrollment_authority_rel",
        "enrollment_id",
        "authority_id",
        string="Granted Operating Authorities",
        compute="_compute_neon_granted_authority_ids",
        store=False,
    )

    @api.depends("neon_track_completion_ids."
                 "modules_completed")
    def _compute_neon_modules_completed(self):
        for rec in self:
            rec.neon_modules_completed = sum(
                rec.neon_track_completion_ids
                .mapped("modules_completed"))

    @api.depends("channel_id.neon_track_ids.module_ids")
    def _compute_neon_modules_total(self):
        for rec in self:
            total = 0
            for trk in rec.channel_id.neon_track_ids:
                total += len(trk.module_ids)
            rec.neon_modules_total = total

    @api.depends("neon_modules_completed",
                 "neon_modules_total")
    def _compute_neon_overall_progress(self):
        for rec in self:
            if rec.neon_modules_total:
                rec.neon_overall_progress = (
                    100.0 * rec.neon_modules_completed
                    / rec.neon_modules_total)
            else:
                rec.neon_overall_progress = 0.0

    # ============================================================
    # M8 workflow -- capstone check + cert issuance
    # ============================================================
    def _check_and_advance_to_certified(self):
        """Called from track.completion._issue_sub_cert.
        When all 7 track_completion records reach 'certified'
        state, issue the capstone cert + transition this
        enrollment to neon_state='certified'.

        Defensive against M9: if channel.neon_capstone_cert_
        type_id is unset (M9 seeds it), enrollment stays at
        'completed' until M9 lands.
        """
        self.ensure_one()
        if self.neon_capstone_cert_id:
            return self.neon_capstone_cert_id
        track_comps = self.neon_track_completion_ids
        total_tracks = self.channel_id.neon_total_tracks
        certified_count = len(track_comps.filtered(
            lambda tc: tc.state == "certified"))
        if certified_count < total_tracks:
            # Not all certified yet -- mark in_progress or
            # completed depending on coverage.
            if certified_count == 0:
                new_state = "enrolled"
            elif certified_count < total_tracks:
                new_state = "in_progress"
            else:
                new_state = "completed"
            if self.neon_state != new_state:
                self.sudo().write({"neon_state": new_state})
            return False
        # All certified. Try capstone cert issuance.
        if not self.channel_id.neon_capstone_cert_type_id:
            _logger.info(
                "neon_lms M8: capstone cert_type not set on "
                "channel %s (M9 seeds). Marking enrollment "
                "%d as completed; capstone deferred.",
                self.channel_id.name, self.id)
            self.sudo().write({
                "neon_state": "completed",
                "neon_completion_date": fields.Datetime.now(),
            })
            return False
        learner = self.env["res.users"].sudo().search([
            ("partner_id", "=", self.partner_id.id),
        ], limit=1)
        if not learner:
            _logger.warning(
                "neon_lms M8: no res.users for partner %s "
                "on enrollment %s; capstone not issued.",
                self.partner_id.id, self.id)
            return False
        Cert = self.env["neon.training.certification"]
        capstone = Cert.sudo().create({
            "user_id": learner.id,
            "type_id": (
                self.channel_id.neon_capstone_cert_type_id.id),
            "state": "active",
            "date_obtained": fields.Date.context_today(self),
            "verified_by_id": SUPERUSER_ID,
            "verified_at": fields.Datetime.now(),
        })
        self.sudo().write({
            "neon_capstone_cert_id": capstone.id,
            "neon_state": "certified",
            "neon_completion_date": fields.Datetime.now(),
        })
        _logger.info(
            "neon_lms M8: capstone %d issued for learner %s.",
            capstone.id, learner.login)
        return capstone

    @api.depends("neon_track_completion_ids.state",
                 "neon_track_completion_ids."
                 "track_id.operating_authority_ids")
    def _compute_neon_granted_authority_ids(self):
        """Authorities granted = union of operating_authority
        _ids on tracks whose completion.state == 'certified'.
        Practical signoff (required for working_at_height) is
        a M11 polish item; M8 grants the authority on track
        cert, M11 adds the practical layer.
        """
        for rec in self:
            certified_tracks = (
                rec.neon_track_completion_ids
                .filtered(lambda tc: tc.state == "certified")
                .mapped("track_id"))
            rec.neon_granted_authority_ids = (
                certified_tracks.mapped(
                    "operating_authority_ids"))
