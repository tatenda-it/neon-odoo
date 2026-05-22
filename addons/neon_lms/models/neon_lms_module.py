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
