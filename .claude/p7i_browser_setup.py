# -*- coding: utf-8 -*-
"""P7i browser-smoke fixture setup (idempotent, COMMITTED).

Run once before p7i_browser_smoke.py:
    odoo shell -d <db> --no-http < p7i_browser_setup.py

Creates the committed fixture the browser smoke logs into (the
harness uses password 'test123'): an enrolled learner
(p7i_blearner, crew tier), two deterministic multiple-choice
questions on the Foundations first module (correct option text
'CORRECT', distractors 'WRONG A'/'WRONG B' so Playwright can
pick by visible text), the materialised completion rows, and a
reset of that module's completion so the fail-then-pass run is
repeatable.

Analogous to the seed/migration data other browser smokes rely
on (e.g. p7g's branded channel). Superuser context; commits.
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

found = ch.neon_track_ids.filtered("is_foundation_gate")
m01 = found.module_ids.sorted(lambda x: (x.sequence_in_track, x.id))[0]

# Learner (committed; test123 so the browser harness can log in).
learner = Users.search([("login", "=", "p7i_blearner")], limit=1)
if not learner:
    learner = Users.create({
        "name": "P7i Browser Learner",
        "login": "p7i_blearner",
        "password": "test123",
        "email": "p7i_blearner@example.com",
        "groups_id": [(6, 0, [base_user.id, crew.id])],
    })

# Enrollment.
enr = Enrollment.search([
    ("partner_id", "=", learner.partner_id.id),
    ("channel_id", "=", ch.id)], limit=1)
if not enr:
    enr = Enrollment.create({
        "partner_id": learner.partner_id.id,
        "channel_id": ch.id,
        "member_status": "joined",
    })

# Two deterministic MC questions on M01 (idempotent by marker text).
MARKER = "P7I-BROWSER"
existing = Question.search([
    ("module_id", "=", m01.id),
    ("question_text", "=like", MARKER + "%")])
if len(existing) < 2:
    existing.unlink() if existing else None
    for i in (1, 2):
        Question.create({
            "module_id": m01.id,
            "question_text": "%s question %d" % (MARKER, i),
            "question_type": "multiple_choice",
            "points": 1,
            "sequence": 10 * i,
            "option_ids": [
                (0, 0, {"option_text": "CORRECT", "is_correct": True, "sequence": 10}),
                (0, 0, {"option_text": "WRONG A", "is_correct": False, "sequence": 20}),
                (0, 0, {"option_text": "WRONG B", "is_correct": False, "sequence": 30}),
            ],
        })

# Materialise + reset this module's completion so the run repeats.
enr._neon_ensure_completion_records()
mc = ModuleComp.search([
    ("enrollment_id", "=", enr.id),
    ("module_id", "=", m01.id)], limit=1)
if mc:
    mc.write({"state": "not_started", "quiz_score": 0.0,
              "last_activity": False})

env.cr.commit()
print("P7i browser fixture ready: learner=%s module=%s questions=%d" % (
    learner.login, m01.code,
    Question.search_count([("module_id", "=", m01.id),
                           ("question_text", "=like", MARKER + "%")])))
