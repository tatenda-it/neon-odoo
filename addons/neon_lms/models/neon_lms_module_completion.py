# -*- coding: utf-8 -*-
"""neon.lms.module.completion -- per-learner per-module state.

Per schema sketch section 5.11. M8 workflow advances through
not_started -> in_progress -> completed based on quiz_score
+ scenario completion criteria.
"""
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


_MODULE_COMPLETION_STATES = [
    ("not_started", "Not Started"),
    ("in_progress", "In Progress"),
    ("completed", "Completed"),
]


class NeonLMSModuleCompletion(models.Model):
    _name = "neon.lms.module.completion"
    _description = "Neon LMS Module Completion"
    _order = "enrollment_id, module_id"

    enrollment_id = fields.Many2one(
        # Model is slide.channel.partner (stdlib); see note
        # on neon.lms.track.completion.enrollment_id.
        "slide.channel.partner",
        string="Enrollment",
        required=True,
        ondelete="cascade",
        index=True,
    )
    module_id = fields.Many2one(
        "neon.lms.module",
        string="Module",
        required=True,
        ondelete="restrict",
        index=True,
    )
    state = fields.Selection(
        _MODULE_COMPLETION_STATES,
        string="State",
        default="not_started",
        required=True,
        tracking=True,
        index=True,
    )
    quiz_score = fields.Float(
        default=0.0,
        help="Latest / best quiz score on this module's "
             "questions. 0-1 scale. M10 attempts model "
             "feeds this.",
    )
    scenarios_completed = fields.Integer(
        compute="_compute_scenarios_completed",
        store=False,
        help="Count of practical scenarios on this module "
             "with passed=True signoff for this learner.",
    )
    scenarios_total = fields.Integer(
        compute="_compute_scenarios_total",
        store=False,
    )
    last_activity = fields.Datetime(
        readonly=True,
        copy=False,
    )

    _sql_constraints = [
        ("module_completion_unique",
         "UNIQUE(enrollment_id, module_id)",
         "One module completion record per (enrollment, module)."),
    ]

    @api.depends("enrollment_id.partner_id",
                 "module_id.practical_scenario_ids")
    def _compute_scenarios_completed(self):
        ScenarioComp = self.env["neon.lms.scenario.completion"]
        for rec in self:
            if not rec.enrollment_id or not rec.module_id:
                rec.scenarios_completed = 0
                continue
            # Find the learner user from enrollment partner.
            partner = rec.enrollment_id.partner_id
            user = self.env["res.users"].sudo().search([
                ("partner_id", "=", partner.id),
            ], limit=1)
            if not user:
                rec.scenarios_completed = 0
                continue
            done = ScenarioComp.sudo().search_count([
                ("learner_id", "=", user.id),
                ("scenario_id", "in",
                 rec.module_id.practical_scenario_ids.ids),
                ("passed", "=", True),
            ])
            rec.scenarios_completed = done

    @api.depends("module_id.practical_scenario_ids")
    def _compute_scenarios_total(self):
        for rec in self:
            rec.scenarios_total = len(
                rec.module_id.practical_scenario_ids)

    # ============================================================
    # M7 transition check helper (M8 wires workflow below).
    # ============================================================
    def _can_transition_to_completed(self):
        """True when quiz_score >= module.min_quiz_score AND
        all practical scenarios have passed=True signoff.
        Modules without practical scenarios just need quiz.
        """
        self.ensure_one()
        if self.quiz_score < self.module_id.min_quiz_score:
            return False
        if self.scenarios_total == 0:
            return True
        return self.scenarios_completed >= self.scenarios_total

    # ============================================================
    # M8 workflow -- module -> track rollup
    # ============================================================
    def _check_and_advance_to_completed(self):
        """Called on quiz_score write or scenario completion.
        If criteria met + state != 'completed', advance.
        Then call track-level rollup.
        """
        self.ensure_one()
        if self.state == "completed":
            return False
        if not self._can_transition_to_completed():
            return False
        self.sudo().write({
            "state": "completed",
            "last_activity": fields.Datetime.now(),
        })
        # Track rollup: find this enrollment's track.completion
        # for the track this module belongs to.
        TrackComp = self.env["neon.lms.track.completion"]
        track_comp = TrackComp.sudo().search([
            ("enrollment_id", "=", self.enrollment_id.id),
            ("track_id", "=", self.module_id.track_id.id),
        ], limit=1)
        if track_comp:
            track_comp._check_and_advance_to_completed()
        return True

    def write(self, vals):
        """Workflow trigger: when quiz_score is written, fire
        the advance check. Cross-model triggers from M5
        scenario completion are wired in M8 via a write hook
        on neon.lms.scenario.completion.
        """
        res = super().write(vals)
        if "quiz_score" in vals:
            for rec in self:
                rec._check_and_advance_to_completed()
        return res
