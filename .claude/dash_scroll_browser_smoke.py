"""DASH-SCROLL-FIX browser smoke -- the dashboard root scrolls vertically.

Bug: `.o_neon_dashboard` had `min-height: 100vh` with no overflow-y and no
bounded height -> it grew to fit its content and overflowed its clipped
parent (.o_action_manager), so content below the fold was unreachable with
no scrollbar. Fix: `height: 100%` + `overflow-y: auto` on the root.

This smoke logs in as a Bookkeeper (the tall lens), SHRINKS the viewport so
the dashboard content definitely exceeds the visible area, then asserts the
root is a real bounded scroll container whose below-fold content is reachable:
  * computed overflow-y is auto/scroll
  * scrollHeight > clientHeight  (there IS content below the fold)
  * scrollTop moves off 0 when scrolled to the bottom (it actually scrolls)

With the OLD code the root grows to fit its content, so scrollHeight ==
clientHeight and scrollTop stays 0 -> this smoke would FAIL. So it genuinely
proves the fix, not just that the page renders.
"""

from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP_SCRIPT = """
# DASH-SCROLL browser-smoke setup -- ensure a Bookkeeper fixture exists.
Users = env['res.users']
grp_ids = [
    env.ref('base.group_user').id,
    env.ref('neon_core.group_neon_bookkeeper').id,
]
u = Users.with_context(active_test=False).search(
    [('login', '=', 'dash_scroll_book')], limit=1)
if u:
    u.write({'active': True, 'password': 'test123',
             'groups_id': [(6, 0, grp_ids)]})
else:
    u = Users.with_context(no_reset_password=True).create({
        'name': 'dash_scroll_book', 'login': 'dash_scroll_book',
        'password': 'test123', 'groups_id': [(6, 0, grp_ids)],
    })
env.cr.commit()
print('IDS_JSON=' + repr({'book_id': u.id}))
"""


def _run_odoo_shell(script: str) -> str:
    proc = subprocess.run(
        [
            "docker", "compose",
            "--project-directory", "C:/Users/Neon/neon-odoo",
            "exec", "-T", "odoo",
            "odoo", "shell", "-d", DB, "--no-http",
        ],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=180,
    )
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def _setup_fixtures() -> dict:
    out = _run_odoo_shell(_SETUP_SCRIPT)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print("[dash_scroll] SETUP FAILED -- output tail:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


_SCROLL_PROBE = """
() => {
    const el = document.querySelector('.o_neon_dashboard');
    if (!el) return {found: false};
    const cs = getComputedStyle(el);
    el.scrollTop = 0;
    const startTop = el.scrollTop;
    el.scrollTop = el.scrollHeight;   // try to scroll to the bottom
    const endTop = el.scrollTop;
    return {
        found: true,
        overflowY: cs.overflowY,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
        hasOverflowContent: el.scrollHeight > el.clientHeight + 4,
        startTop: startTop,
        endTop: endTop,
        scrolled: endTop > 0,
    };
}
"""


def run() -> int:
    _setup_fixtures()
    with BrowserSmoke("dash_scroll") as smoke:

        with smoke.scenario(
                "Bookkeeper dashboard root scrolls -- below-fold content "
                "reachable (overflow-y + bounded height)"):
            smoke.login("dash_scroll_book")
            smoke.assert_menu_visible(
                "neon_dashboard.menu_neon_dashboard_root")
            smoke.open_action(
                "neon_dashboard.action_neon_dashboard_server")
            smoke.assert_visible(
                ".o_neon_dashboard", "dashboard root rendered")
            # Confirm we are on the (tall) Bookkeeper lens.
            smoke.assert_visible(
                ".widget--kpi_pending_invoices",
                "Bookkeeper lens (Pending Invoices tile present)")

            # Shrink the viewport so the dashboard content definitely
            # exceeds the visible area, making the scroll test decisive.
            smoke.page.set_viewport_size({"width": 1200, "height": 520})
            smoke.page.wait_for_timeout(500)  # allow OWL relayout

            m = smoke.page.evaluate(_SCROLL_PROBE)
            print(f"[dash_scroll]     scroll metrics: {m}")

            if not m.get("found"):
                raise AssertionFail(
                    ".o_neon_dashboard not found in DOM")
            if m.get("overflowY") not in ("auto", "scroll"):
                raise AssertionFail(
                    f"root overflow-y is {m.get('overflowY')!r}, "
                    f"expected auto/scroll -> root cannot scroll")
            if not m.get("hasOverflowContent"):
                raise AssertionFail(
                    f"root is not a bounded scroll container "
                    f"(scrollHeight={m.get('scrollHeight')} <= "
                    f"clientHeight={m.get('clientHeight')}): the old "
                    f"min-height:100vh grows to fit content instead of "
                    f"scrolling")
            if not m.get("scrolled"):
                raise AssertionFail(
                    f"scrollTop stayed 0 after scrolling to bottom "
                    f"(endTop={m.get('endTop')}): below-fold content "
                    f"unreachable")
            print(f"[dash_scroll]     OK: overflow-y={m['overflowY']}, "
                  f"scrollHeight={m['scrollHeight']} > "
                  f"clientHeight={m['clientHeight']}, "
                  f"scrolled to {m['endTop']}px")
            smoke.screenshot("bookkeeper_scrolled_to_bottom")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(run())
