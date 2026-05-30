"""M8B.5 DISCOVERY probe (read-only, not committed).

Logs in as each variant tier user + superuser at 375x667, screenshots,
and probes objective layout facts (overflow / wrap / grid tracks /
label visibility). No product change.
"""
from __future__ import annotations
import json
import pathlib
import sys

from browser_smoke import BrowserSmoke

OUT = pathlib.Path(__file__).parent / "m8b5_shots"
OUT.mkdir(exist_ok=True)

PROBE_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const cs = (el, p) => el ? getComputedStyle(el)[p] : null;
  const strip = q('.o_neon_kpi_strip');
  const chips = q('.o_neon_filter_chips');
  const sub = q('.o_neon_dashboard_subtitle');
  const subLines = sub ? Math.round(sub.offsetHeight /
      parseFloat(getComputedStyle(sub).lineHeight || 16)) : null;
  const editLabel = q('.o_neon_dashboard_edit_layout span');
  const rate = q('.o_neon_finance_manage_rate');
  const rateRect = rate ? rate.getBoundingClientRect() : null;
  const root = q('.o_neon_dashboard');
  return {
    innerWidth: window.innerWidth,
    docScrollWidth: document.documentElement.scrollWidth,
    horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 2,
    kpiCols: strip ? getComputedStyle(strip).gridTemplateColumns.split(' ').length : null,
    kpiTiles: document.querySelectorAll('.o_neon_kpi_tile').length,
    chipScrollW: chips ? chips.scrollWidth : null,
    chipClientW: chips ? chips.clientWidth : null,
    chipOverflows: chips ? chips.scrollWidth > chips.clientWidth + 2 : null,
    subtitleText: sub ? sub.textContent.trim() : null,
    subtitleLines: subLines,
    editLabelDisplay: cs(editLabel, 'display'),
    rateRight: rateRect ? Math.round(rateRect.right) : null,
    rateOverflowsViewport: rateRect ? rateRect.right > window.innerWidth + 1 : null,
    blockCols: (q('.o_neon_blocks_unified') ?
        getComputedStyle(q('.o_neon_blocks_unified')).gridTemplateColumns.split(' ').length :
        (q('.o_neon_row_b') ? getComputedStyle(q('.o_neon_row_b')).gridTemplateColumns.split(' ').length : null)),
  };
}
"""

results = {}
with BrowserSmoke("m8b5_probe") as smoke:
    for login, label in [("p8a_director", "director"),
                         ("p8b_sales", "sales"),
                         ("p8b_book", "bookkeeper"),
                         ("p8b_lead", "lead_tech")]:
        try:
            smoke.login(login)
            smoke.page.set_viewport_size({"width": 375, "height": 667})
            smoke.open_action("neon_dashboard.action_neon_dashboard_server")
            smoke.page.wait_for_selector(".o_neon_kpi_strip", timeout=10000)
            smoke.page.wait_for_timeout(500)
            results[label] = smoke.page.evaluate(PROBE_JS)
            smoke.page.screenshot(path=str(OUT / f"{label}_375.png"),
                                  full_page=True)
        except Exception as e:  # noqa: BLE001
            results[label] = {"error": str(e)}

    # Edit mode (superuser director).
    try:
        smoke.login("p8a_director")
        smoke.page.set_viewport_size({"width": 375, "height": 667})
        smoke.open_action("neon_dashboard.action_neon_dashboard_server")
        smoke.page.wait_for_selector(".o_neon_kpi_strip", timeout=10000)
        smoke.page.locator(".o_neon_dashboard_edit_layout").click()
        smoke.page.wait_for_timeout(600)
        edit = smoke.page.evaluate(r"""
        () => {
          const ctrls = document.querySelector('.o_neon_dashboard_controls');
          const btns = [...document.querySelectorAll(
            '.o_neon_edit_save,.o_neon_edit_cancel,.o_neon_edit_reset,.o_neon_edit_apply_all')];
          const tops = btns.map(b => Math.round(b.getBoundingClientRect().top));
          const badge = document.querySelector('.o_neon_always_shown_badge');
          const hideBtns = document.querySelectorAll('.o_neon_block_hide_btn').length;
          const handles = document.querySelectorAll('.o_neon_drag_handle').length;
          const slots = document.querySelectorAll('.o_neon_block_slot').length;
          const unified = !!document.querySelector('.o_neon_blocks_unified');
          return {
            editBtnCount: btns.length,
            editBtnTops: tops,
            editBtnRows: new Set(tops).size,
            ctrlsHeight: ctrls ? Math.round(ctrls.getBoundingClientRect().height) : null,
            alwaysShownBadge: badge ? badge.textContent.trim() : null,
            badgeVisible: badge ? badge.offsetParent !== null : null,
            hideBtns, dragHandles: handles, slots, unified,
            unifiedCols: unified ? getComputedStyle(
              document.querySelector('.o_neon_blocks_unified')).gridTemplateColumns.split(' ').length : null,
          };
        }
        """)
        results["edit_mode"] = edit
        smoke.page.screenshot(path=str(OUT / "edit_mode_375.png"),
                              full_page=True)
    except Exception as e:  # noqa: BLE001
        results["edit_mode"] = {"error": str(e)}

print("PROBE_JSON_START")
print(json.dumps(results, indent=2))
print("PROBE_JSON_END")
sys.exit(0)
