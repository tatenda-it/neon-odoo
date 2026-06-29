"""neon_screens — Equipment & Inventory screen + Rail v0 screenshots."""
import sys
from browser_smoke import BrowserSmoke

CAND = ["p2m75_mgr", "p2m75_sales", "dash_dr_browser"]
with BrowserSmoke("neon_equip_screen") as s:
    used = None
    for l in CAND:
        try:
            s.login(l); used = l; break
        except Exception as e:  # noqa: BLE001
            print(f"[login] {l} failed: {e}")
    if not used:
        print("NO LOGIN"); sys.exit(1)
    print(f"USING {used}")

    with s.scenario(f"equipment screen ({used})"):
        # 1) Rail order (home shows the curated sidebar)
        s.goto_home(); s.page.wait_for_timeout(2500); s.screenshot("rail_home")

        # 2) Open the Equipment & Inventory screen (server action -> client action)
        s.open_action("neon_screens.action_equipment_screen_server")
        try:
            s.page.locator(".o_neon_equip_screen").first.wait_for(state="visible", timeout=15000)
        except Exception as e:  # noqa: BLE001
            print(f"[screen] render wait: {e}")
        s.page.wait_for_timeout(3000)
        s.screenshot("equipment_availability")

        # 3) Asset Register tab
        try:
            s.page.get_by_text("Asset Register", exact=True).first.click(timeout=6000)
            s.page.wait_for_timeout(1500)
            s.screenshot("equipment_register")
        except Exception as e:  # noqa: BLE001
            print(f"[register tab] {e}")

    print(f"OUT {s.output_dir}")

sys.exit(s.summary())
