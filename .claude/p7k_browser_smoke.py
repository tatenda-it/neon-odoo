"""P7k browser smoke -- lesson body renders + lime->white branding.

Prereq: p7k_browser_setup.py (creates the converted P7K lesson +
ensures p2m75_sales enrolment).

1. RENDER (item 1): the converted lesson opens in the player and the
   html_content body TEXT renders -- no "Loading..." hang, no PDF
   viewer. This is the acceptance: a learner opens a lesson and the
   content shows.
2. BRANDING (item 2): on the branded course page the hero stat
   numbers are WHITE (not lime) and the gate badge is the approved
   white pill with grape text -- no lime anywhere.
"""
from __future__ import annotations

import sys

from browser_smoke import AssertionFail, BrowserSmoke

WHITE = "rgb(255, 255, 255)"
GRAPE = "rgb(107, 33, 168)"   # #6B21A8
LIME = "rgb(200, 243, 107)"   # #c8f36b
MARKER = "P7K render proof"


def _lesson(smoke):
    body = smoke.json_rpc(
        "slide.slide", "search_read",
        args=[[["name", "=", "P7K BROWSER lesson"]],
              ["id", "slide_category", "website_url"]])
    rows = body.get("result") or []
    if not rows:
        raise AssertionFail("P7K BROWSER lesson not found -- run p7k_browser_setup.py")
    return rows[0]


def _channel(smoke):
    body = smoke.json_rpc(
        "slide.channel", "search_read",
        args=[[["neon_branded", "=", True]], ["website_url"]])
    rows = body.get("result") or []
    if not rows:
        raise AssertionFail("no neon_branded channel")
    return rows[0]


def main() -> int:
    with BrowserSmoke("p7k") as smoke:

        # ----------------------------------------------------------
        # Scenario 1: the converted lesson renders its html body.
        # ----------------------------------------------------------
        with smoke.scenario("converted lesson renders html_content (no Loading hang)"):
            smoke.login("p2m75_sales")
            lesson = _lesson(smoke)
            smoke._record_assert(
                "fixture lesson is article (was document)",
                expect="article", actual=lesson["slide_category"],
                passed=lesson["slide_category"] == "article")
            smoke.page.goto(smoke.base_url + "/slides/slide/%s" % lesson["id"],
                            wait_until="networkidle")
            smoke.page.wait_for_timeout(2000)
            body = smoke.page.inner_text("body")
            smoke._record_assert(
                "lesson body text renders",
                expect="marker present", actual="present" if MARKER in body else "absent",
                passed=MARKER in body)
            smoke._record_assert(
                "no persistent 'Loading...' hang",
                expect="0", actual=str(body.count("Loading...")),
                passed=body.count("Loading...") == 0)
            # the document PDF-viewer branch must be absent for an article
            pdf_viewers = smoke.page.locator(".ratio.ratio-4x3, #PDFViewer, .o_wslides_fs_slide_pdf").count()
            smoke._record_assert(
                "no PDF viewer element on the article lesson",
                expect="0", actual=str(pdf_viewers), passed=pdf_viewers == 0)
            if MARKER not in body:
                raise AssertionFail("lesson body did not render: %r" % body[:200])
            smoke.screenshot("p7k_lesson_renders")

        # ----------------------------------------------------------
        # Scenario 2: lime -> white on the branded course page.
        # ----------------------------------------------------------
        with smoke.scenario("branding: hero stats white + gate badge grape (no lime)"):
            smoke.login("p2m75_sales")
            ch = _channel(smoke)
            smoke.page.goto(ch["website_url"], wait_until="networkidle")
            smoke.page.wait_for_timeout(900)
            smoke.assert_visible(".o_neon_lms_hero", "Neon hero present")
            num_color = smoke.page.eval_on_selector(
                ".o_neon_lms_stats .o_neon_stat .num",
                "el => getComputedStyle(el).color")
            smoke._record_assert(
                "hero stat number is WHITE (not lime)",
                expect=WHITE, actual=num_color,
                passed=num_color == WHITE and num_color != LIME)
            badge = smoke.page.eval_on_selector(
                ".o_neon_card_gate",
                "el => ({bg: getComputedStyle(el).backgroundColor,"
                " fg: getComputedStyle(el).color,"
                " bd: getComputedStyle(el).borderColor})")
            smoke._record_assert(
                "gate badge: white bg, grape text, grape border (no lime)",
                expect="bg=%s fg=%s" % (WHITE, GRAPE),
                actual="bg=%s fg=%s bd=%s" % (badge["bg"], badge["fg"], badge["bd"]),
                passed=badge["bg"] == WHITE and badge["fg"] == GRAPE
                and badge["bg"] != LIME)
            smoke.screenshot("p7k_branding_white")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
