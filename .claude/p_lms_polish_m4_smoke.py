"""LMS Admin Polish M4 smoke -- quick-create quiz templates
(4 tests).

T_LP400 - action_quick_create_mc creates question with 4
          options (also covered in M2; re-asserted via the
          M4 question-side wrapper action_template_mc)
T_LP401 - action_quick_create_tf creates 2 options
          (True / False)
T_LP402 - action_quick_create_sa creates short_answer
          question with placeholder correct_answer
T_LP403 - quick-create templates respect user's
          default_points preference if set via
          action_set_default_points
"""
print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Module = env["neon.lms.module"]
Question = env["neon.lms.quiz.question"]
ICP = env["ir.config_parameter"].sudo()

target = Module.search([], limit=1)
print(f"target module: {target.code} ({target.name})")

pref_key = "neon_lms.default_points.uid_%d" % env.uid
ICP.set_param(pref_key, "1")


# ============================================================
print()
print("T_LP400 - action_template_mc -> question with 4 "
      "options")
print("=" * 72)
# Create a seed question on the module so we have something
# to call the wrapper on.
seed = Question.create({
    "module_id": target.id,
    "question_text": "T_LP400 seed",
    "question_type": "short_answer",
    "correct_answer": "x",
})
n_before = Question.search_count(
    [("module_id", "=", target.id)])
action = seed.action_template_mc()
n_after = Question.search_count(
    [("module_id", "=", target.id)])
new_q = Question.browse(action.get("res_id"))
ok = bool(
    isinstance(action, dict)
    and action.get("res_model") == "neon.lms.quiz.question"
    and (n_after - n_before) == 1
    and len(new_q.option_ids) == 4
    and new_q.question_type == "multiple_choice"
    and new_q.option_ids.filtered("is_correct"))
print(f"  delta: {n_after - n_before} (expect 1)")
print(f"  options: {len(new_q.option_ids)} (expect 4)")
print(f"  type: {new_q.question_type}")
print("T_LP400:", "PASS" if ok else "FAIL")
results["T_LP400"] = ok


# ============================================================
print()
print("T_LP401 - action_template_tf -> 2 options "
      "(True/False)")
print("=" * 72)
n_before = Question.search_count(
    [("module_id", "=", target.id)])
action = seed.action_template_tf()
n_after = Question.search_count(
    [("module_id", "=", target.id)])
tf_q = Question.browse(action.get("res_id"))
ok = bool(
    (n_after - n_before) == 1
    and len(tf_q.option_ids) == 2
    and tf_q.question_type == "true_false"
    and set(tf_q.option_ids.mapped("option_text"))
    == {"True", "False"})
print(f"  delta: {n_after - n_before} (expect 1)")
print(f"  option labels: "
      f"{sorted(tf_q.option_ids.mapped('option_text'))}")
print("T_LP401:", "PASS" if ok else "FAIL")
results["T_LP401"] = ok


# ============================================================
print()
print("T_LP402 - action_template_sa -> short_answer with "
      "placeholder correct_answer")
print("=" * 72)
n_before = Question.search_count(
    [("module_id", "=", target.id)])
action = seed.action_template_sa()
n_after = Question.search_count(
    [("module_id", "=", target.id)])
sa_q = Question.browse(action.get("res_id"))
ok = bool(
    (n_after - n_before) == 1
    and sa_q.question_type == "short_answer"
    and len(sa_q.option_ids) == 0
    and (sa_q.correct_answer or "").strip()
    and "fill in" in (sa_q.correct_answer or "").lower())
print(f"  type: {sa_q.question_type}")
print(f"  options: {len(sa_q.option_ids)} (expect 0)")
print(f"  correct_answer: {sa_q.correct_answer!r}")
print("T_LP402:", "PASS" if ok else "FAIL")
results["T_LP402"] = ok


# ============================================================
print()
print("T_LP403 - templates respect default_points "
      "preference")
print("=" * 72)
# Persist points=5 as the default via action_set_default_points
sa_q.points = 5
sa_q.action_set_default_points()
# Confirm pref written.
persisted = ICP.get_param(pref_key)
# Spawn another MC -- should pick up default_points=5.
action = seed.action_template_mc()
templated = Question.browse(action.get("res_id"))
ok = (persisted == "5"
      and templated.points == 5)
print(f"  pref persisted: {persisted!r} (expect '5')")
print(f"  templated.points: {templated.points} (expect 5)")
print("T_LP403:", "PASS" if ok else "FAIL")
results["T_LP403"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T_LP400", "T_LP401", "T_LP402", "T_LP403"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
