# -*- coding: utf-8 -*-
"""neon.lms.quiz.attempt + neon.lms.quiz.attempt.response.

Phase 7i -- the learner-facing quiz-attempt surface that was
designed into the schema as the "M10 attempts model" but never
built. This is the missing link: a learner submits an attempt
at a module's quiz, the attempt is graded server-side, and the
resulting score is written to neon.lms.module.completion.
quiz_score -- which FEEDS the existing module -> track -> cert
workflow (it does NOT duplicate or bypass it).

Append-only audit (perm_unlink=0). Grading is server-
authoritative: the learner has create+read only on attempts,
never write -- the score is computed in sudo() so it cannot be
tampered with from the website surface.

⚠️ DECISION (P7i, marker 1): short_answer grading is a
case-insensitive, whitespace-collapsed exact match against
question.correct_answer (the neon.lms.quiz.question help text
specifies "Case-insensitive match against learner response").
Only 5 / 606 questions are short_answer. Flagged at Gate 1:
exact-match is strict for free text; admins can convert those
to multiple_choice if it proves too rigid.

⚠️ DECISION (P7i, marker 2): retake policy is unlimited
retakes, BEST score counts. _record_to_completion only ever
RAISES module.completion.quiz_score, never lowers it -- so a
pass (and any cert it earned) is never undone by a later
weaker attempt.
"""
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


_ATTEMPT_STATES = [
    ("in_progress", "In Progress"),
    ("graded", "Graded"),
]


def _normalize_answer(value):
    """Normalise a free-text answer for short_answer matching:
    lowercase (casefold), strip, and collapse internal runs of
    whitespace to a single space. Empty/None -> ''."""
    if not value:
        return ""
    return " ".join(str(value).split()).casefold()


class NeonLMSQuizAttempt(models.Model):
    _name = "neon.lms.quiz.attempt"
    _description = "Neon LMS Quiz Attempt"
    _order = "learner_id, module_id, attempt_number desc, id desc"

    learner_id = fields.Many2one(
        "res.users",
        string="Learner",
        required=True,
        ondelete="restrict",
        index=True,
    )
    module_id = fields.Many2one(
        "neon.lms.module",
        string="Module",
        required=True,
        ondelete="restrict",
        index=True,
    )
    attempt_number = fields.Integer(
        string="Attempt #",
        readonly=True,
        copy=False,
        default=1,
        help="1-indexed per (learner, module). Set at create "
             "from the count of prior attempts.",
    )
    state = fields.Selection(
        _ATTEMPT_STATES,
        string="State",
        default="in_progress",
        required=True,
        index=True,
    )
    started_at = fields.Datetime(
        readonly=True,
        copy=False,
        default=fields.Datetime.now,
    )
    submitted_at = fields.Datetime(
        readonly=True,
        copy=False,
    )
    response_ids = fields.One2many(
        "neon.lms.quiz.attempt.response",
        "attempt_id",
        string="Responses",
    )
    score = fields.Float(
        string="Score",
        readonly=True,
        copy=False,
        default=0.0,
        help="0-1 scale. points_earned / points_possible. "
             "Computed server-side at grade time.",
    )
    score_percent = fields.Float(
        string="Score %",
        compute="_compute_score_percent",
        store=True,
    )
    passed = fields.Boolean(
        string="Passed",
        readonly=True,
        copy=False,
        help="score >= module.min_quiz_score at grade time.",
    )
    points_earned = fields.Integer(readonly=True, copy=False)
    points_possible = fields.Integer(readonly=True, copy=False)
    min_quiz_score = fields.Float(
        related="module_id.min_quiz_score",
        string="Pass Mark",
        readonly=True,
    )
    track_id = fields.Many2one(
        related="module_id.track_id",
        string="Track",
        store=True,
        readonly=True,
    )
    active = fields.Boolean(default=True)

    @api.depends("score")
    def _compute_score_percent(self):
        for rec in self:
            rec.score_percent = round((rec.score or 0.0) * 100.0, 1)

    @api.model_create_multi
    def create(self, vals_list):
        """Stamp attempt_number from the count of prior attempts
        for the same (learner, module). Done here (not a compute)
        because it's a point-in-time sequence, not a derived
        value that should recompute."""
        for vals in vals_list:
            learner = vals.get("learner_id")
            module = vals.get("module_id")
            if learner and module and not vals.get("attempt_number"):
                prior = self.sudo().search_count([
                    ("learner_id", "=", learner),
                    ("module_id", "=", module),
                ])
                vals["attempt_number"] = prior + 1
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Grading -- server-authoritative. Called via sudo() from the
    # website controller after the learner's responses are created.
    # ------------------------------------------------------------------
    def _grade(self):
        """Grade every response against its question, set
        per-response is_correct + points_awarded, then roll up
        score / passed / points on the attempt. Returns self."""
        self.ensure_one()
        points_possible = 0
        points_earned = 0
        for resp in self.response_ids:
            question = resp.question_id
            pts = question.points or 1
            points_possible += pts
            correct = resp._evaluate()
            resp.write({
                "is_correct": correct,
                "points_awarded": pts if correct else 0,
            })
            if correct:
                points_earned += pts
        score = (points_earned / points_possible) if points_possible else 0.0
        self.write({
            "points_possible": points_possible,
            "points_earned": points_earned,
            "score": score,
            "passed": score >= (self.module_id.min_quiz_score or 0.0),
            "state": "graded",
            "submitted_at": fields.Datetime.now(),
        })
        return self

    def _grade_and_record(self):
        """Grade the attempt and feed the result into the
        existing completion workflow. The single entry point the
        controller calls (in sudo)."""
        self.ensure_one()
        self._grade()
        self._record_to_completion()
        return self

    def _record_to_completion(self):
        """Write the (best) score onto the learner's
        neon.lms.module.completion for this module, which fires
        neon.lms.module.completion.write() -> the existing
        _check_and_advance_to_completed chain (module -> track ->
        sub-cert -> capstone). We FEED that logic; we never
        re-implement it.

        Best-score: only RAISE quiz_score, never lower it.
        """
        self.ensure_one()
        partner = self.learner_id.partner_id
        channel = self.module_id.channel_id
        if not partner or not channel:
            _logger.warning(
                "neon_lms P7i: attempt %s has no partner/channel; "
                "completion not recorded.", self.id)
            return False
        Enrollment = self.env["slide.channel.partner"].sudo()
        enrollment = Enrollment.search([
            ("partner_id", "=", partner.id),
            ("channel_id", "=", channel.id),
        ], limit=1)
        if not enrollment:
            # Learner reached a quiz without an enrollment row.
            # The controller guards against this; log defensively.
            _logger.warning(
                "neon_lms P7i: no enrollment for partner %s on "
                "channel %s; completion not recorded.",
                partner.id, channel.id)
            return False
        # Materialise the completion rows (idempotent). Without
        # the track.completion row the module->track rollup has
        # nothing to find and no cert ever issues.
        enrollment._neon_ensure_completion_records()
        ModuleComp = self.env["neon.lms.module.completion"].sudo()
        mc = ModuleComp.search([
            ("enrollment_id", "=", enrollment.id),
            ("module_id", "=", self.module_id.id),
        ], limit=1)
        if not mc:
            _logger.warning(
                "neon_lms P7i: module.completion missing after "
                "materialisation (enrollment %s, module %s).",
                enrollment.id, self.module_id.id)
            return False
        vals = {"last_activity": fields.Datetime.now()}
        if mc.state == "not_started":
            vals["state"] = "in_progress"
        if self.score > mc.quiz_score:
            # The actual trigger: writing quiz_score fires the
            # advance chain via module.completion.write().
            vals["quiz_score"] = self.score
        mc.write(vals)
        return True


class NeonLMSQuizAttemptResponse(models.Model):
    _name = "neon.lms.quiz.attempt.response"
    _description = "Neon LMS Quiz Attempt Response"
    _order = "attempt_id, question_id, id"

    attempt_id = fields.Many2one(
        "neon.lms.quiz.attempt",
        string="Attempt",
        required=True,
        ondelete="cascade",
        index=True,
    )
    question_id = fields.Many2one(
        "neon.lms.quiz.question",
        string="Question",
        required=True,
        ondelete="restrict",
        index=True,
    )
    question_type = fields.Selection(
        related="question_id.question_type",
        string="Type",
        readonly=True,
    )
    selected_option_ids = fields.Many2many(
        "neon.lms.quiz.option",
        "neon_lms_attempt_response_option_rel",
        "response_id",
        "option_id",
        string="Selected Options",
        help="For multiple_choice / true_false responses.",
    )
    text_response = fields.Char(
        string="Text Response",
        help="For short_answer responses.",
    )
    is_correct = fields.Boolean(readonly=True, copy=False)
    points_awarded = fields.Integer(readonly=True, copy=False)

    def _evaluate(self):
        """Return True if this response is correct. Pure read of
        the question + the learner's selection; no writes.

        multiple_choice / true_false: the set of selected options
        must EXACTLY equal the set of options flagged is_correct
        (all correct options chosen, no incorrect ones), and be
        non-empty.

        short_answer: normalised text match against
        question.correct_answer (⚠️ DECISION marker 1).
        """
        self.ensure_one()
        question = self.question_id
        if question.question_type in ("multiple_choice", "true_false"):
            correct_opts = question.option_ids.filtered("is_correct")
            if not correct_opts:
                return False
            return (set(self.selected_option_ids.ids)
                    == set(correct_opts.ids))
        if question.question_type == "short_answer":
            if not question.correct_answer:
                return False
            return (_normalize_answer(self.text_response)
                    == _normalize_answer(question.correct_answer))
        return False
