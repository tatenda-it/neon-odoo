"""P7i browser smoke -- learner-facing review quiz (3 scenarios).

The attempt model + grading + completion/cert chain is covered
in-process by p7i_smoke.py. This exercises the real HTTP learner
flow through the website controller, and is REAL-DATA-SAFE: it
targets a Foundations-gate module with no practical scenario and
answers whatever questions that module actually has (2 fixture
questions on an empty dev DB, or the real 606-bank module on
prod) by fetching the correct options via RPC.

1. Branded review-quiz index renders for an enrolled learner.
2. A FAILING attempt (no answers) shows "Not yet" and does NOT
   advance the module (DOM + RPC).
3. A PASSING attempt (all correct) shows "Passed", the module
   completes, and the page is Neon-branded.

Fixture prerequisite: run p7i_browser_setup.py once. Base URL /
DB come from NEON_BASE_URL / NEON_DB (default localhost:8069 /
neon_crm), so the same smoke runs against the isolated stack.
"""
from __future__ import annotations

import os
import sys

from browser_smoke import (
    AssertionFail, BrowserSmoke, DEFAULT_BASE_URL, DEFAULT_DB,
)

LEARNER = "p7i_blearner"


def _rows(s, model, domain, fields, **kw):
    return s.json_rpc(model, "search_read",
                      args=[domain, fields], kwargs=kw).get("result") or []


def _target_module(s):
    """Foundations-gate module with NO active practical scenario, lowest
    sequence -- mirrors p7i_browser_setup. Quiz pass alone completes it."""
    mods = _rows(s, "neon.lms.module",
                 [["track_id.is_foundation_gate", "=", True]],
                 ["code", "sequence_in_track"],
                 order="sequence_in_track asc, id asc")
    if not mods:
        raise AssertionFail("no Foundations module found")
    ids = [m["id"] for m in mods]
    scen = _rows(s, "neon.lms.practical.scenario",
                 [["module_id", "in", ids], ["active", "=", True]],
                 ["module_id"])
    gated = {r["module_id"][0] for r in scen if r.get("module_id")}
    for m in mods:
        if m["id"] not in gated:
            return m["id"]
    return mods[0]["id"]


def _module_state(s, mid):
    rows = _rows(s, "neon.lms.module.completion",
                 [["module_id", "=", mid]], ["state", "quiz_score"], limit=1)
    return rows[0] if rows else {}


def main() -> int:
    base = os.environ.get("NEON_BASE_URL", DEFAULT_BASE_URL)
    db = os.environ.get("NEON_DB", DEFAULT_DB)
    with BrowserSmoke("p7i", base_url=base, db=db) as smoke:
        smoke.login(LEARNER)
        mid = _target_module(smoke)
        qrows = _rows(smoke, "neon.lms.quiz.question",
                      [["module_id", "=", mid], ["active", "=", True]],
                      ["id"])
        qcount = len(qrows)
        quiz_url = f"{base}/slides/neon/quiz/{mid}"

        # ---- 1. branded index -----------------------------------------
        with smoke.scenario("enrolled learner: branded review-quiz index"):
            smoke.page.goto(f"{base}/slides/neon/quizzes",
                            wait_until="networkidle")
            smoke.assert_visible(".o_neon_lms_quizwrap", "branded quiz index")
            smoke.assert_visible(".o_neon_quiz_track", "at least one track block")
            smoke.assert_visible("a.o_neon_quizcta_btn", "a 'Take quiz' CTA")
            smoke.screenshot("quiz_index")

        # ---- 2. failing attempt (no answers) does NOT advance ---------
        with smoke.scenario("failing attempt: 'Not yet', no advance"):
            smoke.page.goto(quiz_url, wait_until="networkidle")
            smoke.assert_visible(".o_neon_quiz_form", "quiz form renders")
            smoke.assert_count(".o_neon_quiz_q", qcount,
                               "all %d questions rendered" % qcount)
            # submit with nothing selected -> 0 correct -> fail
            smoke.click(".o_neon_quiz_submit button", name="submit empty attempt")
            smoke.assert_visible(".o_neon_quiz_resultcard.failed",
                                 "result card shows failed state")
            smoke.assert_count(".o_neon_quiz_completebanner", 0,
                               "no module-complete banner on a fail")
            st = _module_state(smoke, mid)
            smoke._record_assert(
                "module not completed after fail (RPC)",
                expect="state != completed",
                actual="state=%s" % st.get("state"),
                passed=st.get("state") != "completed")
            if st.get("state") == "completed":
                raise AssertionFail("module wrongly completed by a failing attempt")
            smoke.screenshot("quiz_fail")

        # ---- 3. passing attempt completes the module ------------------
        with smoke.scenario("passing attempt: 'Passed' + module complete"):
            smoke.page.goto(quiz_url, wait_until="networkidle")
            smoke.assert_visible(".o_neon_quiz_form", "quiz form renders")
            qids = [q["id"] for q in qrows]
            corr = _rows(smoke, "neon.lms.quiz.option",
                         [["question_id", "in", qids], ["is_correct", "=", True]],
                         ["id"])
            if not corr:
                raise AssertionFail("no correct options resolved for target module")
            for o in corr:
                smoke.page.locator("input[value='%d']" % o["id"]).first.check()
            smoke.click(".o_neon_quiz_submit button", name="submit passing attempt")
            smoke.assert_visible(".o_neon_quiz_resultcard.passed",
                                 "result card shows passed state")
            smoke.assert_visible(".o_neon_quiz_bigscore", "branded score display")
            smoke.assert_visible(".o_neon_quiz_completebanner",
                                 "module-complete banner shown")
            st = _module_state(smoke, mid)
            smoke._record_assert(
                "module completed after pass (RPC)",
                expect="state == completed",
                actual="state=%s score=%s" % (st.get("state"), st.get("quiz_score")),
                passed=st.get("state") == "completed")
            if st.get("state") != "completed":
                raise AssertionFail("passing attempt did not complete the module")
            smoke.screenshot("quiz_pass")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
