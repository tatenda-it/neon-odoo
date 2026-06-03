"""P7i browser smoke -- learner-facing review quiz (3 scenarios).

The attempt model + grading + completion/cert chain is covered
in-process by p7i_smoke.py. This exercises the real HTTP learner
flow through the website controller:

1. Branded review-quiz index renders for an enrolled learner.
2. A FAILING attempt (wrong options) shows "Not yet" and does NOT
   advance the module (verified in the DOM and via RPC).
3. A PASSING attempt (correct options) shows "Passed", the module
   completes, and the page is Neon-branded.

Fixture prerequisite: run p7i_browser_setup.py once (creates the
enrolled p7i_blearner + two deterministic MC questions on the
Foundations first module + resets its completion). Base URL / DB
come from NEON_BASE_URL / NEON_DB (default localhost:8069 /
neon_crm), so the same smoke runs against the isolated stack.
"""
from __future__ import annotations

import os
import sys

from browser_smoke import (
    AssertionFail,
    BrowserSmoke,
    DEFAULT_BASE_URL,
    DEFAULT_DB,
)

LEARNER = "p7i_blearner"


def _foundation_module_id(smoke):
    body = smoke.json_rpc(
        "neon.lms.module", "search_read",
        args=[[["track_id.is_foundation_gate", "=", True]],
              ["code", "sequence_in_track"]],
        kwargs={"order": "sequence_in_track asc, id asc", "limit": 1})
    rows = body.get("result") or []
    if not rows:
        raise AssertionFail("no Foundations module found via RPC")
    return rows[0]["id"]


def _module_state(smoke, module_id):
    body = smoke.json_rpc(
        "neon.lms.module.completion", "search_read",
        args=[[["module_id", "=", module_id]], ["state", "quiz_score"]],
        kwargs={"limit": 1})
    rows = body.get("result") or []
    return rows[0] if rows else {}


def _check_options(smoke, label_text):
    """Check every option input whose label contains label_text."""
    labels = smoke.page.locator("label.o_neon_quiz_opt").filter(
        has_text=label_text)
    n = labels.count()
    if n == 0:
        raise AssertionFail("no options matching %r on the quiz form" % label_text)
    for i in range(n):
        labels.nth(i).locator("input").check()
    return n


def main() -> int:
    base_url = os.environ.get("NEON_BASE_URL", DEFAULT_BASE_URL)
    db = os.environ.get("NEON_DB", DEFAULT_DB)
    with BrowserSmoke("p7i", base_url=base_url, db=db) as smoke:

        smoke.login(LEARNER)
        module_id = _foundation_module_id(smoke)
        quiz_url = f"{base_url}/slides/neon/quiz/{module_id}"

        # ----------------------------------------------------------------
        # Scenario 1: branded review-quiz index.
        # ----------------------------------------------------------------
        with smoke.scenario("enrolled learner: branded review-quiz index"):
            smoke.page.goto(f"{base_url}/slides/neon/quizzes",
                            wait_until="networkidle")
            smoke.assert_visible(".o_neon_lms_quizwrap",
                                 "branded quiz index wrapper")
            smoke.assert_visible(".o_neon_quiz_track",
                                 "at least one track block")
            smoke.assert_visible("a.o_neon_quizcta_btn",
                                 "a 'Take quiz' call-to-action")
            smoke.screenshot("quiz_index")

        # ----------------------------------------------------------------
        # Scenario 2: failing attempt does NOT advance the module.
        # ----------------------------------------------------------------
        with smoke.scenario("failing attempt: 'Not yet', no advance"):
            smoke.page.goto(quiz_url, wait_until="networkidle")
            smoke.assert_visible(".o_neon_quiz_form", "quiz form renders")
            smoke.assert_count(".o_neon_quiz_q", 2, "two questions rendered")
            _check_options(smoke, "WRONG A")
            smoke.click(".o_neon_quiz_submit button", name="submit failing attempt")
            smoke.assert_visible(".o_neon_quiz_resultcard.failed",
                                 "result card shows failed state")
            smoke.assert_count(".o_neon_quiz_completebanner", 0,
                               "no module-complete banner on a fail")
            st = _module_state(smoke, module_id)
            smoke._record_assert(
                "module not completed after fail (RPC)",
                expect="state != completed",
                actual="state=%s score=%s" % (st.get("state"), st.get("quiz_score")),
                passed=st.get("state") != "completed")
            if st.get("state") == "completed":
                raise AssertionFail("module wrongly completed by a failing attempt")
            smoke.screenshot("quiz_fail")

        # ----------------------------------------------------------------
        # Scenario 3: passing attempt completes the module (branded).
        # ----------------------------------------------------------------
        with smoke.scenario("passing attempt: 'Passed' + module complete"):
            smoke.page.goto(quiz_url, wait_until="networkidle")
            smoke.assert_visible(".o_neon_quiz_form", "quiz form renders")
            _check_options(smoke, "CORRECT")
            smoke.click(".o_neon_quiz_submit button", name="submit passing attempt")
            smoke.assert_visible(".o_neon_quiz_resultcard.passed",
                                 "result card shows passed state")
            smoke.assert_visible(".o_neon_quiz_bigscore",
                                 "branded score display")
            smoke.assert_visible(".o_neon_quiz_completebanner",
                                 "module-complete banner shown")
            st = _module_state(smoke, module_id)
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
