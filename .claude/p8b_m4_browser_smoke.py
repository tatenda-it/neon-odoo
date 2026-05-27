"""P8B.M4 browser smoke -- Edit Layout UI.

Six scenarios (desktop 1280 unless noted):

1. Edit Layout button toggles edit mode: Save/Cancel/Reset render,
   filter chips hidden, unified grid + drag handles appear.
2. Hide a non-mandatory block -> stub appears in edit mode.
3. Save -> block hidden in view; is_customized -> unified grid persists
   across reload.
4. Reset to defaults -> rich layout returns (hidden block reappears).
5. Apply to all my variants (superuser) -> success toast.
6. Mobile 375px: edit-mode unified grid scroll-reachable (M12.1 guard);
   drag handle present.
"""

from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP_SCRIPT = """
Users = env['res.users']
Dashboard = env['neon.dashboard']

def _get_or_make(login, group_xmlid):
    user = Users.search([('login', '=', login)], limit=1)
    group = env.ref(group_xmlid)
    if not user:
        user = Users.with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'password': 'test123',
            'groups_id': [(4, group.id)],
        })
    else:
        user.write({'password': 'test123'})
        if group.id not in user.groups_id.ids:
            user.write({'groups_id': [(4, group.id)]})
    return user

u_super = _get_or_make('p8b_m4_super', 'neon_core.group_neon_superuser')
u_book  = _get_or_make('p8b_m4_book',  'neon_core.group_neon_bookkeeper')

# Start each run from a clean (non-customised) director layout for the
# superuser so the toggle/hide/save/reset flow is deterministic.
for dtype in ('director', 'sales', 'bookkeeper'):
    d = Dashboard.sudo().get_or_create_for_user(
        user_id=u_super.id, dashboard_type=dtype)
    d.layout_ids.unlink()
    d.write({'is_customized': False})
    d._seed_default_layout()
db = Dashboard.sudo().get_or_create_for_user(
    user_id=u_book.id, dashboard_type='bookkeeper')
db.layout_ids.unlink()
db.write({'is_customized': False})
db._seed_default_layout()

env.cr.commit()
print('IDS_JSON=' + repr({'super_id': u_super.id, 'book_id': u_book.id}))
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
        print("[p8b_m4] SETUP FAILED -- output tail:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


def _open(smoke):
    smoke.open_action("neon_dashboard.action_neon_dashboard_server")
    smoke.page.wait_for_selector(".o_neon_kpi_strip", timeout=10000)


def _count(smoke, selector):
    return smoke.page.locator(selector).count()


def run() -> int:
    _setup_fixtures()
    with BrowserSmoke("p8b_m4") as smoke:

        # =====================================================
        # Scenario 1 -- toggle edit mode.
        # =====================================================
        with smoke.scenario("Edit Layout toggles edit mode"):
            smoke.login("p8b_m4_super")
            _open(smoke)
            smoke.page.locator(".o_neon_dashboard_edit_layout").click()
            smoke.page.wait_for_timeout(400)
            smoke.assert_visible(".o_neon_edit_save", "Save button")
            smoke.assert_visible(".o_neon_edit_cancel", "Cancel button")
            smoke.assert_visible(".o_neon_edit_reset", "Reset button")
            smoke.assert_visible(".o_neon_blocks_unified",
                                 "unified block grid")
            chips = _count(smoke, ".o_neon_filter_chips")
            smoke._record_assert(
                "filter chips hidden in edit mode", expect="0",
                actual=str(chips), passed=chips == 0)
            handles = _count(smoke, ".o_neon_drag_handle")
            smoke._record_assert(
                "drag handles present", expect=">=1",
                actual=str(handles), passed=handles >= 1)
            smoke.screenshot("edit_mode_on")

        # =====================================================
        # Scenario 2 -- hide a block -> stub appears.
        # =====================================================
        with smoke.scenario("Hide block -> stub appears"):
            # block_sales is non-mandatory on the director layout.
            hide_btn = smoke.page.locator(
                ".widget--block_sales .o_neon_block_hide_btn")
            if hide_btn.count() == 0:
                raise AssertionFail("no Hide button on block_sales slot")
            hide_btn.first.click()
            smoke.page.wait_for_timeout(300)
            stub = _count(smoke, ".widget--block_sales .o_neon_block_stub")
            smoke._record_assert(
                "block_sales shows stub after Hide", expect=">=1",
                actual=str(stub), passed=stub >= 1)
            if stub < 1:
                raise AssertionFail("stub did not appear")
            smoke.screenshot("block_hidden_stub")

        # =====================================================
        # Scenario 3 -- Save -> hidden in view + persists on reload.
        # =====================================================
        with smoke.scenario("Save persists hide across reload"):
            smoke.page.locator(".o_neon_edit_save").click()
            smoke.page.wait_for_timeout(600)
            # View mode (customised -> unified); block_sales absent.
            vis = _count(smoke, ".widget--block_sales")
            smoke._record_assert(
                "block_sales absent in view after Save", expect="0",
                actual=str(vis), passed=vis == 0)
            # Reload the action; still hidden + still unified.
            _open(smoke)
            unified = _count(smoke, ".o_neon_blocks_unified")
            vis2 = _count(smoke, ".widget--block_sales")
            smoke._record_assert(
                "persists after reload (unified + hidden)",
                expect="unified>=1 & sales=0",
                actual=f"unified={unified} sales={vis2}",
                passed=unified >= 1 and vis2 == 0)
            smoke.screenshot("saved_hidden")

        # =====================================================
        # Scenario 4 -- Reset -> rich layout returns.
        # =====================================================
        with smoke.scenario("Reset restores default layout"):
            smoke.page.locator(".o_neon_dashboard_edit_layout").click()
            smoke.page.wait_for_timeout(300)
            smoke.page.locator(".o_neon_edit_reset").click()
            smoke.page.wait_for_timeout(600)
            # Back to rich layout: row_a present, block_sales visible.
            rich = _count(smoke, ".o_neon_row_a")
            sales_back = _count(smoke, ".widget--block_sales")
            smoke._record_assert(
                "reset -> rich layout + block_sales restored",
                expect="row_a>=1 & sales>=1",
                actual=f"row_a={rich} sales={sales_back}",
                passed=rich >= 1 and sales_back >= 1)
            smoke.screenshot("reset_restored")

        # =====================================================
        # Scenario 5 -- Apply to all my variants (superuser).
        # =====================================================
        with smoke.scenario("Apply to all my variants (superuser)"):
            smoke.page.locator(".o_neon_dashboard_edit_layout").click()
            smoke.page.wait_for_timeout(300)
            apply_btn = smoke.page.locator(".o_neon_edit_apply_all")
            smoke._record_assert(
                "Apply-to-all button present for superuser",
                expect=">=1", actual=str(apply_btn.count()),
                passed=apply_btn.count() >= 1)
            if apply_btn.count() >= 1:
                apply_btn.first.click()
                smoke.page.wait_for_timeout(800)
                toast = smoke.page.locator(
                    ".o_notification, .o_notification_body").count()
                smoke._record_assert(
                    "apply-to-all fired a notification", expect=">=1",
                    actual=str(toast), passed=toast >= 1)
            smoke.screenshot("apply_all")

        # =====================================================
        # Scenario 6 -- mobile 375px edit-mode scroll reachability.
        # =====================================================
        with smoke.scenario("Mobile 375px edit-mode scroll-reachable"):
            smoke.login("p8b_m4_super")
            _open(smoke)
            smoke.page.set_viewport_size({"width": 375, "height": 720})
            smoke.page.wait_for_timeout(400)
            smoke.page.locator(".o_neon_dashboard_edit_layout").click()
            smoke.page.wait_for_timeout(400)
            smoke.assert_visible(".o_neon_blocks_unified",
                                 "unified grid at 375px")
            handles = _count(smoke, ".o_neon_drag_handle")
            smoke._record_assert(
                "drag handle present at 375px", expect=">=1",
                actual=str(handles), passed=handles >= 1)
            probe = smoke.page.evaluate(
                "() => {\n"
                " const el = document.querySelector('.o_neon_dashboard');\n"
                " if (!el) return {found: false};\n"
                " const scrollable = el.scrollHeight > el.clientHeight + 10;\n"
                " el.scrollTop = 0; el.scrollTo({top: 1500});\n"
                " return {found: true, scrollable,"
                " moved: el.scrollTop > 200};\n"
                "}")
            ok = probe.get("found") and probe.get("scrollable") \
                and probe.get("moved")
            smoke._record_assert(
                "mobile edit-mode scroll-reachable",
                expect="scrollable + scrollTo moves",
                actual=str(probe), passed=bool(ok))
            if not ok:
                raise AssertionFail(f"edit-mode not scrollable: {probe}")
            smoke.screenshot("edit_mobile_375")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(run())
