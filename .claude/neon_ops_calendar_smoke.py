"""neon_screens — Operations Calendar + Holds to chase + Rail screenshots."""
import sys
from browser_smoke import BrowserSmoke

CAND = ["p2m75_mgr", "p2m75_sales", "dash_dr_browser"]
with BrowserSmoke("neon_ops_calendar") as s:
    used = None
    for l in CAND:
        try:
            s.login(l); used = l; break
        except Exception as e:  # noqa: BLE001
            print(f"[login] {l} failed: {e}")
    if not used:
        print("NO LOGIN"); sys.exit(1)
    print(f"USING {used}")

    with s.scenario(f"ops calendar ({used})"):
        s.goto_home(); s.page.wait_for_timeout(2500); s.screenshot("rail")

        s.open_action("neon_screens.action_operations_calendar")
        try:
            s.page.locator(".o_calendar_view, .fc").first.wait_for(state="visible", timeout=15000)
        except Exception as e:  # noqa: BLE001
            print(f"[calendar] wait: {e}")
        s.page.wait_for_timeout(3500)
        s.screenshot("calendar_month")

        s.open_action("neon_screens.action_holds_to_chase")
        s.page.wait_for_timeout(2500)
        s.screenshot("holds_to_chase")

    print(f"OUT {s.output_dir}")
sys.exit(s.summary())
