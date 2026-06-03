# -*- coding: utf-8 -*-
"""P7i smoke -- LMS quiz attempts + the completion/cert chain.

Run:  odoo shell -d neon_p7i --no-http < p7i_smoke.py

Covers: grading for all 3 question types (multiple_choice /
true_false / short_answer), score computation, pass/fail vs
min_quiz_score, attempt numbering, that a passing attempt WRITES
quiz_score and FEEDS the existing _check_and_advance_to_completed
chain (module -> track -> sub-cert -> capstone) rather than
bypassing it, best-score semantics, completion-record
materialisation + idempotency, server-authoritative grading
(learner cannot write a score or forge another learner's
attempt), and the headline END-TO-END: a learner passing all 17
module quizzes earns 7 sub-certs + the capstone ORGANICALLY
(verified_by_id stamped by the issuance path).

All mutations run in-transaction and roll back at the end.
"""
from odoo import fields
from odoo.exceptions import AccessError

env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))

results = {}


def _check(name, ok, detail=""):
    results[name] = bool(ok)
    if not ok:
        print("  %s: FAIL %s" % (name, detail))


Ch = env["slide.channel"].sudo()
Users = env["res.users"].sudo()
Question = env["neon.lms.quiz.question"].sudo()
Attempt = env["neon.lms.quiz.attempt"]
ModuleComp = env["neon.lms.module.completion"].sudo()
TrackComp = env["neon.lms.track.completion"].sudo()
Enrollment = env["slide.channel.partner"].sudo()
Cert = env["neon.training.certification"].sudo()
ScenarioComp = env["neon.lms.scenario.completion"].sudo()

# Neutralise outgoing mail: a prod-cloned DB carries a real ir.mail_server,
# and the existing M12 cert-notification stub message_posts on cert issuance.
# In-tx (rolled back); keeps SMTP noise out of the run.
env["ir.mail_server"].sudo().search([]).write({"active": False})

ch = Ch.search([("neon_track_ids", "!=", False)], limit=1)
_check("T-P7I-00", bool(ch), "Neon channel with tracks exists")

crew = env.ref("neon_jobs.group_neon_jobs_crew")
base_user = env.ref("base.group_user")


def _mk_user(login):
    u = Users.search([("login", "=", login)], limit=1)
    if not u:
        # No email: keeps the cert-notification stub from queuing real mail.
        u = Users.create({
            "name": login, "login": login,
            "groups_id": [(6, 0, [base_user.id, crew.id])],
        })
    return u


def _signoff_scenarios(user, module):
    """Sign off every active practical scenario on the module for this
    learner (passed=True) -- mirrors the existing P7e M5 reviewer flow.
    A module with scenarios is gated on quiz AND scenario signoff; P7i
    feeds quiz_score, it does not bypass the scenario gate.

    NB: module.completion.scenarios_completed is a non-stored compute that
    does not @depend on scenario.completion, so within ONE transaction it
    can read stale. In production each signoff is a separate request (fresh
    env -> fresh compute). We reproduce that here by invalidating + running
    the advance once after all signoffs, rather than masking the gate."""
    scenarios = module.sudo().practical_scenario_ids.filtered("active")
    for sc in scenarios:
        comp = ScenarioComp.search([
            ("learner_id", "=", user.id), ("scenario_id", "=", sc.id)], limit=1)
        if not comp:
            comp = ScenarioComp.create({
                "learner_id": user.id, "scenario_id": sc.id})
        comp.write({"passed": True, "signed_off_by_id": env.uid,
                    "signoff_date": fields.Datetime.now()})
    if not scenarios:
        return
    enr = Enrollment.search([
        ("partner_id", "=", user.partner_id.id),
        ("channel_id", "=", module.channel_id.id)], limit=1)
    mc = ModuleComp.search([
        ("enrollment_id", "=", enr.id), ("module_id", "=", module.id)], limit=1)
    if mc:
        mc.invalidate_recordset(["scenarios_completed", "scenarios_total"])
        mc._check_and_advance_to_completed()


def _enroll(user):
    enr = Enrollment.search([
        ("partner_id", "=", user.partner_id.id),
        ("channel_id", "=", ch.id)], limit=1)
    if not enr:
        enr = Enrollment.create({
            "partner_id": user.partner_id.id, "channel_id": ch.id})
    return enr


learner = _mk_user("p7i_learner")
other = _mk_user("p7i_other")
e2e = _mk_user("p7i_e2e")
_enroll(learner)
_enroll(e2e)


# ---- question fixtures (cloned DB has 0 questions: create our own) ----
def mk_mc(module, seq=10, ncorrect=1):
    opts = [(0, 0, {"option_text": "A", "is_correct": True, "sequence": 10})]
    if ncorrect >= 2:
        opts.append((0, 0, {"option_text": "B", "is_correct": True, "sequence": 20}))
    else:
        opts.append((0, 0, {"option_text": "B", "is_correct": False, "sequence": 20}))
    opts.append((0, 0, {"option_text": "C", "is_correct": False, "sequence": 30}))
    opts.append((0, 0, {"option_text": "D", "is_correct": False, "sequence": 40}))
    return Question.create({
        "module_id": module.id, "question_text": "MC q %d" % seq,
        "question_type": "multiple_choice", "points": 1, "sequence": seq,
        "option_ids": opts})


def mk_tf(module, seq=10, true_correct=True):
    return Question.create({
        "module_id": module.id, "question_text": "TF q %d" % seq,
        "question_type": "true_false", "points": 1, "sequence": seq,
        "option_ids": [
            (0, 0, {"option_text": "True", "is_correct": true_correct, "sequence": 10}),
            (0, 0, {"option_text": "False", "is_correct": not true_correct, "sequence": 20})]})


def mk_sa(module, answer="Dante", seq=10):
    return Question.create({
        "module_id": module.id, "question_text": "SA q %d" % seq,
        "question_type": "short_answer", "points": 1, "sequence": seq,
        "correct_answer": answer})


# Seed every module with 2 MC (so the e2e learner can pass each),
# and add one TF + one SA to the first Foundations module for the
# 3-type grading tests.
modules = env["neon.lms.module"].sudo().search([])
for m in modules:
    mk_mc(m, seq=10)
    mk_mc(m, seq=20)

found_track = ch.neon_track_ids.filtered("is_foundation_gate")
m01 = found_track.module_ids.sorted(lambda x: (x.sequence_in_track, x.id))[0]
# Dedicated, captured-by-handle questions for the grading unit tests
# (high sequences so they never collide with the generic seed above or
# any pre-existing questions on the module -- the smoke must be robust
# on a DB that already carries a question bank, e.g. prod's 606).
tf_q = mk_tf(m01, seq=130, true_correct=True)
sa_q = mk_sa(m01, answer="Dante", seq=140)
mc1 = mk_mc(m01, seq=110)
mc2 = mk_mc(m01, seq=120)
# Make m01 scenario-gated on EVERY dataset (prod modules already carry
# practical scenarios; an empty clone has none). This makes the no-bypass
# test deterministic: a passing quiz must NOT complete a module that still
# has an unsigned scenario.
env["neon.lms.practical.scenario"].sudo().create({
    "module_id": m01.id, "title": "P7I gate scenario",
    "description": "P7i no-bypass gate scenario",
    "signoff_authority": "superuser"})


def build_cmds(module, correct=True):
    cmds = []
    for q in module.quiz_question_ids.filtered("active").sorted(
            lambda x: (x.sequence, x.id)):
        if q.question_type in ("multiple_choice", "true_false"):
            opts = (q.option_ids.filtered("is_correct") if correct
                    else q.option_ids.filtered(lambda o: not o.is_correct))
            cmds.append((0, 0, {"question_id": q.id,
                                "selected_option_ids": [(6, 0, opts.ids)]}))
        else:
            cmds.append((0, 0, {
                "question_id": q.id,
                "text_response": (q.correct_answer if correct else "wrong-xyz")}))
    return cmds


def attempt(user, module, correct=True):
    att = Attempt.with_user(user).create({
        "learner_id": user.id, "module_id": module.id,
        "response_ids": build_cmds(module, correct=correct)})
    att.sudo()._grade_and_record()
    return att.sudo()


# =====================================================================
# 1-8  grading per question type
# =====================================================================
# Craft a single attempt with mixed correctness (4 explicit responses on
# the captured-handle questions) to inspect each response in isolation.
mc1_correct = mc1.option_ids.filtered("is_correct")
mc1_wrong = mc1.option_ids.filtered(lambda o: not o.is_correct)[:1]
tf_correct = tf_q.option_ids.filtered("is_correct")
tf_wrong = tf_q.option_ids.filtered(lambda o: not o.is_correct)

mixed = Attempt.with_user(learner).create({
    "learner_id": learner.id, "module_id": m01.id,
    "response_ids": [
        (0, 0, {"question_id": mc1.id, "selected_option_ids": [(6, 0, mc1_correct.ids)]}),         # correct
        (0, 0, {"question_id": mc2.id, "selected_option_ids": [(6, 0, mc2.option_ids.filtered(lambda o: not o.is_correct)[:1].ids)]}),  # wrong (single incorrect opt)
        (0, 0, {"question_id": tf_q.id, "selected_option_ids": [(6, 0, tf_wrong.ids)]}),            # wrong
        (0, 0, {"question_id": sa_q.id, "text_response": "  dANTE "}),                              # correct (normalised)
    ]})
mixed.sudo()._grade()
r_by_q = {r.question_id.id: r for r in mixed.response_ids}
_check("T-P7I-01", r_by_q[mc1.id].is_correct is True, "MC all-correct -> correct")
_check("T-P7I-02", r_by_q[mc2.id].is_correct is False, "MC wrong option -> incorrect")
_check("T-P7I-04", r_by_q[tf_q.id].is_correct is False, "TF wrong -> incorrect")
_check("T-P7I-06", r_by_q[sa_q.id].is_correct is True,
       "SA case+whitespace-insensitive match ('  dANTE ' == 'Dante')")

# MC partial credit: select a subset of correct (needs a 2-correct MC)
mc_multi = mk_mc(m01, seq=50, ncorrect=2)
correct_opts = mc_multi.option_ids.filtered("is_correct")
part = Attempt.with_user(learner).create({
    "learner_id": learner.id, "module_id": m01.id,
    "response_ids": [(0, 0, {"question_id": mc_multi.id,
                             "selected_option_ids": [(6, 0, correct_opts[:1].ids)]})]})
part.sudo()._grade()
_check("T-P7I-03", part.response_ids[0].is_correct is False,
       "MC partial selection (subset of correct) -> incorrect (exact match)")

tf_ok = Attempt.with_user(learner).create({
    "learner_id": learner.id, "module_id": m01.id,
    "response_ids": [(0, 0, {"question_id": tf_q.id,
                             "selected_option_ids": [(6, 0, tf_correct.ids)]})]})
tf_ok.sudo()._grade()
_check("T-P7I-05", tf_ok.response_ids[0].is_correct is True, "TF correct -> correct")

sa_bad = Attempt.with_user(learner).create({
    "learner_id": learner.id, "module_id": m01.id,
    "response_ids": [(0, 0, {"question_id": sa_q.id, "text_response": "ethernet"})]})
sa_bad.sudo()._grade()
_check("T-P7I-07", sa_bad.response_ids[0].is_correct is False, "SA mismatch -> incorrect")

sa_ws = Attempt.with_user(learner).create({
    "learner_id": learner.id, "module_id": m01.id,
    "response_ids": [(0, 0, {"question_id": sa_q.id, "text_response": "DANTE"})]})
sa_ws.sudo()._grade()
_check("T-P7I-08", sa_ws.response_ids[0].is_correct is True, "SA uppercase match")

# =====================================================================
# 9-12  score computation + pass/fail + attempt numbering
# =====================================================================
# mixed attempt: 4 questions (1pt each), 2 correct (mc1 + sa) -> 0.5
_check("T-P7I-09", abs(mixed.score - 0.5) < 0.001,
       "score = earned/possible (2/4 = 0.5): got %s" % mixed.score)
_check("T-P7I-10", mixed.passed is False,
       "0.5 < min_quiz_score 0.8 -> not passed")

full = attempt(learner, m01, correct=True)
_check("T-P7I-11", full.passed is True,
       "all-correct attempt passes (score %s >= mark %s)"
       % (full.score, m01.min_quiz_score))

n_before = Attempt.sudo().search_count([
    ("learner_id", "=", learner.id), ("module_id", "=", m01.id)])
again = attempt(learner, m01, correct=True)
_check("T-P7I-12", again.attempt_number == n_before + 1,
       "attempt_number increments per (learner, module): %s vs %s"
       % (again.attempt_number, n_before + 1))

# =====================================================================
# 13-16  quiz_score written + chain FED (not bypassed) + best-score
# =====================================================================
enr_l = _enroll(learner)
mc_m01 = ModuleComp.search([("enrollment_id", "=", enr_l.id),
                            ("module_id", "=", m01.id)], limit=1)
# 'full' (T11) is a passing attempt on m01; quiz_score is the best score.
_check("T-P7I-13",
       full.passed and mc_m01 and abs(mc_m01.quiz_score - full.score) < 1e-6,
       "passing quiz writes module.completion.quiz_score=%s (pass mark %s)"
       % (mc_m01.quiz_score if mc_m01 else None, m01.min_quiz_score))
# NO-BYPASS: quiz passed, but m01 has an unsigned practical scenario, so
# the EXISTING gate keeps it in_progress. P7i feeds quiz_score; it does
# not bypass the scenario requirement.
_check("T-P7I-14", mc_m01 and mc_m01.state != "completed",
       "scenario-gated module NOT completed on quiz alone (state=%s)"
       % (mc_m01.state if mc_m01 else None))
# Sign off the scenario(s) -> the existing chain now completes the module.
_signoff_scenarios(learner, m01)
mc_m01.invalidate_recordset()
_check("T-P7I-15", mc_m01.state == "completed",
       "module completes once quiz>=mark AND scenarios signed (state=%s)"
       % mc_m01.state)
# best-score: a later failing attempt must NOT lower quiz_score or
# un-complete the module.
score_before = mc_m01.quiz_score
fail_after = attempt(learner, m01, correct=False)
mc_m01.invalidate_recordset()
_check("T-P7I-16",
       (not fail_after.passed) and mc_m01.quiz_score >= score_before
       and mc_m01.state == "completed",
       "best-score: fail (passed=%s) doesn't lower score (%s>=%s) or "
       "un-complete (%s)" % (fail_after.passed, mc_m01.quiz_score,
                             score_before, mc_m01.state))

# =====================================================================
# 17  materialisation creates 7 track + 17 module rows; idempotent
# =====================================================================
enr_e = _enroll(e2e)
enr_e._neon_ensure_completion_records()
tc_n = TrackComp.search_count([("enrollment_id", "=", enr_e.id)])
mc_n = ModuleComp.search_count([("enrollment_id", "=", enr_e.id)])
enr_e._neon_ensure_completion_records()  # 2nd call: must be a no-op
tc_n2 = TrackComp.search_count([("enrollment_id", "=", enr_e.id)])
mc_n2 = ModuleComp.search_count([("enrollment_id", "=", enr_e.id)])
_check("T-P7I-17",
       tc_n == 7 and mc_n == 17 and tc_n2 == 7 and mc_n2 == 17,
       "materialise 7 track + 17 module rows, idempotent (%s/%s -> %s/%s)"
       % (tc_n, mc_n, tc_n2, mc_n2))

# =====================================================================
# 18  feed-not-bypass: an impossible pass mark never completes
# =====================================================================
sandbox_track = ch.neon_track_ids.filtered(
    lambda t: t.code == "TRK_RIGGING")
mx = sandbox_track.module_ids[0]
orig_min = mx.min_quiz_score
mx.write({"min_quiz_score": 1.5})
guard = attempt(learner, mx, correct=True)
mc_mx = ModuleComp.search([("enrollment_id", "=", enr_l.id),
                           ("module_id", "=", mx.id)], limit=1)
_check("T-P7I-18",
       guard.score >= 0.99 and not guard.passed
       and (not mc_mx or mc_mx.state != "completed"),
       "score 1.0 but pass-mark 1.5 -> not passed, not completed "
       "(existing min_quiz_score gate is fed, not bypassed)")
mx.write({"min_quiz_score": orig_min})

# =====================================================================
# 19-20  END-TO-END: learner passes all 17 quizzes + signs off every
#        practical scenario -> 7 sub-certs + capstone. (On the real
#        prod bank 6 modules carry scenarios, so quiz-pass alone is
#        necessary but not sufficient -- this proves the FULL chain.)
# =====================================================================
certs_before = Cert.search_count([("user_id", "=", e2e.id)])
# Process tracks foundation-first (mirrors the prereq order learners
# follow); the chain issues per-track on the last module of each track.
ordered_tracks = ch.neon_track_ids.sorted(
    lambda t: (0 if t.is_foundation_gate else 1, t.sequence, t.id))
e2e_error = ""
try:
    for trk in ordered_tracks:
        for mod in trk.module_ids.sorted(lambda x: (x.sequence_in_track, x.id)):
            attempt(e2e, mod, correct=True)   # pass the real quiz
            _signoff_scenarios(e2e, mod)       # + sign off any scenarios
except Exception as exc:  # surface, don't abort the summary line
    e2e_error = repr(exc)

enr_e.invalidate_recordset()
track_comps = TrackComp.search([("enrollment_id", "=", enr_e.id)])
certified = track_comps.filtered(lambda tc: tc.state == "certified")
sub_certs = certified.mapped("sub_cert_id")
_check("T-P7I-19a", not e2e_error, "end-to-end ran without error: %s" % e2e_error)
_check("T-P7I-19b", len(certified) == 7,
       "all 7 tracks certified: %d" % len(certified))
_check("T-P7I-19c", len(sub_certs) == 7 and all(sub_certs.mapped("verified_by_id")),
       "7 sub-certs issued, each verified_by_id stamped by issuance path")
_check("T-P7I-19d", enr_e.neon_state == "certified",
       "enrollment neon_state=certified: %s" % enr_e.neon_state)
_check("T-P7I-19e", bool(enr_e.neon_capstone_cert_id)
       and bool(enr_e.neon_capstone_cert_id.verified_by_id),
       "capstone cert issued + verified_by_id stamped")

certs_after = Cert.search_count([("user_id", "=", e2e.id)])
new_certs = Cert.search([("user_id", "=", e2e.id)])
_check("T-P7I-20a", certs_after - certs_before == 8,
       "exactly 8 certs created organically (7 sub + capstone): %d"
       % (certs_after - certs_before))
_check("T-P7I-20b", all(c.verified_by_id for c in new_certs),
       "every issued cert carries verified_by_id (none manual/unverified)")

# =====================================================================
# 21-24  security: server-authoritative grading + own-row
# =====================================================================
# 21 learner CAN create own attempt (already exercised above via with_user)
own = Attempt.with_user(learner).search_count([("learner_id", "=", learner.id)])
_check("T-P7I-21", own > 0, "learner can create + read own attempts (%d)" % own)

# 22 learner CANNOT write a score (no write ACL -> server-authoritative)
t22 = False
try:
    full.with_user(learner).write({"score": 1.0})
except AccessError:
    t22 = True
except Exception:
    t22 = True
_check("T-P7I-22", t22, "learner cannot write attempt.score (AccessError)")

# 23 learner CANNOT forge an attempt for another learner (own-row create)
t23 = False
try:
    Attempt.with_user(learner).create({
        "learner_id": other.id, "module_id": m01.id})
except AccessError:
    t23 = True
except Exception:
    t23 = True
_check("T-P7I-23", t23,
       "learner cannot create an attempt for another learner")

# 24 learner cannot read another learner's attempt (own-row read)
seen_other = Attempt.with_user(learner).search([
    ("learner_id", "=", e2e.id)])
_check("T-P7I-24", len(seen_other) == 0,
       "own-row read rule hides other learners' attempts: saw %d"
       % len(seen_other))

# =====================================================================
# 25  a module with ZERO questions cannot be passed/completed vacuously
# =====================================================================
zero_mod = env["neon.lms.module"].sudo().create({
    "code": "P7I_ZEROQ", "name": "Zero-question test module",
    "track_id": found_track.id, "sequence_in_track": 999,
    "min_quiz_score": 0.8})
z_att = attempt(learner, zero_mod, correct=True)  # 0 questions -> 0 responses
z_mc = ModuleComp.search([("enrollment_id", "=", enr_l.id),
                          ("module_id", "=", zero_mod.id)], limit=1)
_check("T-P7I-25",
       z_att.score == 0.0 and not z_att.passed
       and (not z_mc or z_mc.state != "completed"),
       "0-question module: score=%s passed=%s state=%s -> no vacuous "
       "completion" % (z_att.score, z_att.passed,
                       z_mc.state if z_mc else None))

# =====================================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print("Total: {}/{} passed".format(passed, total))
for k in sorted(results):
    if not results[k]:
        print("  {}: FAIL".format(k))

env.cr.rollback()
