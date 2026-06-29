"""neon_screens — composed Operations Calendar with custom in-screen switcher."""
import sys
from browser_smoke import BrowserSmoke

CAND = ["p2m75_mgr", "p2m75_sales", "dash_dr_browser"]
console_errors = []

PROBE = """() => ({
    vtabs: document.querySelectorAll('.o_neon_vtab').length,
    active_tab: ((document.querySelector('.o_neon_vtab_active')||{}).textContent||'').trim(),
    holds_rows: document.querySelectorAll('.o_neon_hold_row').length,
    fc: document.querySelectorAll('.fc, .fc-view-harness').length,
    list: document.querySelectorAll('.o_list_table, .o_list_renderer').length,
    kanban: document.querySelectorAll('.o_kanban_renderer, .o_kanban_view').length,
})"""

with BrowserSmoke("neon_ops_composed") as s:
    s.page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    used = None
    for l in CAND:
        try:
            s.login(l); used = l; break
        except Exception as e:  # noqa: BLE001
            print(f"[login] {l} failed: {e}")
    if not used:
        print("NO LOGIN"); sys.exit(1)
    print(f"USING {used}")

    with s.scenario(f"composed switcher ({used})"):
        s.open_action("neon_screens.action_operations_screen_server")
        s.page.locator(".o_neon_ops_screen").first.wait_for(state="visible", timeout=15000)
        s.page.wait_for_timeout(3500)
        s.screenshot("01_calendar")
        print("CALENDAR", s.page.evaluate(PROBE))

        for mode, label in [("List", "02_list"), ("Kanban", "03_kanban"), ("Calendar", "04_calendar_back")]:
            try:
                s.page.locator(".o_neon_vtab", has_text=mode).first.click(timeout=6000)
                s.page.wait_for_timeout(2200)
                s.screenshot(label)
                print(mode.upper(), s.page.evaluate(PROBE))
            except Exception as e:  # noqa: BLE001
                print(f"[{mode}] {e}")

        # popup on the calendar (we're back on Calendar)
        try:
            s.page.locator(".fc-event, .fc-daygrid-event").first.click(timeout=5000)
            s.page.wait_for_timeout(1200)
            s.screenshot("05_popup")
            print("popup: clicked")
        except Exception as e:  # noqa: BLE001
            print(f"[popup] {e}")

    real = [e for e in console_errors if e]
    print(f"CONSOLE_ERRORS {len(real)}")
    for e in real[:12]:
        print("  CERR:", e)
    print(f"OUT {s.output_dir}")

sys.exit(s.summary())
