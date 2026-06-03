# -*- coding: utf-8 -*-
"""P7i browser-smoke fixture setup (idempotent, COMMITTED).

Run once before p7i_browser_smoke.py:
    odoo shell -d <db> --no-http < p7i_browser_setup.py

Creates the committed fixture the browser smoke logs into (the
harness uses password 'test123'): an enrolled learner
(p7i_blearner, crew tier) and a guaranteed-passable target
module -- a Foundations-gate module with NO practical scenario
(so a quiz pass alone completes it) and at least one question.

Real-data-safe: if the target already carries a question bank
(prod's 606), it is NOT polluted; deterministic fixture
questions are only added when the module has zero. The target's
completion is reset so the fail-then-pass run repeats.
"""
from odoo import fields  # noqa: F401

env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))

Users = env["res.users"].sudo()
Ch = env["slide.channel"].sudo()
Question = env["neon.lms.quiz.question"].sudo()
Enrollment = env["slide.channel.partner"].sudo()
ModuleComp = env["neon.lms.module.completion"].sudo()

crew = env.ref("neon_jobs.group_neon_jobs_crew")
base_user = env.ref("base.group_user")

ch = Ch.search([("neon_branded", "=", True)], limit=1) or \
    Ch.search([("neon_track_ids", "!=", False)], limit=1)
assert ch, "no Neon channel"

# Target: a Foundations-gate module with NO active practical scenario
# (quiz pass alone completes it -> deterministic for the browser smoke).
found = ch.neon_track_ids.filtered("is_foundation_gate")
candidates = found.module_ids.sorted(lambda m: (m.sequence_in_track, m.id))
target = next((m for m in candidates
               if not m.practical_scenario_ids.filtered("active")),
              candidates[0])

# Learner (committed; test123 so the browser harness can log in).
learner = Users.search([("login", "=", "p7i_blearner")], limit=1)
if not learner:
    learner = Users.create({
        "name": "P7i Browser Learner", "login": "p7i_blearner",
        "password": "test123", "email": "p7i_blearner@example.com",
        "groups_id": [(6, 0, [base_user.id, crew.id])]})

enr = Enrollment.search([
    ("partner_id", "=", learner.partner_id.id),
    ("channel_id", "=", ch.id)], limit=1)
if not enr:
    enr = Enrollment.create({
        "partner_id": learner.partner_id.id, "channel_id": ch.id,
        "member_status": "joined"})

# Only seed deterministic questions when the target has NONE (empty dev
# DB). Never pollute a real bank (prod). Two MC, correct option = "CORRECT".
if not target.quiz_question_ids.filtered("active"):
    for i in (1, 2):
        Question.create({
            "module_id": target.id,
            "question_text": "P7I-BROWSER question %d" % i,
            "question_type": "multiple_choice", "points": 1, "sequence": 10 * i,
            "option_ids": [
                (0, 0, {"option_text": "CORRECT", "is_correct": True, "sequence": 10}),
                (0, 0, {"option_text": "WRONG A", "is_correct": False, "sequence": 20}),
                (0, 0, {"option_text": "WRONG B", "is_correct": False, "sequence": 30}),
            ]})

enr._neon_ensure_completion_records()
mc = ModuleComp.search([
    ("enrollment_id", "=", enr.id), ("module_id", "=", target.id)], limit=1)
if mc:
    mc.write({"state": "not_started", "quiz_score": 0.0, "last_activity": False})

env.cr.commit()
print("P7i browser fixture ready: learner=%s target=%s questions=%d scenarios=%d" % (
    learner.login, target.code,
    len(target.quiz_question_ids.filtered("active")),
    len(target.practical_scenario_ids.filtered("active"))))
