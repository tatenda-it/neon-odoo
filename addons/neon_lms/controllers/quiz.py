# -*- coding: utf-8 -*-
"""Phase 7i -- learner-facing review-quiz website controller.

Routes (auth='user', enrolled-members only) under /slides/neon/*:
  * /slides/neon/quizzes              -- index: tracks -> modules + status
  * /slides/neon/quiz/<module_id>     -- take the module's review quiz
  * /slides/neon/quiz/<module_id>/submit (POST) -- grade + record + result

Grading is server-authoritative: the controller creates the
attempt + responses as the learner, then calls
attempt.sudo()._grade_and_record() so the score is computed and
the completion workflow fed under elevated ACL (the learner has
no write access to scores or completion rows).
"""
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class NeonLMSQuizController(http.Controller):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _neon_channel(self):
        """The single branded Neon program channel, or None."""
        return request.env["slide.channel"].sudo().search(
            [("neon_branded", "=", True)], limit=1) or \
            request.env["slide.channel"].sudo().search(
                [("neon_track_ids", "!=", False)], limit=1)

    def _enrollment(self, channel):
        """The current user's enrollment row on the channel, or
        an empty recordset."""
        if not channel:
            return request.env["slide.channel.partner"].sudo()
        partner = request.env.user.partner_id
        return request.env["slide.channel.partner"].sudo().search([
            ("partner_id", "=", partner.id),
            ("channel_id", "=", channel.id),
        ], limit=1)

    def _module_status(self, module, enrollment):
        """Return ('locked'|'passed'|'in_progress'|'available',
        best_score_percent) for this module + learner."""
        user = request.env.user
        if not module.track_id._can_user_start(user):
            return ("locked", 0.0)
        score = 0.0
        state = "available"
        if enrollment:
            mc = request.env["neon.lms.module.completion"].sudo().search([
                ("enrollment_id", "=", enrollment.id),
                ("module_id", "=", module.id),
            ], limit=1)
            if mc:
                score = mc.quiz_score
                if mc.state == "completed":
                    state = "passed"
                elif mc.state == "in_progress":
                    state = "in_progress"
        return (state, round(score * 100.0, 1))

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------
    @http.route("/slides/neon/quizzes", type="http", auth="user",
                website=True)
    def neon_quiz_index(self, **kw):
        channel = self._neon_channel()
        if not channel:
            return request.render("neon_lms.quiz_not_available", {})
        enrollment = self._enrollment(channel)
        if not enrollment:
            return request.render("neon_lms.quiz_not_enrolled",
                                  {"channel": channel})
        tracks = []
        for track in channel.sudo().neon_track_ids.sorted(
                lambda t: (t.sequence, t.id)):
            modules = []
            for module in track.module_ids.sorted(
                    lambda m: (m.sequence_in_track, m.id)):
                status, pct = self._module_status(module, enrollment)
                modules.append({
                    "module": module,
                    "status": status,
                    "score_percent": pct,
                    "question_count": len(
                        module.sudo().quiz_question_ids.filtered("active")),
                })
            tracks.append({
                "track": track,
                "modules": modules,
                "locked": not track._can_user_start(request.env.user),
                "reason": track._reason_user_cannot_start(
                    request.env.user),
            })
        return request.render("neon_lms.quiz_index", {
            "channel": channel,
            "tracks": tracks,
        })

    # ------------------------------------------------------------------
    # Take a module quiz
    # ------------------------------------------------------------------
    def _get_module(self, module_id):
        module = request.env["neon.lms.module"].sudo().browse(module_id)
        if not module.exists():
            return None
        return module

    @http.route("/slides/neon/quiz/<int:module_id>", type="http",
                auth="user", website=True)
    def neon_quiz_take(self, module_id, **kw):
        module = self._get_module(module_id)
        if not module:
            return request.not_found()
        channel = module.channel_id
        enrollment = self._enrollment(channel)
        if not enrollment:
            return request.render("neon_lms.quiz_not_enrolled",
                                  {"channel": channel})
        if not module.track_id._can_user_start(request.env.user):
            return request.render("neon_lms.quiz_locked", {
                "module": module,
                "reason": module.track_id._reason_user_cannot_start(
                    request.env.user),
            })
        questions = module.sudo().quiz_question_ids.filtered(
            "active").sorted(lambda q: (q.sequence, q.id))
        return request.render("neon_lms.quiz_take", {
            "module": module,
            "questions": questions,
            "pass_mark_pct": round(
                (module.min_quiz_score or 0.0) * 100.0),
        })

    @http.route("/slides/neon/quiz/<int:module_id>/submit",
                type="http", auth="user", website=True,
                methods=["POST"])
    def neon_quiz_submit(self, module_id, **post):
        module = self._get_module(module_id)
        if not module:
            return request.not_found()
        channel = module.channel_id
        enrollment = self._enrollment(channel)
        if not enrollment:
            return request.render("neon_lms.quiz_not_enrolled",
                                  {"channel": channel})
        if not module.track_id._can_user_start(request.env.user):
            return request.render("neon_lms.quiz_locked", {
                "module": module,
                "reason": module.track_id._reason_user_cannot_start(
                    request.env.user),
            })
        questions = module.sudo().quiz_question_ids.filtered("active")

        # Build response command list from the posted form. Field
        # names: q_<question_id> (option id(s) for mc/tf,
        # free text for short_answer).
        response_cmds = []
        for q in questions:
            field = "q_%d" % q.id
            vals = {"question_id": q.id}
            if q.question_type == "short_answer":
                vals["text_response"] = (post.get(field) or "").strip()
            else:
                raw = request.httprequest.form.getlist(field)
                opt_ids = []
                for token in raw:
                    try:
                        opt_ids.append(int(token))
                    except (TypeError, ValueError):
                        continue
                # Defensive: only options that belong to this
                # question (a tampered form can't credit foreign
                # options).
                valid = set(q.option_ids.ids)
                opt_ids = [o for o in opt_ids if o in valid]
                vals["selected_option_ids"] = [(6, 0, opt_ids)]
            response_cmds.append((0, 0, vals))

        # Create the attempt as the learner (own record), then
        # grade + record in sudo (server-authoritative score).
        attempt = request.env["neon.lms.quiz.attempt"].create({
            "learner_id": request.env.user.id,
            "module_id": module.id,
            "response_ids": response_cmds,
        })
        attempt.sudo()._grade_and_record()

        # Re-read the (sudo) module completion for the fresh state.
        mc = request.env["neon.lms.module.completion"].sudo().search([
            ("enrollment_id", "=", enrollment.id),
            ("module_id", "=", module.id),
        ], limit=1)
        return request.render("neon_lms.quiz_result", {
            "module": module,
            "attempt": attempt.sudo(),
            "module_state": mc.state if mc else "not_started",
            "pass_mark_pct": round(
                (module.min_quiz_score or 0.0) * 100.0),
        })
