"""neon_web_sidebar -- browser depth-verify + the non-negotiable web_responsive
conflict-test, with screenshots.

DEPTH: rail renders, lists the user's apps, clicking one navigates + highlights,
the systray toggle collapses/expands, content offsets correctly.
CONFLICT: web_responsive's navbar renders once (no double-render), its apps
launcher trigger is intact, the Ctrl-K command palette opens, and there are NO
console errors with the rail present.
Read-only (navigation only). Run after install.
"""
import os
import sys

sys.path.insert(0, ".")
from browser_smoke import BrowserSmoke  # noqa: E402

SHOT_DIR = os.path.join("smoke-output", "neon_web_sidebar")
os.makedirs(SHOT_DIR, exist_ok=True)


def main():
    with BrowserSmoke("neon_web_sidebar") as smoke:
        console_errors = []
        smoke.page.on("console", lambda m: console_errors.append(m.text)
                      if m.type == "error" else None)
        smoke.login("p2m75_book")  # bookkeeper -> sees finance + several apps
        smoke.page.goto(f"{smoke.base_url}/web", wait_until="networkidle")
        smoke.page.wait_for_timeout(800)

        # --- DEPTH: rail renders + lists apps + content offset ---
        with smoke.scenario("rail renders + lists apps"):
            smoke.assert_visible("body.o_neon_sidebar_open .o_neon_sidebar",
                                 "sidebar rail visible (open by default)")
            n = smoke.page.locator(".o_neon_sidebar .o_neon_sidebar_app").count()
            smoke._record_assert("rail lists the user's apps",
                                 expect=">=3 app rows", actual=f"{n} rows", passed=n >= 3)
            ml = smoke.page.evaluate(
                "() => { const am=document.querySelector('.o_action_manager');"
                " return am ? getComputedStyle(am).marginLeft : '0px'; }")
            smoke._record_assert("content offset applied",
                                 expect="action_manager margin-left > 100px",
                                 actual=ml, passed=int(float(ml.replace('px', '') or 0)) > 100)
            smoke.page.screenshot(path=os.path.join(SHOT_DIR, "01_rail_open.png"))

        # --- DEPTH: click an app -> navigates + active highlight ---
        with smoke.scenario("click app navigates + highlights active"):
            apps = smoke.page.locator(".o_neon_sidebar .o_neon_sidebar_app")
            target = apps.nth(min(1, apps.count() - 1))
            label = target.locator(".o_neon_sidebar_label").inner_text()
            target.click()
            smoke.page.wait_for_timeout(1200)
            active = smoke.page.locator(
                ".o_neon_sidebar .o_neon_sidebar_app.o_neon_sidebar_app_active").count()
            smoke._record_assert(f"clicking '{label}' marks an app active",
                                 expect="1 active app row", actual=f"{active} active",
                                 passed=active == 1)
            smoke.page.screenshot(path=os.path.join(SHOT_DIR, "02_rail_active.png"))

        # --- CONFLICT: navbar renders exactly once (no double-render) ---
        with smoke.scenario("web_responsive navbar intact (single render)"):
            navs = smoke.page.locator(".o_main_navbar").count()
            smoke._record_assert("exactly one navbar", expect="1 .o_main_navbar",
                                 actual=f"{navs}", passed=navs == 1)
            # web_responsive's apps-menu trigger present in the navbar
            trig = smoke.page.locator(
                ".o_main_navbar .o_navbar_apps_menu, .o_main_navbar button.o_grid_apps_menu, "
                ".o_main_navbar .o_menu_toggle, .o_main_navbar [accesskey='h']").count()
            smoke._record_assert("web_responsive apps-menu trigger present",
                                 expect=">=1 trigger", actual=f"{trig}", passed=trig >= 1)

        # --- CONFLICT: web_responsive grid launcher still opens ---
        with smoke.scenario("web_responsive grid launcher opens"):
            opened = False
            for sel in [".o_main_navbar .o_grid_apps_menu__button",
                        ".o_grid_apps_menu__button",
                        ".o_main_navbar .o_grid_apps_menu"]:
                loc = smoke.page.locator(sel)
                if loc.count():
                    try:
                        loc.first.click(timeout=2000)
                        smoke.page.wait_for_timeout(800)
                        if smoke.page.locator(
                            "body.o_apps_menu_opened, .o_navbar_apps_menu_search, "
                            ".o_apps_menu, .o_app").count():
                            opened = True
                            break
                    except Exception:
                        continue
            smoke._record_assert("web_responsive grid launcher opens",
                                 expect="apps grid/menu appears", actual=str(opened),
                                 passed=opened)
            if opened:
                smoke.page.screenshot(path=os.path.join(SHOT_DIR, "03_grid_launcher.png"))
                smoke.page.keyboard.press("Escape")
                smoke.page.wait_for_timeout(400)

        # --- CONFLICT: Ctrl-K command palette ---
        with smoke.scenario("Ctrl-K command palette opens"):
            smoke.page.keyboard.press("Control+k")
            smoke.page.wait_for_timeout(600)
            pal = smoke.page.locator(".o_command_palette").count()
            smoke._record_assert("command palette opens", expect=">=1 palette",
                                 actual=f"{pal}", passed=pal >= 1)
            smoke.page.keyboard.press("Escape")

        # --- DEPTH: systray toggle collapses + expands ---
        with smoke.scenario("systray toggle collapses + expands the rail"):
            btn = smoke.page.locator(".o_neon_sidebar_toggle_btn")
            smoke._record_assert("systray toggle present", expect="1 button",
                                 actual=f"{btn.count()}", passed=btn.count() == 1)
            btn.first.click()
            smoke.page.wait_for_timeout(500)
            collapsed = smoke.page.locator("body.o_neon_sidebar_open").count() == 0
            smoke._record_assert("toggle collapses rail (body class removed)",
                                 expect="o_neon_sidebar_open gone", actual=str(collapsed),
                                 passed=collapsed)
            smoke.page.screenshot(path=os.path.join(SHOT_DIR, "04_rail_hidden.png"))
            btn.first.click()
            smoke.page.wait_for_timeout(500)
            reopened = smoke.page.locator("body.o_neon_sidebar_open .o_neon_sidebar").count() == 1
            smoke._record_assert("toggle re-expands rail",
                                 expect="rail visible again", actual=str(reopened),
                                 passed=reopened)

        # --- CONFLICT: no console errors with the rail present ---
        with smoke.scenario("no console errors"):
            real = [e for e in console_errors
                    if "favicon" not in e.lower() and "websocket" not in e.lower()
                    and "/longpolling" not in e.lower() and "503" not in e]
            smoke._record_assert("no console errors", expect="0 errors",
                                 actual=f"{len(real)}: {real[:3]}", passed=len(real) == 0)

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
