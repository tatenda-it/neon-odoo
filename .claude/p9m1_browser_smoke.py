"""P9.M9.1 browser smoke -- venue map iframe on the event-job form.

Confirms the neon_venue_map_iframe widget renders an <iframe> when the
job's venue has coordinates. Per scope: assert the element exists; do
NOT depend on Google's server-side tile render.
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke

BASE_URL = "http://localhost:8069"
DB = "neon_crm"

_SETUP = """
P = env['res.partner']
zw = env.ref('base.zw', raise_if_not_found=False)
venue = P.search([('name','=','P9 Map Test Venue')], limit=1)
if not venue:
    venue = P.create({
        'name': 'P9 Map Test Venue', 'is_venue': True, 'is_company': True,
        'street': '1 Pennefather Avenue', 'city': 'Harare',
        'country_id': zw.id if zw else False,
        'partner_latitude': -17.8252, 'partner_longitude': 31.0335,
    })
else:
    venue.write({'partner_latitude': -17.8252, 'partner_longitude': 31.0335})
ej = env['commercial.event.job'].search(
    [('commercial_job_id','!=',False)], limit=1)
ej.commercial_job_id.venue_id = venue.id
env.cr.commit()
print('IDS_JSON=' + repr({'ej_id': ej.id, 'venue_id': venue.id}))
"""


def _shell(script):
    p = subprocess.run(
        ["docker", "compose", "--project-directory",
         "C:/Users/Neon/neon-odoo", "exec", "-T", "odoo",
         "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"), capture_output=True, timeout=180)
    return (p.stdout + p.stderr).decode("utf-8", errors="replace")


def _setup():
    out = _shell(_SETUP)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print("[p9m1] SETUP FAILED:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


def run():
    ids = _setup()
    with BrowserSmoke("p9m1") as smoke:
        with smoke.scenario("Event-job Venue page renders map iframe"):
            smoke.login("p8a_director")
            smoke.page.goto(
                f"{BASE_URL}/web#id={ids['ej_id']}"
                f"&model=commercial.event.job&view_type=form")
            smoke.page.wait_for_selector(".o_form_view", timeout=15000)
            smoke.page.wait_for_timeout(800)
            # Click the Venue notebook tab.
            tab = smoke.page.locator(
                ".o_notebook a.nav-link", has_text="Venue")
            if tab.count():
                tab.first.click()
                smoke.page.wait_for_timeout(500)
            iframes = smoke.page.locator(".o_neon_venue_map_iframe").count()
            smoke._record_assert(
                "venue map iframe present on event-job form",
                expect=">=1", actual=str(iframes), passed=iframes >= 1)
            if iframes < 1:
                raise AssertionFail("no .o_neon_venue_map_iframe rendered")
            src = smoke.page.locator(
                ".o_neon_venue_map_iframe").first.get_attribute("src") or ""
            ok_src = "google.com/maps" in src and "output=embed" in src
            smoke._record_assert(
                "iframe src is keyless Maps embed",
                expect="google maps embed", actual=src[:80], passed=ok_src)
            smoke.screenshot("venue_map_iframe")
        return smoke.summary()


if __name__ == "__main__":
    sys.exit(run())
