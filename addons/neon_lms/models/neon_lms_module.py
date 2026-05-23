# -*- coding: utf-8 -*-
"""neon.lms.module -- one of 17 modules under a track.

Per schema sketch section 5.3. Modules carry slide content
(M12 migration), quizzes (M4), and practical scenarios (M5).
"""
from odoo import api, fields, models, _


class NeonLMSModule(models.Model):
    _name = "neon.lms.module"
    _description = "Neon LMS Module"
    _order = "track_id, sequence_in_track asc, id asc"

    code = fields.Char(
        string="Code",
        required=True,
        index=True,
        help="Unique identifier (e.g., M01, M02). Used by "
             "data files + cross-module references.",
    )
    name = fields.Char(
        string="Name",
        required=True,
        translate=True,
    )
    track_id = fields.Many2one(
        "neon.lms.track",
        string="Track",
        required=True,
        ondelete="restrict",
        index=True,
    )
    channel_id = fields.Many2one(
        "slide.channel",
        related="track_id.channel_id",
        store=True,
        readonly=True,
        index=True,
        help="Cached for query efficiency. Single program "
             "channel shared across all modules.",
    )
    sequence_in_track = fields.Integer(default=10)
    prerequisite_module_ids = fields.Many2many(
        "neon.lms.module",
        "neon_lms_module_prereq_rel",
        "module_id",
        "prereq_module_id",
        string="Prerequisite Modules",
        help="Intra-track ordering -- modules that must be "
             "completed before this one. Empty for first "
             "module in a track.",
    )
    # M6 -- reference SOPs attached to this module. Inverse
    # of neon.lms.sop.module_ids. M6 ships the M2M; SOPs
    # don't gate progression.
    sop_ids = fields.Many2many(
        "neon.lms.sop",
        "neon_lms_sop_module_rel",
        "module_id",
        "sop_id",
        string="Reference SOPs",
        help="Standard Operating Procedures linked to this "
             "module for learner reference. Read-only -- "
             "SOPs don't block module completion.",
    )
    # M7 -- reverse o2m fields (forward M2O lives on
    # quiz/scenario models from M4/M5). Surfaced here so M7
    # completion computes can traverse module ->
    # practical_scenario_ids and module -> quiz_question_ids.
    quiz_question_ids = fields.One2many(
        "neon.lms.quiz.question",
        "module_id",
        string="Quiz Questions",
    )
    practical_scenario_ids = fields.One2many(
        "neon.lms.practical.scenario",
        "module_id",
        string="Practical Scenarios",
    )
    min_quiz_score = fields.Float(
        string="Minimum Quiz Score",
        default=0.8,
        help="Required score (0-1) on the module quiz to "
             "advance.",
    )

    _sql_constraints = [
        ("module_code_unique",
         "UNIQUE(code)",
         "Module code must be unique."),
    ]

    # ------------------------------------------------------------------
    # LMS Admin Polish M2 -- quick-create helpers (also reused
    # by M4 server-action templates). Each helper creates a
    # placeholder record on this module and returns an
    # ir.actions.act_window pointing at it so the admin lands
    # directly in the edit form.
    # ------------------------------------------------------------------
    def _quick_create_pref_points(self):
        """Read user-scoped default_points preference (M4).
        Falls back to 1. Stored as an ir.config_parameter
        keyed per-user."""
        self.ensure_one()
        ICP = self.env["ir.config_parameter"].sudo()
        raw = ICP.get_param(
            "neon_lms.default_points.uid_%d" % self.env.uid,
            default="1")
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return 1

    def action_quick_create_mc(self):
        self.ensure_one()
        points = self._quick_create_pref_points()
        question = self.env["neon.lms.quiz.question"].create({
            "module_id": self.id,
            "question_text": _("New multiple-choice question"),
            "question_type": "multiple_choice",
            "points": points,
            "option_ids": [
                (0, 0, {"option_text": _("Option A"),
                        "is_correct": True,
                        "sequence": 10}),
                (0, 0, {"option_text": _("Option B"),
                        "is_correct": False,
                        "sequence": 20}),
                (0, 0, {"option_text": _("Option C"),
                        "is_correct": False,
                        "sequence": 30}),
                (0, 0, {"option_text": _("Option D"),
                        "is_correct": False,
                        "sequence": 40}),
            ],
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": "neon.lms.quiz.question",
            "res_id": question.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_quick_create_tf(self):
        self.ensure_one()
        points = self._quick_create_pref_points()
        question = self.env["neon.lms.quiz.question"].create({
            "module_id": self.id,
            "question_text": _("New true/false question"),
            "question_type": "true_false",
            "points": points,
            "option_ids": [
                (0, 0, {"option_text": _("True"),
                        "is_correct": True,
                        "sequence": 10}),
                (0, 0, {"option_text": _("False"),
                        "is_correct": False,
                        "sequence": 20}),
            ],
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": "neon.lms.quiz.question",
            "res_id": question.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_quick_create_sa(self):
        self.ensure_one()
        points = self._quick_create_pref_points()
        question = self.env["neon.lms.quiz.question"].create({
            "module_id": self.id,
            "question_text": _("New short-answer question"),
            "question_type": "short_answer",
            "points": points,
            "correct_answer": _("(fill in expected answer)"),
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": "neon.lms.quiz.question",
            "res_id": question.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_quick_create_scenario(self):
        self.ensure_one()
        scenario = self.env["neon.lms.practical.scenario"].create({
            "module_id": self.id,
            "title": _("New practical scenario"),
            "description": _("(scenario setup -- what the "
                             "learner is asked to do)"),
            "signoff_authority": "superuser",
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": "neon.lms.practical.scenario",
            "res_id": scenario.id,
            "view_mode": "form",
            "target": "current",
        }
