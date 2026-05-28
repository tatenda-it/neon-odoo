"""P9.M9.3 browser smoke -- Venues · Map (multi-pin client action).

Scenarios:
(1) Menu visible -> client action renders header + list + map
(2) 4 fixture venues land in left pane, 2 mapped + 2 unmapped badges
(3) Leaflet markers count = 2 (mapped venues only)
(4) Click list row -> map pans + popup opens
(5) Search "Meikles" -> list filters to 1
(6) Filter chip "Unmapped" -> list shows 2, markers vanish
(7) Filter chip "Mapped" + click Rainbow row -> popup link present
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

def get_or_make(name, vals):
    v = P.search([('name','=',name)], limit=1)
    full = dict(vals, name=name, is_venue=True, is_company=True)
    if v:
        v.write(full)
    else:
        v = P.create(full)
    return v

v_rainbow = get_or_make('P9M3 Rainbow', {
    'city': 'Harare', 'country_id': zw.id if zw else False,
    'partner_latitude': -17.85, 'partner_longitude': 31.06,
})
v_meikles = get_or_make('P9M3 Meikles', {
    'city': 'Harare', 'country_id': zw.id if zw else False,
    'partner_latitude': -17.83, 'partner_longitude': 31.05,
})
v_generic = get_or_make('P9M3 Generic Hall', {
    'street': '5 Sample Road', 'city': 'Bulawayo',
    'country_id': zw.id if zw else False,
    'partner_latitude': 0.0, 'partner_longitude': 0.0,
})
v_empty = get_or_make('P9M3 Empty Venue', {
    'partner_latitude': 0.0, 'partner_longitude': 0.0,
})

# Ensure director user has the lead-tech tier so the menu is visible.
u = env['res.users'].search([('login','=','p8a_director')], limit=1)
if u:
    g_lead = env.ref('neon_jobs.group_neon_jobs_crew_leader')
    g_mgr = env.ref('neon_jobs.group_neon_jobs_manager')
    if g_lead.id not in u.groups_id.ids:
        u.write({'groups_id': [(4, g_lead.id)]})
    if g_mgr.id not in u.groups_id.ids:
        u.write({'groups_id': [(4, g_mgr.id)]})

env.cr.commit()
print('IDS_JSON=' + repr({
    'rainbow': v_rainbow.id, 'meikles': v_meikles.id,
    'generic': v_generic.id, 'empty': v_empty.id,
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
        print("[p9m3] SETUP FAILED:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


def run():
    ids = _setup()
    with BrowserSmoke("p9m3") as smoke:
        smoke.login("p8a_director")

        with smoke.scenario("Open Venues · Map via menu"):
            smoke.page.goto(
                f"{BASE_URL}/web#action=neon_jobs."
                f"action_neon_venue_multi_map_server")
            smoke.page.wait_for_selector(
                ".o_neon_venue_multi_map__map", timeout=20000)
            smoke.page.wait_for_timeout(1500)
            header_count = smoke.page.locator(
                ".o_neon_venue_multi_map__header").count()
            smoke._record_assert(
                "header renders",
                expect=">=1", actual=str(header_count),
                passed=header_count >= 1)
            if header_count < 1:
                raise AssertionFail("header missing")
            smoke.screenshot("multi_map_loaded")

        with smoke.scenario("4 fixture venues in list + correct badges"):
            cards = smoke.page.locator(".o_neon_venue_multi_map__card")
            count = cards.count()
            smoke._record_assert(
                "card count includes 4 fixtures",
                expect=">=4", actual=str(count),
                passed=count >= 4)
            mapped_badges = smoke.page.locator(
                ".o_neon_venue_multi_map__badge_mapped").count()
            address_badges = smoke.page.locator(
                ".o_neon_venue_multi_map__badge_address").count()
            empty_badges = smoke.page.locator(
                ".o_neon_venue_multi_map__badge_empty").count()
            smoke._record_assert(
                "badge breakdown >= 2 mapped, 1 address, 1 empty among "
                "fixtures",
                expect=">=2 mapped >=1 address >=1 empty",
                actual=(f"mapped={mapped_badges} address={address_badges} "
                        f"empty={empty_badges}"),
                passed=(mapped_badges >= 2
                        and address_badges >= 1
                        and empty_badges >= 1))

        with smoke.scenario("Leaflet markers count = mapped venues"):
            markers = smoke.page.locator(".leaflet-marker-icon").count()
            smoke._record_assert(
                "markers >= 2 (mapped fixture venues)",
                expect=">=2", actual=str(markers),
                passed=markers >= 2)
            smoke.screenshot("markers_visible")

        with smoke.scenario("Click list row pans map + opens popup"):
            row = smoke.page.locator(
                ".o_neon_venue_multi_map__card",
                has_text="P9M3 Rainbow").first
            row.click()
            smoke.page.wait_for_timeout(700)
            popup = smoke.page.locator(".leaflet-popup").count()
            smoke._record_assert(
                "popup opened after list click",
                expect=">=1", actual=str(popup),
                passed=popup >= 1)
            open_link = smoke.page.locator(
                ".o_neon_venue_popup_open").count()
            smoke._record_assert(
                "popup contains Open venue link",
                expect=">=1", actual=str(open_link),
                passed=open_link >= 1)
            smoke.screenshot("popup_open")
            # Dismiss popup so next scenario starts clean.
            close = smoke.page.locator(".leaflet-popup-close-button")
            if close.count():
                close.first.click()
                smoke.page.wait_for_timeout(300)

        with smoke.scenario("Search filters list"):
            search = smoke.page.locator(
                ".o_neon_venue_multi_map__search").first
            search.fill("Meikles")
            smoke.page.wait_for_timeout(500)  # debounce 200ms + render
            cards = smoke.page.locator(
                ".o_neon_venue_multi_map__card").count()
            smoke._record_assert(
                "search 'Meikles' -> 1 row",
                expect="==1", actual=str(cards),
                passed=cards == 1)
            # Clear for next scenario
            search.fill("")
            smoke.page.wait_for_timeout(500)

        with smoke.scenario("Unmapped chip hides markers"):
            chip = smoke.page.locator(
                ".o_neon_venue_multi_map__chip",
                has_text="Unmapped").first
            chip.click()
            smoke.page.wait_for_timeout(500)
            markers = smoke.page.locator(".leaflet-marker-icon").count()
            unmapped_cards = smoke.page.locator(
                ".o_neon_venue_multi_map__card").count()
            smoke._record_assert(
                "unmapped chip: 0 markers, >=2 cards",
                expect="markers=0 cards>=2",
                actual=f"markers={markers} cards={unmapped_cards}",
                passed=markers == 0 and unmapped_cards >= 2)
            # Back to All
            smoke.page.locator(
                ".o_neon_venue_multi_map__chip",
                has_text="All").first.click()
            smoke.page.wait_for_timeout(400)

        with smoke.scenario("Mapped chip + click Rainbow row -> popup"):
            smoke.page.locator(
                ".o_neon_venue_multi_map__chip",
                has_text="Mapped").first.click()
            smoke.page.wait_for_timeout(500)
            row = smoke.page.locator(
                ".o_neon_venue_multi_map__card",
                has_text="P9M3 Rainbow").first
            row.click()
            smoke.page.wait_for_timeout(700)
            link_count = smoke.page.locator(
                ".o_neon_venue_popup_open").count()
            smoke._record_assert(
                "Open venue link present in popup",
                expect=">=1", actual=str(link_count),
                passed=link_count >= 1)

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(run())
