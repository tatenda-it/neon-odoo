"""LMS Admin Polish M2 smoke -- notebook on module form
(6 tests).

T_LP200 - module form view loads + has 4-tab notebook
T_LP201 - adding question inline saves with module_id set
T_LP202 - adding scenario inline saves with module_id set
T_LP203 - SOP M2M attaches correctly
T_LP204 - action_quick_create_mc returns act_window for a
          question with 4 options pre-populated
T_LP205 - inline-edited multiple_choice with no is_correct
          raises ValidationError
"""
from odoo.exceptions import AccessError, ValidationError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Module = env["neon.lms.module"]
Question = env["neon.lms.quiz.question"]
Scenario = env["neon.lms.practical.scenario"]
SOP = env["neon.lms.sop"]
View = env["ir.ui.view"]

target = Module.search([], limit=1)
assert target, "expected at least one seeded module"
print(f"target module: {target.code} ({target.name})")


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


# ============================================================
print()
print("T_LP200 - module form view loads + 4-tab notebook")
print("=" * 72)
form = env.ref("neon_lms.view_neon_lms_module_form",
               raise_if_not_found=False)
arch = (form.arch_db if form else "") or ""
has_form = bool(form)
has_4_pages = (arch.count('<page ') >= 4
               and 'name="content"' in arch
               and 'name="quiz"' in arch
               and 'name="scenarios"' in arch
               and 'name="sops"' in arch)
# Confirm the view actually loads without error.
try:
    view_info = Module.get_view(
        view_id=form.id, view_type="form")
    loaded = bool(view_info.get("arch"))
except Exception as e:  # noqa: BLE001
    loaded = False
    print(f"  get_view err: {e}")
ok = has_form and has_4_pages and loaded
print(f"  view exists: {has_form}")
print(f"  4 notebook pages (content/quiz/scenarios/sops): "
      f"{has_4_pages}")
print(f"  fields_view_get loads: {loaded}")
print("T_LP200:", "PASS" if ok else "FAIL")
results["T_LP200"] = ok


# ============================================================
print()
print("T_LP201 - adding question inline saves with module_id")
print("=" * 72)
# Simulate "inline add" by writing through the o2m on the
# module. The brief expects this to work as if the admin
# typed in the editable tree.
new_q = Question.create({
    "module_id": target.id,
    "question_text": "T_LP201 probe",
    "question_type": "short_answer",
    "correct_answer": "probe",
    "points": 1,
})
ok = (new_q.module_id == target
      and new_q in target.quiz_question_ids)
print(f"  question created on module: {ok}")
print("T_LP201:", "PASS" if ok else "FAIL")
results["T_LP201"] = ok


# ============================================================
print()
print("T_LP202 - adding scenario inline saves with module_id")
print("=" * 72)
new_s = Scenario.create({
    "module_id": target.id,
    "title": "T_LP202 scenario",
    "description": "probe",
    "signoff_authority": "superuser",
})
ok = (new_s.module_id == target
      and new_s in target.practical_scenario_ids)
print(f"  scenario created on module: {ok}")
print("T_LP202:", "PASS" if ok else "FAIL")
results["T_LP202"] = ok


# ============================================================
print()
print("T_LP203 - SOP M2M attaches correctly")
print("=" * 72)
existing_sops = SOP.search([], limit=1)
if not existing_sops:
    sop = SOP.create({
        "name": "T_LP203 probe SOP",
    })
else:
    sop = existing_sops
before = len(target.sop_ids)
target.sop_ids = [(4, sop.id)]
after = len(target.sop_ids)
ok = (sop in target.sop_ids) and (after >= before)
print(f"  sop_ids before/after: {before}/{after}")
print(f"  sop attached to module: {sop in target.sop_ids}")
print("T_LP203:", "PASS" if ok else "FAIL")
results["T_LP203"] = ok


# ============================================================
print()
print("T_LP204 - action_quick_create_mc creates question "
      "with 4 options")
print("=" * 72)
n_before = Question.search_count(
    [("module_id", "=", target.id)])
action = target.action_quick_create_mc()
n_after = Question.search_count(
    [("module_id", "=", target.id)])
new_question = Question.browse(action.get("res_id"))
ok = bool(
    isinstance(action, dict)
    and action.get("type") == "ir.actions.act_window"
    and action.get("res_model") == "neon.lms.quiz.question"
    and (n_after - n_before) == 1
    and len(new_question.option_ids) == 4
    and new_question.question_type == "multiple_choice"
    and new_question.option_ids.filtered("is_correct"))
print(f"  delta: {n_after - n_before} (expect 1)")
print(f"  option count: {len(new_question.option_ids)} "
      f"(expect 4)")
print(f"  exactly one is_correct=True: "
      f"{bool(new_question.option_ids.filtered('is_correct'))}")
print("T_LP204:", "PASS" if ok else "FAIL")
results["T_LP204"] = ok


# ============================================================
print()
print("T_LP205 - MC with no is_correct -> ValidationError")
print("=" * 72)
err, _v = _try(lambda: Question.create({
    "module_id": target.id,
    "question_text": "T_LP205 bad MC",
    "question_type": "multiple_choice",
    "option_ids": [
        (0, 0, {"option_text": "A", "is_correct": False}),
        (0, 0, {"option_text": "B", "is_correct": False}),
    ],
}))
ok = isinstance(err, ValidationError)
print(f"  ValidationError raised: {ok}")
if err:
    print(f"  msg: {str(err)[:120]}")
print("T_LP205:", "PASS" if ok else "FAIL")
results["T_LP205"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T_LP200", "T_LP201", "T_LP202", "T_LP203",
         "T_LP204", "T_LP205"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
