"""neon_screens — Event Jobs screen (#3) + Rail v0 slot-4 screenshots."""
import sys
from browser_smoke import BrowserSmoke

CAND = ["p2m75_mgr", "p2m75_sales", "dash_dr_browser"]
TABS = ["Confirmed", "Soft Hold", "TBC", "All"]

with BrowserSmoke("neon_eventjobs_screen") as s:
    used = None
    for l in CAND:
        try:
            s.login(l); used = l; break
        except Exception as e:  # noqa: BLE001
            print(f"[login] {l} failed: {e}")
    if not used:
        print("NO LOGIN"); sys.exit(1)
    print(f"USING {used}")

    with s.scenario(f"event jobs screen ({used})"):
        # 1) Rail order — Event Jobs should sit at slot 4
        s.goto_home(); s.page.wait_for_timeout(2500); s.screenshot("rail_home")

        # 2) Open the Event Jobs screen (server action -> client action)
        s.open_action("neon_screens.action_event_jobs_screen_server")
        try:
            s.page.locator(".o_neon_ej_screen").first.wait_for(state="visible", timeout=15000)
        except Exception as e:  # noqa: BLE001
            print(f"[screen] render wait: {e}")
        s.page.wait_for_timeout(3000)
        s.screenshot("eventjobs_all")

        # depth: count rows + tabs rendered
        try:
            rows = s.page.locator(".o_neon_ej_row").count()
            tabs = s.page.locator(".o_neon_ej_tab").count()
            print(f"[depth] rows={rows} tabs={tabs}")
        except Exception as e:  # noqa: BLE001
            print(f"[depth] {e}")

        # 3) Each filter tab
        for t in TABS:
            try:
                s.page.locator(".o_neon_ej_tab", has_text=t).first.click(timeout=6000)
                s.page.wait_for_timeout(1200)
                s.screenshot(f"eventjobs_tab_{t.lower().replace(' ', '_')}")
            except Exception as e:  # noqa: BLE001
                print(f"[tab {t}] {e}")

    print(f"OUT {s.output_dir}")

sys.exit(s.summary())
