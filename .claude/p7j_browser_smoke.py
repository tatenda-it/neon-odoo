"""P7j browser smoke -- Neon slide cover + global-footer Useful-Links removal.

1. COVER: the neon_branded channel card renders the Neon event cover
   (object-fit:cover anchored top so the top-left logo is NOT clipped),
   not the stock coffee-mug; the placeholder route serves a real image.
2. FOOTER: the global footer (/contactus) no longer shows the "Useful
   Links" column (About-us + Connect-with-us intact); the P7h LMS footer
   (/slides) is unchanged.
"""
from __future__ import annotations

import sys

from browser_smoke import AssertionFail, BrowserSmoke


def main() -> int:
    with BrowserSmoke("p7j") as smoke:

        # --------------------------------------------------------------
        # Scenario 1: Neon slide/channel cover (logo not clipped).
        # --------------------------------------------------------------
        with smoke.scenario("Neon event cover on the channel card (logo not clipped)"):
            smoke.login("robin@neonhiring.co.zw")
            smoke.page.goto(smoke.base_url + "/slides", wait_until="networkidle")
            smoke.page.wait_for_timeout(900)
            smoke.assert_visible("img[src*='slide.channel']", "channel card cover image")
            info = smoke.page.eval_on_selector(
                "img[src*='slide.channel/1'], .o_wslides_background_image img",
                "el => ({op: getComputedStyle(el).objectPosition,"
                " of: getComputedStyle(el).objectFit, w: el.naturalWidth, h: el.naturalHeight})")
            # the fix: crop anchored to the top so the top-left logo survives
            smoke._record_assert(
                "cover crop anchored to top (logo preserved)",
                expect="top ... / cover",
                actual="object-position=%s object-fit=%s" % (info["op"], info["of"]),
                passed=info["op"].startswith("50% 0") or "top" in info["op"].lower()
                or info["op"].split()[-1] in ("0px", "0%", "top"))
            # the served cover is a real landscape image (Neon 16:9), not a tiny/broken placeholder
            ratio = (info["w"] / info["h"]) if info["h"] else 0
            smoke._record_assert(
                "cover is a real landscape image (Neon 16:9)",
                expect="ratio ~1.78, naturalWidth>400",
                actual="%dx%d ratio=%.2f" % (info["w"], info["h"], ratio),
                passed=info["w"] > 400 and 1.5 < ratio < 2.1)
            if not (info["w"] > 400 and 1.5 < ratio < 2.1):
                raise AssertionFail("cover not the expected Neon 16:9 image: %s" % info)
            smoke.screenshot("neon_channel_cover")

        # --------------------------------------------------------------
        # Scenario 2: global footer Useful-Links removed; LMS footer kept.
        # --------------------------------------------------------------
        with smoke.scenario("global footer: 'Useful Links' removed, layout intact"):
            smoke.login("robin@neonhiring.co.zw")
            smoke.page.goto(smoke.base_url + "/contactus", wait_until="networkidle")
            smoke.page.wait_for_timeout(500)
            foot = smoke.page.locator("footer#bottom").inner_text()
            smoke._record_assert(
                "'Useful Links' column removed from global footer",
                expect="absent", actual="present" if "Useful Links" in foot else "absent",
                passed="Useful Links" not in foot)
            if "Useful Links" in foot:
                raise AssertionFail("Useful Links still in global footer")
            # the rest of the global footer is intact
            smoke._record_assert(
                "global footer layout intact (About us + Connect with us)",
                expect="both present",
                actual="about=%s connect=%s" % ("About us" in foot, "Connect with us" in foot),
                passed="About us" in foot and "Connect with us" in foot)
            # P7h LMS footer unchanged on /slides
            smoke.page.goto(smoke.base_url + "/slides", wait_until="networkidle")
            smoke.page.wait_for_timeout(500)
            smoke.assert_visible(".o_neon_lms_footer", "P7h LMS footer still present on /slides")
            smoke.goto_home()

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
