"""LMS Admin Polish M1 smoke -- bulk quiz import wizard
(8 tests).

T_LP100 - action_parse_preview populates preview_html
T_LP101 - dry_run mode creates no records
T_LP102 - import mode with 3-row CSV creates 3 questions
T_LP103 - malformed row (missing question_text) -> skipped
T_LP104 - multiple_choice with no is_correct -> error in
          preview (row marked error; not created on import)
T_LP105 - true_false row -> 2 options (True/False)
T_LP106 - short_answer row -> no options, correct_answer set
T_LP107 - file upload alternative populates csv_data identically
"""
from odoo.exceptions import UserError, ValidationError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Wizard = env["neon.lms.quiz.import.wizard"]
Question = env["neon.lms.quiz.question"]
Module = env["neon.lms.module"]

target = Module.search([], limit=1)
assert target, "expected at least one seeded neon.lms.module"
print(f"target module: {target.code} ({target.name})")


def _make_wizard(**vals):
    base = {"module_id": target.id}
    base.update(vals)
    return Wizard.create(base)


_CSV_HEADER = (
    "question_text,type,option_1_text,option_1_correct,"
    "option_2_text,option_2_correct,option_3_text,"
    "option_3_correct,option_4_text,option_4_correct,"
    "points,explanation,correct_answer")


def _row(**kw):
    cols = ["question_text", "type",
            "option_1_text", "option_1_correct",
            "option_2_text", "option_2_correct",
            "option_3_text", "option_3_correct",
            "option_4_text", "option_4_correct",
            "points", "explanation", "correct_answer"]
    return ",".join(str(kw.get(c, "")) for c in cols)


# ============================================================
print()
print("T_LP100 - action_parse_preview populates preview_html")
print("=" * 72)
csv_3rows = "\n".join([
    _CSV_HEADER,
    _row(question_text="Cap 1 of 'How To Hire'?",
         type="mc",
         option_1_text="A", option_1_correct="True",
         option_2_text="B", option_2_correct="False",
         option_3_text="C", option_3_correct="False",
         option_4_text="D", option_4_correct="False",
         points="2", explanation="see slide 3"),
    _row(question_text="Is the sky blue?",
         type="tf", option_1_correct="True",
         option_2_correct="False"),
    _row(question_text="Define ROI",
         type="sa", correct_answer="return on investment"),
])
w = _make_wizard(csv_data=csv_3rows, mode="dry_run")
w.action_parse_preview()
ok = bool(w.preview_html) and "rows parsed" in w.preview_html
print(f"  preview length: "
      f"{len(w.preview_html) if w.preview_html else 0}")
print(f"  has_preview flag: {w.has_preview}")
print("T_LP100:", "PASS" if ok else "FAIL")
results["T_LP100"] = ok


# ============================================================
print()
print("T_LP101 - dry_run creates no records")
print("=" * 72)
n_before = Question.search_count(
    [("module_id", "=", target.id)])
w2 = _make_wizard(csv_data=csv_3rows, mode="dry_run")
w2.action_parse_preview()
# Pressing Import in dry_run mode should raise UserError.
err = None
try:
    with env.cr.savepoint():
        w2.action_import()
except UserError as e:
    err = str(e)
n_after = Question.search_count(
    [("module_id", "=", target.id)])
ok = (err is not None
      and "Import" in err
      and n_after == n_before)
print(f"  questions before: {n_before}, after: {n_after}")
print(f"  expected UserError raised: {bool(err)}")
print("T_LP101:", "PASS" if ok else "FAIL")
results["T_LP101"] = ok


# ============================================================
print()
print("T_LP102 - import mode with 3-row CSV creates 3 "
      "questions")
print("=" * 72)
n_before = Question.search_count(
    [("module_id", "=", target.id)])
w3 = _make_wizard(csv_data=csv_3rows, mode="import")
w3.action_parse_preview()
w3.action_import()
n_after = Question.search_count(
    [("module_id", "=", target.id)])
delta = n_after - n_before
ok = delta == 3
print(f"  questions delta: {delta} (expected 3)")
print(f"  summary: {w3.wizard_state}")
print("T_LP102:", "PASS" if ok else "FAIL")
results["T_LP102"] = ok


# ============================================================
print()
print("T_LP103 - malformed row (missing question_text) "
      "-> skipped")
print("=" * 72)
csv_bad = "\n".join([
    _CSV_HEADER,
    _row(question_text="Valid Q",
         type="sa", correct_answer="x"),
    _row(question_text="",
         type="sa", correct_answer="y"),
])
n_before = Question.search_count(
    [("module_id", "=", target.id)])
w4 = _make_wizard(csv_data=csv_bad, mode="import")
w4.action_parse_preview()
preview = w4.preview_html or ""
w4.action_import()
n_after = Question.search_count(
    [("module_id", "=", target.id)])
delta = n_after - n_before
ok = (delta == 1
      and "skipped" in preview
      and "missing question_text" in preview)
print(f"  questions delta: {delta} (expected 1)")
print(f"  'skipped' in preview: {'skipped' in preview}")
print("T_LP103:", "PASS" if ok else "FAIL")
results["T_LP103"] = ok


# ============================================================
print()
print("T_LP104 - multiple_choice with no is_correct -> "
      "error row, not created")
print("=" * 72)
csv_no_correct = "\n".join([
    _CSV_HEADER,
    _row(question_text="Bad MC -- no correct",
         type="mc",
         option_1_text="A", option_1_correct="False",
         option_2_text="B", option_2_correct="False"),
])
n_before = Question.search_count(
    [("module_id", "=", target.id)])
w5 = _make_wizard(csv_data=csv_no_correct, mode="import")
w5.action_parse_preview()
w5.action_import()
n_after = Question.search_count(
    [("module_id", "=", target.id)])
delta = n_after - n_before
ok = delta == 0 and "no correct" in (w5.preview_html or "")
print(f"  questions delta: {delta} (expected 0)")
print(f"  'no correct' in preview: "
      f"{'no correct' in (w5.preview_html or '')}")
print("T_LP104:", "PASS" if ok else "FAIL")
results["T_LP104"] = ok


# ============================================================
print()
print("T_LP105 - true_false row -> 2 options (True/False)")
print("=" * 72)
csv_tf = "\n".join([
    _CSV_HEADER,
    _row(question_text="TF probe",
         type="tf",
         option_1_correct="True"),
])
n_before = Question.search_count(
    [("module_id", "=", target.id)])
w6 = _make_wizard(csv_data=csv_tf, mode="import")
w6.action_parse_preview()
w6.action_import()
new_q = Question.search(
    [("module_id", "=", target.id),
     ("question_text", "=", "TF probe")], limit=1)
ok = (bool(new_q)
      and len(new_q.option_ids) == 2
      and set(new_q.option_ids.mapped("option_text"))
      == {"True", "False"}
      and new_q.option_ids.filtered(
          lambda o: o.option_text == "True").is_correct
      and not new_q.option_ids.filtered(
          lambda o: o.option_text == "False").is_correct)
print(f"  question created: {bool(new_q)}")
if new_q:
    print(f"  options: "
          f"{[(o.option_text, o.is_correct) for o in new_q.option_ids]}")
print("T_LP105:", "PASS" if ok else "FAIL")
results["T_LP105"] = ok


# ============================================================
print()
print("T_LP106 - short_answer row -> no options, "
      "correct_answer set")
print("=" * 72)
csv_sa = "\n".join([
    _CSV_HEADER,
    _row(question_text="SA probe",
         type="sa", correct_answer="forty-two"),
])
w7 = _make_wizard(csv_data=csv_sa, mode="import")
w7.action_parse_preview()
w7.action_import()
sa_q = Question.search(
    [("module_id", "=", target.id),
     ("question_text", "=", "SA probe")], limit=1)
ok = (bool(sa_q)
      and len(sa_q.option_ids) == 0
      and sa_q.correct_answer == "forty-two")
print(f"  question created: {bool(sa_q)}")
if sa_q:
    print(f"  option count: {len(sa_q.option_ids)} (expect 0)")
    print(f"  correct_answer: {sa_q.correct_answer!r}")
print("T_LP106:", "PASS" if ok else "FAIL")
results["T_LP106"] = ok


# ============================================================
print()
print("T_LP107 - file upload alternative populates csv_data "
      "identically")
print("=" * 72)
import base64 as _b64
payload = csv_3rows.encode("utf-8")
encoded = _b64.b64encode(payload)
w8 = Wizard.new({
    "module_id": target.id,
    "csv_file": encoded,
    "csv_file_name": "probe.csv",
})
w8._onchange_csv_file()
ok = (w8.csv_data or "").strip() == csv_3rows.strip()
print(f"  csv_data after upload onchange "
      f"matches paste: {ok}")
print("T_LP107:", "PASS" if ok else "FAIL")
results["T_LP107"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T_LP100", "T_LP101", "T_LP102", "T_LP103",
         "T_LP104", "T_LP105", "T_LP106", "T_LP107"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
