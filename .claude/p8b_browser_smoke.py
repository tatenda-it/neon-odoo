"""P8B browser smoke -- role-variant dashboards (Sales / Bookkeeper /
Lead Tech) + MD-peek selector + mobile scroll reachability.

Six scenarios (the architecture auto-routes each tier to its own
variant via a SINGLE Dashboard menu -- there are no per-variant menus,
so "sees X not Y" is expressed as "the auto-routed variant renders its
own KPI/chip/block set"; cross-variant peek is superuser-only via the
View-as selector):

1. p8b_sales   -> Sales variant: 6 KPI tiles + Hot/Aging/Won chips +
   Hot Deals Watch block; no View-as selector (non-superuser).
2. p8b_book    -> Bookkeeper variant: 6 KPI tiles + Overdue/Due Soon/
   Recently Paid chips + Budget Alerts block.
3. p8b_lead    -> Lead Tech variant: 4 KPI tiles + Today/Next 7/Next 30
   chips + Crew Gaps Watch block.
4. p8b_super   -> View-as peek flips Director -> Sales -> Bookkeeper ->
   Lead Tech, each re-rendering the right tile count.
5. Sales 'Won' chip hides the Hot Deals block (client-side filter).
6. Sales variant at 375px: scroll reachability (M12.1 guard).
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

u_sales = _get_or_make('p8b_sales', 'neon_core.group_neon_sales_rep')
u_book  = _get_or_make('p8b_book',  'neon_core.group_neon_bookkeeper')
u_lead  = _get_or_make('p8b_lead',  'neon_core.group_neon_lead_tech')
u_super = _get_or_make('p8b_super', 'neon_core.group_neon_superuser')

env.cr.commit()
print('IDS_JSON=' + repr({
    'sales_id': u_sales.id, 'book_id': u_book.id,
    'lead_id': u_lead.id, 'super_id': u_super.id,
}))
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
        print("[p8b] SETUP FAILED -- output tail:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


def _open_dashboard(smoke):
    smoke.open_action("neon_dashboard.action_neon_dashboard_server")
    smoke.page.wait_for_selector(".o_neon_kpi_strip", timeout=10000)


def run() -> int:
    _setup_fixtures()
    with BrowserSmoke("p8b") as smoke:

        # =====================================================
        # Scenario 1 -- Sales variant.
        # =====================================================
        with smoke.scenario("p8b_sales sees the Sales variant"):
            smoke.login("p8b_sales")
            smoke.assert_menu_visible(
                "neon_dashboard.menu_neon_dashboard_root")
            _open_dashboard(smoke)
            smoke.assert_count(
                ".o_neon_kpi_tile", 6, "6 KPI tiles (sales)")
            smoke.assert_visible(
                ".widget--block_hot_deals", "Hot Deals Watch block")
            smoke.assert_visible(
                ".o_neon_filter_chip", "filter chips present")
            # Non-superuser: no View-as selector.
            smoke.assert_count(
                ".o_neon_dashboard_viewas", 0, "no View-as (non-super)")
            # Sales chip labels.
            won_chips = smoke.page.locator(
                ".o_neon_filter_chip", has_text="Won").count()
            smoke._record_assert(
                "sales chip 'Won' present", expect=">=1",
                actual=str(won_chips), passed=won_chips >= 1)
            smoke.screenshot("sales_variant")

        # =====================================================
        # Scenario 2 -- Bookkeeper variant.
        # =====================================================
        with smoke.scenario("p8b_book sees the Bookkeeper variant"):
            smoke.login("p8b_book")
            _open_dashboard(smoke)
            smoke.assert_count(
                ".o_neon_kpi_tile", 6, "6 KPI tiles (bookkeeper)")
            smoke.assert_visible(
                ".widget--block_budget_alerts", "Budget Alerts block")
            paid = smoke.page.locator(
                ".o_neon_filter_chip", has_text="Recently Paid").count()
            smoke._record_assert(
                "bookkeeper chip 'Recently Paid' present", expect=">=1",
                actual=str(paid), passed=paid >= 1)
            smoke.screenshot("bookkeeper_variant")

        # =====================================================
        # Scenario 3 -- Lead Tech variant.
        # =====================================================
        with smoke.scenario("p8b_lead sees the Lead Tech variant"):
            smoke.login("p8b_lead")
            _open_dashboard(smoke)
            smoke.assert_count(
                ".o_neon_kpi_tile", 4, "4 KPI tiles (lead_tech)")
            smoke.assert_visible(
                ".widget--block_crew_gaps", "Crew Gaps Watch block")
            smoke.assert_visible(
                ".widget--block_cert_expiry", "Cert Expiry Watch block")
            n30 = smoke.page.locator(
                ".o_neon_filter_chip", has_text="Next 30 Days").count()
            smoke._record_assert(
                "lead_tech chip 'Next 30 Days' present", expect=">=1",
                actual=str(n30), passed=n30 >= 1)
            smoke.screenshot("lead_tech_variant")

        # =====================================================
        # Scenario 4 -- Superuser View-as peek across variants.
        # =====================================================
        with smoke.scenario("p8b_super peeks via View-as selector"):
            smoke.login("p8b_super")
            _open_dashboard(smoke)
            smoke.assert_visible(
                ".o_neon_dashboard_viewas", "View-as selector (super)")
            for dtype, count in (("sales", 6), ("bookkeeper", 6),
                                 ("lead_tech", 4)):
                smoke.page.locator(
                    ".o_neon_dashboard_viewas").select_option(dtype)
                smoke.page.wait_for_timeout(600)
                smoke.assert_count(
                    ".o_neon_kpi_tile", count,
                    f"View-as={dtype}: {count} KPI tiles")
            smoke.screenshot("super_viewas")

        # =====================================================
        # Scenario 5 -- Sales 'Won' chip hides Hot Deals block.
        # =====================================================
        with smoke.scenario("Sales 'Won' chip hides Hot Deals block"):
            smoke.login("p8b_sales")
            _open_dashboard(smoke)
            smoke.page.locator(
                ".o_neon_filter_chip", has_text="Won").first.click()
            smoke.page.wait_for_timeout(300)
            hidden = smoke.page.evaluate(
                "() => { const e = document.querySelector"
                "('.widget--block_hot_deals');"
                " return e ? getComputedStyle(e).display === 'none'"
                " : false; }")
            smoke._record_assert(
                "Won chip hides Hot Deals block",
                expect="display:none", actual=str(hidden), passed=hidden)
            if not hidden:
                raise AssertionFail("Won chip did not hide Hot Deals")
            smoke.screenshot("sales_won_filter")

        # =====================================================
        # Scenario 6 -- Sales variant mobile scroll reachability.
        # (M12.1 guard: tag browser-smoke-must-test-scroll-reachability)
        # =====================================================
        with smoke.scenario("Sales variant scroll-reachable at 375px"):
            smoke.login("p8b_sales")
            _open_dashboard(smoke)
            smoke.page.set_viewport_size({"width": 375, "height": 720})
            smoke.page.wait_for_timeout(500)
            probe = smoke.page.evaluate(
                "() => {\n"
                " const el = document.querySelector('.o_neon_dashboard');\n"
                " if (!el) return {found: false};\n"
                " const scrollable = el.scrollHeight > el.clientHeight + 10;\n"
                " el.scrollTop = 0;\n"
                " el.scrollTo({top: 1500});\n"
                " const moved = el.scrollTop > 200;\n"
                " return {found: true, scrollable, moved,\n"
                "   scrollHeight: el.scrollHeight,\n"
                "   clientHeight: el.clientHeight};\n"
                "}")
            ok = (probe.get("found") and probe.get("scrollable")
                  and probe.get("moved"))
            smoke._record_assert(
                "mobile: sales dashboard scroll-reachable",
                expect="scrollable + scrollTo moves",
                actual=(f"scrollH={probe.get('scrollHeight')} "
                        f"clientH={probe.get('clientHeight')} "
                        f"moved={probe.get('moved')}"),
                passed=bool(ok))
            if not ok:
                raise AssertionFail(
                    f"sales mobile not scroll-reachable: probe={probe}")
            # Deepest block (AI Insights) reachable.
            ai_reachable = smoke.page.evaluate(
                "() => { const ai = document.querySelector"
                "('.o_neon_block_ai, .widget--block_ai_insights');"
                " if (!ai) return false;"
                " ai.scrollIntoView({block: 'center'});"
                " const r = ai.getBoundingClientRect();"
                " return r.top < window.innerHeight && r.bottom > 0; }")
            smoke._record_assert(
                "mobile: AI Insights reachable via scroll",
                expect="intersects viewport", actual=str(ai_reachable),
                passed=bool(ai_reachable))
            if not ai_reachable:
                raise AssertionFail("AI block not reachable on sales mobile")
            smoke.screenshot("sales_mobile_375")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(run())
