"""neon_theme — capture dashboard + list + form screenshots for design review.

Run: .\\.claude\\.venv-browser\\Scripts\\python .\\.claude\\neon_theme_screens.py
"""
import sys
from browser_smoke import BrowserSmoke

CANDIDATES = ["p2m75_sales", "p2m75_mgr", "p2m75_book", "p2m75_approver"]

with BrowserSmoke("neon_theme") as s:
    used = None
    for login in CANDIDATES:
        try:
            s.login(login)
            used = login
            break
        except Exception as e:  # noqa: BLE001
            print(f"[login] {login} failed: {e}")
    if not used:
        print("NO WORKING LOGIN")
        sys.exit(1)
    print(f"USING LOGIN: {used}")

    with s.scenario(f"neon_theme screenshots ({used})"):
        # 1) Neon KPI dashboard (server action -> client dashboard)
        try:
            s.open_action("neon_dashboard.action_neon_dashboard_server")
            s.page.wait_for_timeout(3500)
            s.screenshot("dashboard")
        except Exception as e:  # noqa: BLE001
            print(f"[dashboard] failed: {e}; falling back to home")
            s.goto_home(); s.page.wait_for_timeout(3000); s.screenshot("dashboard_home_fallback")

        # 2) A list view with REAL rows (Contacts = 4805 partners), forced to list
        try:
            s.open_action("contacts.action_contacts")
            s.page.wait_for_timeout(1800)
            try:
                s.page.locator(".o_cp_switch_buttons button.o_list, button[data-tooltip='List']").first.click(timeout=3000)
                s.page.wait_for_timeout(1500)
            except Exception:
                pass
            s.screenshot("list_contacts")
        except Exception as e:  # noqa: BLE001
            print(f"[list] contacts failed: {e}")

        # 3) A record form — click a data CELL (not the <tr>, which intercepts)
        try:
            s.page.locator("td.o_data_cell").first.click(timeout=8000)
            s.page.wait_for_timeout(2000)
            s.screenshot("form_contact")
        except Exception as e:  # noqa: BLE001
            print(f"[form] cell-click failed: {e}; trying kanban card")
            try:
                s.page.locator(".o_kanban_record").first.click(timeout=6000)
                s.page.wait_for_timeout(2000)
                s.screenshot("form_contact")
            except Exception as e2:  # noqa: BLE001
                print(f"[form] kanban-click also failed: {e2}")

    print(f"OUTPUT_DIR {s.output_dir}")

sys.exit(s.summary())
