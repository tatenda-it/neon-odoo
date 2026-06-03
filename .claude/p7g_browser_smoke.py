"""P7g browser smoke -- branded Neon course page (2 scenarios).

The branding data/logic (track cards, stats, config) is covered in-process
by p7g_smoke.py. This exercises the rendered website page:

1. An enrolled member loads the course landing and sees the Neon branding
   -- white-wordmark logo on the grape header, the grape hero, the 4-stat
   strip, all 7 track cards, the capstone band -- and the stock eLearning
   cover (coffee-mug + default header) is gone.
2. Learner-scoped published view: the enrolled member reaches the course
   (no access-denied), and the channel is published + members-visibility
   (enrolled-only, not public-internet).
"""
from __future__ import annotations

import sys

from browser_smoke import AssertionFail, BrowserSmoke


def _channel(smoke):
    body = smoke.json_rpc(
        "slide.channel", "search_read",
        args=[[["neon_branded", "=", True]],
              ["website_url", "is_published", "visibility"]])
    rows = body.get("result") or []
    if not rows:
        raise AssertionFail("no neon_branded channel found via RPC")
    return rows[0]


def main() -> int:
    with BrowserSmoke("p7g") as smoke:

        # --------------------------------------------------------------
        # Scenario 1: enrolled member sees the Neon-branded landing.
        # --------------------------------------------------------------
        with smoke.scenario("enrolled member: branded Neon course page"):
            smoke.login("p2m75_sales")
            ch = _channel(smoke)
            smoke.page.goto(ch["website_url"],
                            wait_until="networkidle")
            smoke.page.wait_for_timeout(800)
            smoke.assert_visible(".o_neon_lms_hero", "Neon grape hero")
            smoke.assert_visible(".o_neon_logo", "white-wordmark logo")
            smoke.assert_count(".o_neon_card", 7, "7 track cards")
            smoke.assert_visible(".o_neon_card_gate",
                                 "Foundations 'Start Here' gate badge")
            smoke.assert_count(".o_neon_lms_stats .o_neon_stat", 4,
                               "4-stat strip")
            smoke.assert_visible(".o_neon_lms_capstone", "capstone band")
            # stock eLearning cover (coffee-mug + default header) is gone
            smoke.assert_count(".o_wslides_course_header", 0,
                               "stock course header hidden")
            smoke.screenshot("neon_branded_course")

        # --------------------------------------------------------------
        # Scenario 2: learner-scoped published view + members visibility.
        # --------------------------------------------------------------
        with smoke.scenario("learner-scoped published view (members-only)"):
            smoke.login("p2m75_sales")
            ch = _channel(smoke)
            smoke.page.goto(ch["website_url"],
                            wait_until="networkidle")
            smoke.page.wait_for_timeout(600)
            # real access: the enrolled member renders the branded published
            # course (not a 403 / permission wall). assert_visible on the
            # hero proves access + that the published content reaches them.
            smoke.assert_visible(".o_neon_lms_hero",
                                 "member sees the published branded course")
            h1 = smoke.page.locator("h1").first.inner_text()
            smoke._record_assert(
                "course landing (not a 403 page)",
                expect="Neon Workshop Training Programme",
                actual=h1, passed="Neon Workshop" in h1)
            if "Neon Workshop" not in h1:
                raise AssertionFail("member did not reach the branded course (%r)" % h1)
            smoke._record_assert(
                "channel published + members-visibility (enrolled-only)",
                expect="published=True visibility=members",
                actual="published=%s visibility=%s" % (
                    ch["is_published"], ch["visibility"]),
                passed=bool(ch["is_published"]) and ch["visibility"] == "members")
            if not (ch["is_published"] and ch["visibility"] == "members"):
                raise AssertionFail("channel not published/members as expected")
            smoke.goto_home()

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
