"""P7i PROD-CLONE verification (real 606-question bank) -- NOT committed.

Proves, against a clone of prod neon_crm (real questions from P7e), that:
  1. the branded index renders each module's REAL question count (not 0),
  2. a non-M01 module (M08, 35 real questions) renders its real questions,
  3. a learner can PASS it on the real questions -> module completes.

Correct options are fetched via RPC (crew can read option.is_correct) and
checked by input value -- a true HTTP pass through the controller.
Base URL / DB from NEON_BASE_URL / NEON_DB.
"""
from __future__ import annotations

import os
import sys

from browser_smoke import (
    AssertionFail, BrowserSmoke, DEFAULT_BASE_URL, DEFAULT_DB,
)

LEARNER = "p7i_blearner"
TARGET_CODE = "M08"   # non-M01, Foundations gate track, 0 scenarios


def _rpc_rows(s, model, domain, fields, **kw):
    body = s.json_rpc(model, "search_read", args=[domain, fields], kwargs=kw)
    return body.get("result") or []


def main() -> int:
    base = os.environ.get("NEON_BASE_URL", DEFAULT_BASE_URL)
    db = os.environ.get("NEON_DB", DEFAULT_DB)
    with BrowserSmoke("p7i_prod", base_url=base, db=db) as s:
        s.login(LEARNER)

        # ---- 1. index shows REAL per-module counts -------------------
        with s.scenario("index: real per-module question counts"):
            s.page.goto(f"{base}/slides/neon/quizzes", wait_until="networkidle")
            s.assert_visible(".o_neon_lms_quizwrap", "branded index")
            s.screenshot("prod_index_real_counts")
            txt = " ".join(
                s.page.locator(".o_neon_lms_quizwrap").inner_text().split())
            # On the real bank every module has questions: the wiring-gap
            # marker "No quiz yet" (rendered only when count<=0) must be
            # ABSENT, and real counts (e.g. 35 / 90) must be present.
            no_gap = "No quiz yet" not in txt
            has_real = any(("%d questions" % n) in txt for n in (35, 90, 40, 31, 30, 10))
            s._record_assert(
                "no 'No quiz yet' on the real bank (no wiring gap)",
                expect="0 occurrences", actual=str(txt.count("No quiz yet")),
                passed=no_gap)
            s._record_assert(
                "modules show REAL counts (e.g. 35 / 90 questions)",
                expect="real counts present",
                actual=("present" if has_real else "absent"),
                passed=has_real)
            if not (no_gap and has_real):
                raise AssertionFail("index did not surface real question counts")

        # ---- 2 + 3. real questions render + a real pass --------------
        mods = _rpc_rows(s, "neon.lms.module",
                         [["code", "=", TARGET_CODE]], ["id"])
        if not mods:
            raise AssertionFail("target module %s not found" % TARGET_CODE)
        mid = mods[0]["id"]
        qrows = _rpc_rows(s, "neon.lms.quiz.question",
                          [["module_id", "=", mid], ["active", "=", True]],
                          ["id", "question_type"])
        qcount = len(qrows)

        with s.scenario("M08: %d real questions render + a real pass" % qcount):
            s.page.goto(f"{base}/slides/neon/quiz/{mid}", wait_until="networkidle")
            s.assert_visible(".o_neon_quiz_form", "quiz form (real questions)")
            s.assert_count(".o_neon_quiz_q", qcount,
                           "all %d real questions rendered" % qcount)
            s.screenshot("prod_m08_real_questions")

            # Fetch correct options (crew can read is_correct) and check them.
            qids = [q["id"] for q in qrows]
            corr = _rpc_rows(s, "neon.lms.quiz.option",
                             [["question_id", "in", qids],
                              ["is_correct", "=", True]], ["id"])
            if not corr:
                raise AssertionFail("no correct options resolved for %s" % TARGET_CODE)
            for o in corr:
                s.page.locator("input[value='%d']" % o["id"]).first.check()
            s.click(".o_neon_quiz_submit button", name="submit real-question attempt")
            s.assert_visible(".o_neon_quiz_resultcard.passed",
                             "passed on real questions")
            s.assert_visible(".o_neon_quiz_completebanner",
                             "module-complete banner")
            st = _rpc_rows(s, "neon.lms.module.completion",
                           [["module_id", "=", mid]], ["state", "quiz_score"])
            row = st[0] if st else {}
            s._record_assert(
                "M08 completed on real questions (RPC)",
                expect="state == completed",
                actual="state=%s score=%s" % (row.get("state"), row.get("quiz_score")),
                passed=row.get("state") == "completed")
            if row.get("state") != "completed":
                raise AssertionFail("M08 did not complete on a real-question pass")
            s.screenshot("prod_m08_passed")

        return s.summary()


if __name__ == "__main__":
    sys.exit(main())
