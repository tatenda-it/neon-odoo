"""P7h browser smoke -- dedicated Neon LMS footer on /slides* only (2 scenarios).

1. On a course page (/slides/<course>): the Neon LMS footer renders with
   the course-support email + the Operations-Director line, NO social
   icons, and the "(c) <year> Neon Events Elements" copyright; the global
   footer body is hidden.
2. On a non-LMS page (/contactus): the Neon footer is absent and the
   GLOBAL footer is unchanged (its social icons + "Company name" copyright
   still present) -- proving the swap is scoped to eLearning routes only.
"""
from __future__ import annotations

import re
import sys

from browser_smoke import AssertionFail, BrowserSmoke


def _course_url(smoke):
    body = smoke.json_rpc(
        "slide.channel", "search_read",
        args=[[["neon_track_ids", "!=", False]], ["website_url"]])
    rows = body.get("result") or []
    if not rows:
        raise AssertionFail("no Neon channel found via RPC")
    return rows[0]["website_url"]


def main() -> int:
    with BrowserSmoke("p7h") as smoke:

        # --------------------------------------------------------------
        # Scenario 1: course page -> Neon LMS footer.
        # --------------------------------------------------------------
        with smoke.scenario("course page: dedicated Neon LMS footer"):
            smoke.login("p2m75_sales")
            smoke.page.goto(_course_url(smoke), wait_until="networkidle")
            smoke.page.wait_for_timeout(600)
            smoke.assert_visible(".o_neon_lms_footer", "Neon LMS footer present")
            foot = smoke.page.locator(".o_neon_lms_footer").inner_text()
            smoke._record_assert(
                "footer shows course-support email",
                expect="admin@neonhiring.co.zw", actual=foot[:0] + (
                    "found" if "admin@neonhiring.co.zw" in foot else "missing"),
                passed="admin@neonhiring.co.zw" in foot)
            smoke._record_assert(
                "footer shows the OD course-support line",
                expect="+263 772 336 333",
                actual="found" if "+263 772 336 333" in foot else "missing",
                passed="+263 772 336 333" in foot)
            # NO social icons anywhere (global footer body hidden on /slides)
            smoke.assert_count(".s_social_media", 0,
                               "no social icons on the course page")
            cop = smoke.page.locator(".o_neon_lms_footer_copyright").inner_text()
            smoke._record_assert(
                "copyright = (c) <year> Neon Events Elements",
                expect="<year> Neon Events Elements",
                actual=cop.strip(),
                passed=("Neon Events Elements" in cop
                        and bool(re.search(r"\d{4}", cop))))
            if "Neon Events Elements" not in cop:
                raise AssertionFail("copyright wrong: %r" % cop)
            smoke.screenshot("neon_lms_footer")

        # --------------------------------------------------------------
        # Scenario 2: non-LMS page -> GLOBAL footer unchanged.
        # --------------------------------------------------------------
        with smoke.scenario("non-LMS page: global footer unchanged"):
            smoke.login("p2m75_sales")
            smoke.page.goto(smoke.base_url + "/contactus",
                            wait_until="networkidle")
            smoke.page.wait_for_timeout(400)
            smoke.assert_count(".o_neon_lms_footer", 0,
                               "Neon footer NOT on non-LMS pages")
            smoke.assert_visible(".s_social_media",
                                 "global footer social icons still present")
            cop = smoke.page.locator(".o_footer_copyright").inner_text()
            smoke._record_assert(
                "global copyright unchanged ('Company name')",
                expect="Company name", actual=cop.strip(),
                passed="Company name" in cop)
            if "Company name" not in cop:
                raise AssertionFail("global copyright changed unexpectedly: %r" % cop)
            smoke.goto_home()

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
