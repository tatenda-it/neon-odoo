# -*- coding: utf-8 -*-
"""neon.lms.quiz.question + neon.lms.quiz.option.

Phase 7e M4. Per-module quiz authoring; attempts + scoring
land in M8 + M10.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


_QUESTION_TYPES = [
    ("multiple_choice", "Multiple Choice"),
    ("true_false", "True/False"),
    ("short_answer", "Short Answer"),
]


class NeonLMSQuizQuestion(models.Model):
    _name = "neon.lms.quiz.question"
    _description = "Neon LMS Quiz Question"
    _order = "module_id, sequence asc, id asc"

    module_id = fields.Many2one(
        "neon.lms.module",
        string="Module",
        required=True,
        ondelete="restrict",
        index=True,
    )
    sequence = fields.Integer(default=10)
    question_text = fields.Text(
        string="Question",
        required=True,
        translate=True,
    )
    question_type = fields.Selection(
        _QUESTION_TYPES,
        string="Type",
        required=True,
        default="multiple_choice",
    )
    option_ids = fields.One2many(
        "neon.lms.quiz.option",
        "question_id",
        string="Options",
        help="For multiple_choice / true_false. At least one "
             "option must have is_correct=True.",
    )
    correct_answer = fields.Char(
        string="Correct Answer",
        help="For short_answer questions. Case-insensitive "
             "match against learner response (M10 scoring).",
    )
    points = fields.Integer(default=1)
    explanation = fields.Text(
        translate=True,
        help="Shown to learner after attempt for feedback. "
             "Optional but recommended.",
    )
    active = fields.Boolean(default=True)

    @api.constrains("question_type", "option_ids",
                    "correct_answer")
    def _check_question_completeness(self):
        """multiple_choice + true_false: at least one option
        with is_correct=True. short_answer: correct_answer
        non-empty.
        """
        for rec in self:
            if rec.question_type in (
                    "multiple_choice", "true_false"):
                if not rec.option_ids.filtered("is_correct"):
                    raise ValidationError(_(
                        "%(type)s question '%(text)s' must "
                        "have at least one option marked "
                        "is_correct=True."
                    ) % {
                        "type": dict(_QUESTION_TYPES).get(
                            rec.question_type),
                        "text": (rec.question_text
                                 or "(no text)")[:60],
                    })
            elif rec.question_type == "short_answer":
                if not (rec.correct_answer
                        and rec.correct_answer.strip()):
                    raise ValidationError(_(
                        "Short Answer question '%s' must "
                        "have correct_answer set."
                    ) % (rec.question_text or "(no text)")[:60])


class NeonLMSQuizOption(models.Model):
    _name = "neon.lms.quiz.option"
    _description = "Neon LMS Quiz Option"
    _order = "question_id, sequence asc, id asc"

    question_id = fields.Many2one(
        "neon.lms.quiz.question",
        string="Question",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    option_text = fields.Char(
        string="Option Text",
        required=True,
        translate=True,
    )
    is_correct = fields.Boolean(
        default=False,
        help="At least one option per multiple_choice / "
             "true_false question must be flagged correct.",
    )
