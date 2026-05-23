# -*- coding: utf-8 -*-
"""neon.lms.track.completion -- per-learner per-track state.

Per schema sketch section 5.10. M8 workflow advances this
through not_started -> in_progress -> completed -> certified
based on module completions + sub-cert issuance.
"""
import logging

from odoo import api, fields, models, SUPERUSER_ID, _

_logger = logging.getLogger(__name__)


_TRACK_COMPLETION_STATES = [
    ("not_started", "Not Started"),
    ("in_progress", "In Progress"),
    ("completed", "Completed"),
    ("certified", "Certified"),
]


class NeonLMSTrackCompletion(models.Model):
    _name = "neon.lms.track.completion"
    _description = "Neon LMS Track Completion"
    _order = "enrollment_id, track_id"

    enrollment_id = fields.Many2one(
        # Model is slide.channel.partner (Odoo stdlib);
        # neon_lms_enrollment.py _inherits it classically
        # so all Neon fields land on slide.channel.partner.
        # No separate model name -- this M2O targets the
        # extended stdlib model.
        "slide.channel.partner",
        string="Enrollment",
        required=True,
        ondelete="cascade",
        index=True,
    )
    track_id = fields.Many2one(
        "neon.lms.track",
        string="Track",
        required=True,
        ondelete="restrict",
        index=True,
    )
    state = fields.Selection(
        _TRACK_COMPLETION_STATES,
        string="State",
        default="not_started",
        required=True,
        tracking=True,
        index=True,
    )
    modules_completed = fields.Integer(
        compute="_compute_modules_completed",
        store=False,
    )
    modules_total = fields.Integer(
        related="track_id.module_count",
        store=True,
    )
    overall_score = fields.Float(
        compute="_compute_overall_score",
        store=False,
        help="Weighted average of module quiz scores in this "
             "track. Used by M8 against track.min_overall_"
             "score to allow certified transition.",
    )
    sub_cert_id = fields.Many2one(
        "neon.training.certification",
        string="Sub-Certification",
        ondelete="set null",
        copy=False,
        help="Set on transition to certified. M8 creates the "
             "cert via track.sub_cert_type_id (populated by "
             "M9 seed extension).",
    )
    completion_date = fields.Datetime(
        readonly=True,
        copy=False,
    )
    certification_date = fields.Datetime(
        readonly=True,
        copy=False,
    )

    _sql_constraints = [
        ("track_completion_unique",
         "UNIQUE(enrollment_id, track_id)",
         "One track completion record per (enrollment, track)."),
    ]

    @api.depends("enrollment_id",
                 "track_id.module_ids")
    def _compute_modules_completed(self):
        """Count module.completion records under same
        enrollment whose module belongs to this track and
        is in state='completed'.
        """
        ModuleComp = self.env["neon.lms.module.completion"]
        for rec in self:
            if not rec.enrollment_id or not rec.track_id:
                rec.modules_completed = 0
                continue
            done = ModuleComp.sudo().search_count([
                ("enrollment_id", "=", rec.enrollment_id.id),
                ("module_id", "in", rec.track_id.module_ids.ids),
                ("state", "=", "completed"),
            ])
            rec.modules_completed = done

    @api.depends("enrollment_id", "track_id.module_ids")
    def _compute_overall_score(self):
        ModuleComp = self.env["neon.lms.module.completion"]
        for rec in self:
            if not rec.enrollment_id or not rec.track_id:
                rec.overall_score = 0.0
                continue
            comps = ModuleComp.sudo().search([
                ("enrollment_id", "=", rec.enrollment_id.id),
                ("module_id", "in", rec.track_id.module_ids.ids),
            ])
            if not comps:
                rec.overall_score = 0.0
                continue
            rec.overall_score = (
                sum(comps.mapped("quiz_score"))
                / len(comps))

    # ============================================================
    # M8 will wire actual workflow; M7 ships transition checks
    # ============================================================
    def _can_transition_to_completed(self):
        """True when modules_completed == modules_total (all
        modules in the track done). M8 calls this on every
        module-completion write to detect track rollup.
        """
        self.ensure_one()
        return (self.modules_total > 0
                and self.modules_completed
                >= self.modules_total)

    def _can_transition_to_certified(self):
        """True when state='completed' AND sub_cert_id set
        (M8 issues the cert before flipping state). Belt-and-
        braces: ensures the cert reference is in place before
        the state change.
        """
        self.ensure_one()
        return (self.state == "completed"
                and bool(self.sub_cert_id))

    # ============================================================
    # M8 workflow -- track rollup + sub-cert issuance + capstone
    # ============================================================
    def _check_and_advance_to_completed(self):
        """If all modules in this track are completed,
        advance track.completion to 'completed' + try cert
        issuance.
        """
        self.ensure_one()
        if self.state in ("completed", "certified"):
            if self.state == "completed":
                # Retry cert issuance (M9 may have caught up).
                self._issue_sub_cert()
            return False
        self.invalidate_recordset(["modules_completed"])
        if not self._can_transition_to_completed():
            return False
        self.sudo().write({
            "state": "completed",
            "completion_date": fields.Datetime.now(),
        })
        self._issue_sub_cert()
        return True

    def _issue_sub_cert(self):
        """Create the neon.training.certification record for
        this track. Defensive against M9 not installed --
        skips when sub_cert_type_id unset.
        """
        self.ensure_one()
        if self.sub_cert_id:
            return self.sub_cert_id
        if not self.track_id.sub_cert_type_id:
            _logger.info(
                "neon_lms M8: track %s has no sub_cert_type"
                "_id (M9 seeds). Track stays at 'completed' "
                "until M9 lands.",
                self.track_id.code)
            return False
        partner = self.enrollment_id.partner_id
        learner = self.env["res.users"].sudo().search([
            ("partner_id", "=", partner.id),
        ], limit=1)
        if not learner:
            _logger.warning(
                "neon_lms M8: no res.users for partner %s "
                "on enrollment %s; cert not issued.",
                partner.id, self.enrollment_id.id)
            return False
        Cert = self.env["neon.training.certification"]
        cert = Cert.sudo().create({
            "user_id": learner.id,
            "type_id": self.track_id.sub_cert_type_id.id,
            "state": "active",
            "date_obtained": fields.Date.context_today(self),
            "verified_by_id": SUPERUSER_ID,
            "verified_at": fields.Datetime.now(),
        })
        self.sudo().write({
            "sub_cert_id": cert.id,
            "state": "certified",
            "certification_date": fields.Datetime.now(),
        })
        _logger.info(
            "neon_lms M8: sub-cert %d issued for learner %s "
            "on track %s.",
            cert.id, learner.login, self.track_id.code)
        # M12 notification stubs. Fire track_certified always;
        # fire authority_granted per granted authority (track
        # may grant 0..n authorities).
        if hasattr(self.enrollment_id,
                   "_notify_track_certified"):
            self.enrollment_id._notify_track_certified(
                self.track_id)
            for authority in self.track_id.operating_authority_ids:
                self.enrollment_id._notify_authority_granted(
                    authority)
        self.enrollment_id._check_and_advance_to_certified()
        return cert
