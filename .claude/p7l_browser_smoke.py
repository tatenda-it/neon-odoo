"""P7l browser smoke -- dead YouTube embeds become working search prompts.

Prereq: p7l_browser_setup.py (seeds the two converted P7L lessons +
ensures p2m75_sales enrolment).

Acceptance, verified in the actual learner player:
1. CASE A lesson: the "Find a tutorial on YouTube" search prompt renders
   with a clickable youtube.com/results link -- and there is NO dead
   <iframe> player and NO "Video unavailable", while the real lesson
   body text still shows.
2. CASE B (Capture) lesson: same, PLUS the authored intro survived and
   the stale "watch the three embedded tutorials" sentence was rephrased
   to point at the search link.
"""
from __future__ import annotations

import sys

from browser_smoke import AssertionFail, BrowserSmoke

MARKER_A = "P7L render proof A"
MARKER_B = "P7L render proof B"
STALE = "three embedded YouTube tutorials"
FIXED = "Use the YouTube search link above"


def _lesson(smoke, name):
    body = smoke.json_rpc(
        "slide.slide", "search_read",
        args=[[["name", "=", name]], ["id", "slide_category"]])
    rows = body.get("result") or []
    if not rows:
        raise AssertionFail("%r not found -- run p7l_browser_setup.py" % name)
    return rows[0]


def _open(smoke, lesson_id):
    smoke.page.goto(smoke.base_url + "/slides/slide/%s" % lesson_id,
                    wait_until="networkidle")
    smoke.page.wait_for_timeout(2000)


def main() -> int:
    with BrowserSmoke("p7l") as smoke:

        # ----------------------------------------------------------
        # Scenario 1: CASE A -- search prompt renders, no dead embed.
        # ----------------------------------------------------------
        with smoke.scenario("CASE A converted lesson shows search prompt (no dead player)"):
            smoke.login("p2m75_sales")
            lesson = _lesson(smoke, "P7L BROWSER lesson")
            _open(smoke, lesson["id"])
            body = smoke.page.inner_text("body")

            smoke._record_assert(
                "search-prompt heading renders",
                expect="present",
                actual="present" if "Find a tutorial on YouTube" in body else "absent",
                passed="Find a tutorial on YouTube" in body)
            smoke.assert_visible(
                "a[href*='youtube.com/results']", "clickable Search-YouTube link present")
            href = smoke.page.get_attribute("a[href*='youtube.com/results']", "href") or ""
            smoke._record_assert(
                "link targets a real YouTube search",
                expect="youtube.com/results?search_query=...",
                actual=href[:80],
                passed="youtube.com/results?search_query=" in href)

            dead = smoke.page.locator("iframe[src*='youtube']").count()
            smoke._record_assert(
                "no dead YouTube <iframe> player",
                expect="0", actual=str(dead), passed=dead == 0)
            smoke._record_assert(
                "no 'Video unavailable'",
                expect="0", actual=str(body.count("Video unavailable")),
                passed=body.count("Video unavailable") == 0)
            smoke._record_assert(
                "real lesson body survived",
                expect="marker present",
                actual="present" if MARKER_A in body else "absent",
                passed=MARKER_A in body)
            if "Find a tutorial on YouTube" not in body or dead != 0:
                raise AssertionFail("case A did not convert in the player: %r" % body[:200])
            smoke.screenshot("p7l_caseA_search_prompt")

        # ----------------------------------------------------------
        # Scenario 2: CASE B (Capture) -- prompt + intro + sentence fix.
        # ----------------------------------------------------------
        with smoke.scenario("CASE B Capture lesson: prompt + intro preserved + sentence rephrased"):
            smoke.login("p2m75_sales")
            lesson = _lesson(smoke, "P7L BROWSER Capture lesson")
            _open(smoke, lesson["id"])
            body = smoke.page.inner_text("body")

            smoke._record_assert(
                "search-prompt heading renders",
                expect="present",
                actual="present" if "Find a tutorial on YouTube" in body else "absent",
                passed="Find a tutorial on YouTube" in body)
            dead = smoke.page.locator("iframe[src*='youtube']").count()
            smoke._record_assert(
                "no dead YouTube <iframe> player",
                expect="0", actual=str(dead), passed=dead == 0)
            smoke._record_assert(
                "authored Capture intro survived",
                expect="present",
                actual="present" if MARKER_B in body else "absent",
                passed=MARKER_B in body)
            smoke._record_assert(
                "stale 'embedded tutorials' sentence rephrased",
                expect="stale gone + fixed present",
                actual="stale=%s fixed=%s" % (STALE in body, FIXED in body),
                passed=(STALE not in body) and (FIXED in body))
            if dead != 0 or "Find a tutorial on YouTube" not in body:
                raise AssertionFail("case B did not convert in the player: %r" % body[:200])
            smoke.screenshot("p7l_caseB_capture")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())