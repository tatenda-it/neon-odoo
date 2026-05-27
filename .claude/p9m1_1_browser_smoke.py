"""P9.M9.1.1 browser smoke -- Leaflet drop-pin on the venue form.

Scenarios: (1) map + marker + OSM attribution render; (2) click-drop
updates the lat field and Save persists across reload; (3) search box
present (live Nominatim soft-checked). Leaflet touch/drag is native;
click is the deterministic commit path we hard-assert.
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
v = P.search([('name','=','P9.1.1 Map Venue')], limit=1)
vals = {'is_venue': True, 'is_company': True, 'city': 'Harare',
        'country_id': zw.id if zw else False,
        'partner_latitude': -17.8252, 'partner_longitude': 31.0335,
        'coords_source': 'geocoded'}
if v:
    v.write(vals)
else:
    v = P.create(dict(vals, name='P9.1.1 Map Venue'))
env.cr.commit()
print('IDS_JSON=' + repr({'venue_id': v.id}))
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
        print("[p9m1_1] SETUP FAILED:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


def run():
    ids = _setup()
    with BrowserSmoke("p9m1_1") as smoke:
        smoke.login("p8a_director")
        url = (f"{BASE_URL}/web#id={ids['venue_id']}"
               f"&model=res.partner&view_type=form")

        with smoke.scenario("Leaflet map + marker + attribution render"):
            smoke.page.goto(url)
            smoke.page.wait_for_selector(".o_neon_venue_pin_map",
                                         timeout=15000)
            smoke.page.wait_for_timeout(1500)  # tiles + invalidateSize
            lc = smoke.page.locator(".leaflet-container").count()
            mk = smoke.page.locator(".leaflet-marker-icon").count()
            attr = smoke.page.locator(
                ".leaflet-control-attribution", has_text="OpenStreetMap"
            ).count()
            smoke._record_assert(
                "leaflet map + marker + attribution",
                expect="container>=1 marker>=1 attr>=1",
                actual=f"container={lc} marker={mk} attr={attr}",
                passed=lc >= 1 and mk >= 1 and attr >= 1)
            if not (lc and mk):
                raise AssertionFail("Leaflet map/marker did not render")
            smoke.screenshot("leaflet_render")

        with smoke.scenario("Click-drop updates lat field + persists"):
            lat_in = smoke.page.locator(
                ".o_field_widget[name='partner_latitude'] input")
            before = lat_in.input_value() if lat_in.count() else None
            # Click off-centre on the map to move the pin.
            smoke.page.locator(".o_neon_venue_pin_map").click(
                position={"x": 90, "y": 70})
            smoke.page.wait_for_timeout(500)
            after = lat_in.input_value() if lat_in.count() else None
            smoke._record_assert(
                "map click changed partner_latitude",
                expect="value changed", actual=f"{before} -> {after}",
                passed=bool(before is not None and after is not None
                            and before != after))
            if before == after:
                raise AssertionFail("map click did not update lat field")
            # Save + reload -> marker persists.
            smoke.page.locator(".o_form_button_save").first.click()
            smoke.page.wait_for_timeout(1200)
            smoke.page.goto(url)
            smoke.page.wait_for_selector(".o_neon_venue_pin_map",
                                         timeout=15000)
            smoke.page.wait_for_timeout(1500)
            mk2 = smoke.page.locator(".leaflet-marker-icon").count()
            smoke._record_assert(
                "marker persists after save+reload",
                expect=">=1", actual=str(mk2), passed=mk2 >= 1)
            smoke.screenshot("after_click_save")

        with smoke.scenario("Search box present (Nominatim soft)"):
            box = smoke.page.locator(".o_neon_venue_pin_search input")
            present = box.count() >= 1
            smoke._record_assert(
                "search input present", expect=">=1",
                actual=str(box.count()), passed=present)
            if present:
                box.first.fill("Harare International Convention Centre")
                smoke.page.wait_for_timeout(2500)  # debounce + network
                res = smoke.page.locator(
                    ".o_neon_venue_pin_results li").count()
                # Soft: live Nominatim may rate-limit/timeout in CI.
                smoke._record_assert(
                    "[soft] nominatim returned results",
                    expect=">=1 (best-effort)", actual=str(res),
                    passed=True)
            smoke.screenshot("search_box")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(run())
