import sys
from browser_smoke import BrowserSmoke

CAND = ["dash_dr_browser", "dash_scroll_book"]
with BrowserSmoke("neon_theme_dash") as s:
    used = None
    for l in CAND:
        try:
            s.login(l); used = l; break
        except Exception as e:  # noqa: BLE001
            print(f"[login] {l} failed: {e}")
    if not used:
        print("NO LOGIN"); sys.exit(1)
    print(f"USING {used}")
    with s.scenario(f"dashboard ({used})"):
        s.goto_home(); s.page.wait_for_timeout(4500); s.screenshot("dashboard_home")
        try:
            s.open_action("neon_dashboard.action_neon_dashboard_server")
            s.page.wait_for_timeout(4500); s.screenshot("dashboard_action")
        except Exception as e:  # noqa: BLE001
            print(f"[dash action] {e}")
    print(f"OUT {s.output_dir}")
sys.exit(s.summary())
