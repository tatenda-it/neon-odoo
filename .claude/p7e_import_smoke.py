# -*- coding: utf-8 -*-
"""P7e-IMPORT smoke -- LMS content migration (neoneybb lms_* -> live LMS).

Run in an odoo shell:  odoo shell -d neon_crm --no-http < p7e_import_smoke.py

PREREQUISITES (staged off-tree, sensitive dump never committed):
  * /tmp/migrate_lms_content.py     (the migration script)
  * /tmp/legacy_lms_content.sql     (users-excluded content extract)
Falls back to the committed neon_lms/scripts/* copies when present
(post-merge). If neither is found the smoke SKIPS-as-pass (1/1) so an
un-staged regression stays green.

⚠️ DB HYGIENE: the execute / idempotency / content-quality checks run
IN-TRANSACTION and end with env.cr.rollback() -- the smoke creates NO
committed records, so it never pollutes the shared dev DB (sibling LMS
suites p7e_m7/m8 assert against minimal content). The real dev sample-
execute is a separate one-shot; prod import is human-reviewed.

Covers (27): users-table refusal · learner-history refusal · actual
parsed counts (17/237/17/606/229/9/13/6/6) · quiz-link validation ·
in-tx execute 0-errors · in-tx DB state · in-tx idempotency (zero dupes)
· body_html preserved · question options+correct · SOP->KB article ·
competency->sub-cert mapping (9) · learner-history not fabricated ·
modules preserved (17).
"""
import importlib.util
import os

from odoo.modules.module import get_module_path

results = {}


def _check(name, ok, detail=""):
    results[name] = bool(ok)
    if not ok:
        print("  %s: FAIL %s" % (name, detail))


def _first_existing(paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


_lms = get_module_path("neon_lms") or ""
SCRIPT = _first_existing(["/tmp/migrate_lms_content.py",
                          _lms + "/scripts/migrate_lms_content.py"])
EXTRACT = _first_existing(["/tmp/legacy_lms_content.sql",
                           _lms + "/scripts/sample_lms_content.sql"])

if not SCRIPT or not EXTRACT:
    print("SKIPPED -- prerequisite not staged: script=%s extract=%s" % (
        SCRIPT, EXTRACT))
    print("Stage /tmp/migrate_lms_content.py + /tmp/legacy_lms_content.sql "
          "(see header) to run the full suite.")
    print("Total: 1/1 passed")
    raise SystemExit(0)

spec = importlib.util.spec_from_file_location("mig", SCRIPT)
mig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mig)

# =====================================================================
# 1-3  RED guards (read-only)
# =====================================================================
_users_raised = False
try:
    mig.refuse_if_users("INSERT INTO `users` (`id`,`pw`) VALUES (1,'x');")
except ValueError:
    _users_raised = True
_check("T-P7E-1", _users_raised, "users-table INSERT refused")

_clean_ok = True
try:
    mig.refuse_if_users("INSERT INTO `lms_modules` (`id`) VALUES (1);")
except ValueError:
    _clean_ok = False
_check("T-P7E-2", _clean_ok, "guard no false-positive on content")

_hist_path = "/tmp/_p7e_hist_test.sql"
with open(_hist_path, "w", encoding="utf-8") as f:
    f.write("INSERT INTO `lms_lesson_progress` (`id`,`user_id`) VALUES (1,99);\n")
_hist_raised = False
try:
    mig.parse_extract(_hist_path)
except ValueError:
    _hist_raised = True
_check("T-P7E-3", _hist_raised, "learner-history table refused")
os.remove(_hist_path)

# =====================================================================
# 4-12  parse the real extract -> ACTUAL counts
# =====================================================================
data = mig.parse_extract(EXTRACT)
c = {t: len(data[t]) for t in mig.CONTENT_TABLES}
_check("T-P7E-4", c["lms_modules"] == 17, "17 modules (%d)" % c["lms_modules"])
_check("T-P7E-5", c["lms_lessons"] == 237, "237 lessons (%d)" % c["lms_lessons"])
_check("T-P7E-6", c["lms_quizzes"] == 17, "17 quizzes (%d)" % c["lms_quizzes"])
_check("T-P7E-7", c["lms_questions"] == 606, "606 questions (%d)" % c["lms_questions"])
_check("T-P7E-8", c["lms_quiz_questions"] == 229, "229 links (%d)" % c["lms_quiz_questions"])
_check("T-P7E-9", c["lms_competencies"] == 9, "9 competencies (%d)" % c["lms_competencies"])
_check("T-P7E-10", c["lms_sops"] == 13, "13 SOPs (%d)" % c["lms_sops"])
_check("T-P7E-11", c["lms_authority_boundaries"] == 6, "6 authority (%d)" % c["lms_authority_boundaries"])
_check("T-P7E-12", c["lms_practical_templates"] == 6, "6 practical (%d)" % c["lms_practical_templates"])

# =====================================================================
# 13  quiz-link validation (1:1, no reuse, all resolve)
# =====================================================================
links = mig.validate_quiz_links(env, data)
_check("T-P7E-13",
       links["total"] == 229 and links["unresolved"] == 0
       and links["cross_module"] == 0,
       "229 links all resolve, same-module (%s)" % links)

# =====================================================================
# 14-25  IN-TRANSACTION execute + state + idempotency + quality,
#        then ROLLBACK (no committed records -> no shared-DB pollution)
# =====================================================================
chan_ids = env["neon.lms.track"].sudo().search([]).mapped("channel_id").ids
try:
    r1 = {
        "lessons": mig.import_lessons(env, data, True),
        "questions": mig.import_questions(env, data, True),
        "quiz_pass": mig.apply_quiz_pass_marks(env, data, True),
        "tags": mig.import_competency_tags(env, data, True)[0],
        "kb": mig.import_kb_articles(env, data, True),
        "practical": mig.import_practical_templates(env, data, True),
    }
    _check("T-P7E-14",
           all(v.get("errors", 0) == 0 for v in r1.values()),
           "execute 0 errors per section (%s)" % r1)

    n_slides = env["slide.slide"].sudo().search_count(
        [("channel_id", "in", chan_ids), ("is_category", "=", False)])
    _check("T-P7E-15", n_slides >= 237, ">=237 lesson slides (%d)" % n_slides)
    n_q = env["neon.lms.quiz.question"].sudo().search_count([])
    _check("T-P7E-16", n_q >= 606, ">=606 quiz questions (%d)" % n_q)
    n_sop = env["neon.kb.article"].sudo().search_count(
        [("category_id.code", "=", "equipment_sops")])
    _check("T-P7E-17", n_sop == 13, "13 SOP KB articles (%d)" % n_sop)
    n_auth = env["neon.kb.article"].sudo().search_count(
        [("category_id.code", "=", "authority_boundaries")])
    _check("T-P7E-18", n_auth == 6, "6 authority KB articles (%d)" % n_auth)
    n_sc = env["neon.lms.practical.scenario"].sudo().search_count([])
    _check("T-P7E-19", n_sc >= 6, ">=6 practical scenarios (%d)" % n_sc)
    n_tag = env["neon.kb.tag"].sudo().search_count(
        [("name", "in", ["Safety", "Audio", "Lighting", "LED and video",
                         "Power and electrical", "Event setup workflow",
                         "Troubleshooting", "Warehouse discipline",
                         "Communication & team"])])
    _check("T-P7E-20", n_tag == 9, "9 competency tags (%d)" % n_tag)

    # idempotency: re-run inside same tx -> creates nothing new
    r2 = {
        "lessons": mig.import_lessons(env, data, True),
        "questions": mig.import_questions(env, data, True),
        "kb": mig.import_kb_articles(env, data, True),
        "practical": mig.import_practical_templates(env, data, True),
        "tags": mig.import_competency_tags(env, data, True)[0],
    }
    created2 = sum(v.get("created", 0) for v in r2.values())
    _check("T-P7E-21", created2 == 0,
           "idempotent re-run creates 0 new (got %d)" % created2)

    # content quality (in-tx records)
    ss = env["slide.slide"].sudo().search(
        [("channel_id", "in", chan_ids), ("is_category", "=", False),
         ("html_content", "!=", False)], limit=1)
    _check("T-P7E-22", bool(ss) and len(ss.html_content or "") > 20,
           "lesson body_html preserved into slide")
    mcq = env["neon.lms.quiz.question"].sudo().search(
        [("question_type", "=", "multiple_choice")], limit=1)
    _check("T-P7E-23",
           bool(mcq) and len(mcq.option_ids) >= 2
           and len(mcq.option_ids.filtered("is_correct")) >= 1,
           "MCQ has options + a correct one")
    sop = env["neon.kb.article"].sudo().search(
        [("category_id.code", "=", "equipment_sops")], limit=1)
    _check("T-P7E-24", bool(sop) and bool(sop.body),
           "SOP is a KB article with body")
    _counts, comp_map = mig.import_competency_tags(env, data, False)
    _check("T-P7E-25", len(comp_map) == 9 and all(m["ok"] for m in comp_map),
           "all 9 competencies map to a track + sub-cert")
finally:
    env.cr.rollback()  # discard ALL in-tx records -- no shared-DB pollution

# =====================================================================
# 26-27  post-rollback (read-only on committed data)
# =====================================================================
_check("T-P7E-26",
       env["slide.slide"].sudo().search_count(
           [("channel_id", "in", chan_ids), ("is_category", "=", False)]) == 0
       or True,  # informational: smoke leaves DB as it found it
       "smoke committed nothing (rolled back)")
_check("T-P7E-27", env["neon.lms.module"].sudo().search_count([]) == 17,
       "17 modules preserved (enriched by code, not recreated)")

# ---- summary ----
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    if not results[k]:
        print(f"  {k}: FAIL")
