"""P9.M9.2 browser smoke -- Jobs block venue pin + modal dialog.

Scenarios:
(1) Pin icon renders inside every Jobs row's Venue cell on the
    Director Dashboard.
(2) Clicking the pin opens the venue-map modal containing a Google
    Maps embed iframe (for coord-bearing venue) OR placeholder text
    (for empty venue).
(3) Clicking the venue TEXT (not the icon) opens the event_job form
    via the existing onJobClick row handler -- regression that
    t-on-click.stop on the pin doesn't break row navigation.
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke

BASE_URL = "http://localhost:8069"
DB = "neon_crm"

_SETUP = """
from datetime import date, timedelta
P = env['res.partner']
J = env['commercial.job']
EJ = env['commercial.event.job']
zw = env.ref('base.zw', raise_if_not_found=False)
usd = env.ref('base.USD')

# Coord-bearing venue: Rainbow Towers Hotel coords.
v_coords = P.search([('name','=','P9M2-BR Coords Venue')], limit=1)
vals_c = {'is_venue': True, 'is_company': True,
          'partner_latitude': -17.8567035,
          'partner_longitude': 31.0601584,
          'street': '1 Pennefather Avenue', 'city': 'Harare',
          'country_id': zw.id if zw else False}
if v_coords:
    v_coords.write(vals_c)
else:
    v_coords = P.create(dict(vals_c, name='P9M2-BR Coords Venue'))

# Address-only venue.
v_addr = P.search([('name','=','P9M2-BR Address Venue')], limit=1)
vals_a = {'is_venue': True, 'is_company': True,
          'street': '99 Sample Road', 'city': 'Bulawayo',
          'country_id': zw.id if zw else False}
if v_addr:
    v_addr.write(vals_a)
else:
    v_addr = P.create(dict(vals_a, name='P9M2-BR Address Venue'))

client = P.search([('name','=','P9M2-BR Client')], limit=1)
if not client:
    client = P.create({'name': 'P9M2-BR Client', 'is_company': True})

# Clean any prior event_jobs from previous runs to keep the dashboard
# row count predictable.
EJ.search([('commercial_job_id.partner_id','=',client.id)]).unlink()
J.search([('partner_id','=',client.id)]).unlink()

today = date.today()
j_c = J.create({'partner_id': client.id, 'venue_id': v_coords.id,
                'event_date': today + timedelta(days=1),
                'currency_id': usd.id})
ej_c = EJ.create({'commercial_job_id': j_c.id})
j_a = J.create({'partner_id': client.id, 'venue_id': v_addr.id,
                'event_date': today + timedelta(days=2),
                'currency_id': usd.id})
ej_a = EJ.create({'commercial_job_id': j_a.id})
env.cr.commit()
print('IDS_JSON=' + repr({
    'ej_coords': ej_c.id, 'ej_addr': ej_a.id,
    'venue_coords': v_coords.id, 'venue_addr': v_addr.id,
    'client_id': client.id,
}))
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
        print("[p9m2] SETUP FAILED:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


def _open_dashboard(smoke):
    """Navigate to the Director Dashboard and wait for jobs table."""
    smoke.page.goto(f"{BASE_URL}/web#action=neon_dashboard."
                    f"action_neon_dashboard_server")
    smoke.page.wait_for_selector(".o_neon_jobs_table", timeout=20000)
    smoke.page.wait_for_timeout(800)


def run():
    ids = _setup()
    with BrowserSmoke("p9m2") as smoke:
        smoke.login("p8a_director")

        with smoke.scenario("Pin icon renders in every Venue cell"):
            _open_dashboard(smoke)
            rows = smoke.page.locator(
                ".o_neon_jobs_table .o_neon_jobs_row").count()
            pins = smoke.page.locator(
                ".o_neon_jobs_venue_pin").count()
            smoke._record_assert(
                "pin icon count matches row count",
                expect=f"=={rows}",
                actual=f"rows={rows} pins={pins}",
                passed=pins >= 1 and pins == rows)
            if pins < 1 or pins != rows:
                raise AssertionFail(
                    f"pin/row mismatch: rows={rows} pins={pins}")
            smoke.screenshot("pin_icons_visible")

        with smoke.scenario("Pin click opens modal with coord iframe"):
            _open_dashboard(smoke)
            # Find the row whose venue cell text contains 'Coords'
            # and click its pin (not the text).
            row = smoke.page.locator(
                ".o_neon_jobs_row",
                has=smoke.page.locator(
                    ".o_neon_jobs_venue_cell",
                    has_text="P9M2-BR Coords Venue"))
            pin = row.locator(".o_neon_jobs_venue_pin").first
            pin.click()
            smoke.page.wait_for_selector(
                ".o_neon_venue_modal", timeout=8000)
            smoke.page.wait_for_timeout(400)
            iframes = smoke.page.locator(
                ".o_neon_venue_modal .o_neon_venue_map_iframe").count()
            smoke._record_assert(
                "modal opens + contains map iframe (coords path)",
                expect=">=1", actual=str(iframes),
                passed=iframes >= 1)
            if iframes >= 1:
                src = smoke.page.locator(
                    ".o_neon_venue_modal .o_neon_venue_map_iframe"
                ).first.get_attribute("src") or ""
                ok_src = ("google.com/maps" in src
                          and "output=embed" in src
                          and "-17.85" in src)
                smoke._record_assert(
                    "iframe src embeds the venue's lat/lng",
                    expect="google maps embed w/ coords",
                    actual=src[:120], passed=ok_src)
            smoke.screenshot("modal_coords")
            # Dismiss via the X / close button so next scenario starts
            # without a stacked modal.
            close = smoke.page.locator(
                ".o_neon_venue_modal .btn-close, "
                ".o_neon_venue_modal header button[aria-label='Close']"
            ).first
            if close.count():
                close.click()
                smoke.page.wait_for_timeout(300)

        with smoke.scenario("Pin click on address-only venue: iframe with addr"):
            _open_dashboard(smoke)
            row = smoke.page.locator(
                ".o_neon_jobs_row",
                has=smoke.page.locator(
                    ".o_neon_jobs_venue_cell",
                    has_text="P9M2-BR Address Venue"))
            row.locator(".o_neon_jobs_venue_pin").first.click()
            smoke.page.wait_for_selector(
                ".o_neon_venue_modal", timeout=8000)
            smoke.page.wait_for_timeout(400)
            iframes = smoke.page.locator(
                ".o_neon_venue_modal .o_neon_venue_map_iframe").count()
            smoke._record_assert(
                "modal opens with map iframe (address-only path)",
                expect=">=1", actual=str(iframes),
                passed=iframes >= 1)
            if iframes >= 1:
                src = smoke.page.locator(
                    ".o_neon_venue_modal .o_neon_venue_map_iframe"
                ).first.get_attribute("src") or ""
                ok = "google.com/maps" in src and "Bulawayo" in src
                smoke._record_assert(
                    "iframe src encodes the venue address",
                    expect="address present in src",
                    actual=src[:120], passed=ok)
            smoke.screenshot("modal_address")
            close = smoke.page.locator(
                ".o_neon_venue_modal .btn-close, "
                ".o_neon_venue_modal header button[aria-label='Close']"
            ).first
            if close.count():
                close.click()
                smoke.page.wait_for_timeout(300)

        with smoke.scenario("Venue TEXT click still opens event_job form"):
            _open_dashboard(smoke)
            row = smoke.page.locator(
                ".o_neon_jobs_row",
                has=smoke.page.locator(
                    ".o_neon_jobs_venue_cell",
                    has_text="P9M2-BR Coords Venue"))
            # Click the venue name span (NOT the pin).
            row.locator(".o_neon_jobs_venue_cell span").first.click()
            # Expect navigation to commercial.event.job form.
            smoke.page.wait_for_selector(
                ".o_form_view", timeout=15000)
            smoke.page.wait_for_timeout(500)
            on_form = smoke.page.locator(".o_form_view").count() >= 1
            smoke._record_assert(
                "venue text click opens event_job form",
                expect="form view rendered",
                actual=f"o_form_view count={1 if on_form else 0}",
                passed=on_form)
            smoke.screenshot("text_click_opens_form")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(run())
