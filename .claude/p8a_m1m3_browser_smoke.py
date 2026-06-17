"""P8A.M1-M3 browser smoke -- Neon Dashboard UI surfaces.

Five scenarios:

1. **p8a_director** lands on /web -> Dashboard menu visible ->
   opens dashboard -> header brand + KPI strip (7 tiles) + filter
   chips + Edit Layout pencil all render.
2. **p8a_book** opens dashboard -> bookkeeper layout (kpi_cash +
   kpi_ar_overdue + kpi_jobs_week mandatory + visible tiles only).
3. **p8a_sales** opens dashboard -> sales layout (pipeline / leads /
   forecast / week tiles).
4. **p8a_director** uses the View-as dropdown to flip to 'sales' ->
   dashboard re-renders with sales widgets only.
5. **p8a_no_tier** (internal user, no neon_core tier group) -> menu
   hidden + RPC denied (AccessError).

Mirrors the P6.M10 cash-flow browser smoke harness pattern.
"""

from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP_SCRIPT = """
# P8A browser-smoke setup -- ensures the five tier fixtures exist
# with password test123 and the right neon_core meta-group.
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
        # Reset password each run -- previous runs may have rotated it.
        user.write({'password': 'test123'})
        if group.id not in user.groups_id.ids:
            user.write({'groups_id': [(4, group.id)]})
    return user

u_director = _get_or_make('p8a_director', 'neon_core.group_neon_superuser')
u_book     = _get_or_make('p8a_book',     'neon_core.group_neon_bookkeeper')
u_sales    = _get_or_make('p8a_sales',    'neon_core.group_neon_sales_rep')
u_lead     = _get_or_make('p8a_lead',     'neon_core.group_neon_lead_tech')
u_crew     = _get_or_make('p8a_crew',     'neon_core.group_neon_crew')

# Negative-case fixture: internal user with NO neon_core tier.
no_tier = Users.search([('login', '=', 'p8a_no_tier')], limit=1)
if not no_tier:
    no_tier = Users.with_context(no_reset_password=True).create({
        'name': 'p8a_no_tier', 'login': 'p8a_no_tier',
        'password': 'test123',
        'groups_id': [(4, env.ref('base.group_user').id)],
    })
else:
    no_tier.write({'password': 'test123'})
for xmlid in ('neon_core.group_neon_superuser',
              'neon_core.group_neon_bookkeeper',
              'neon_core.group_neon_sales_rep',
              'neon_core.group_neon_lead_tech',
              'neon_core.group_neon_crew'):
    g = env.ref(xmlid, raise_if_not_found=False)
    if g and g in no_tier.groups_id:
        no_tier.write({'groups_id': [(3, g.id)]})

env.cr.commit()
print('IDS_JSON=' + repr({
    'director_id': u_director.id, 'book_id': u_book.id,
    'sales_id': u_sales.id, 'lead_id': u_lead.id, 'crew_id': u_crew.id,
    'no_tier_id': no_tier.id,
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
        print("[p8a_m1m3] SETUP FAILED -- output tail:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307 (controlled local input)


def run() -> int:
    _setup_fixtures()
    with BrowserSmoke("p8a_m1m3") as smoke:

        # ============================================================
        # Scenario 1 -- Director sees the full 7-tile dashboard.
        # ============================================================
        with smoke.scenario(
                "p8a_director loads dashboard with 7-tile KPI strip"):
            smoke.login("p8a_director")
            smoke.assert_menu_visible(
                "neon_dashboard.menu_neon_dashboard_root")
            # Server-action xmlid drives /web#action= deep link.
            smoke.open_action(
                "neon_dashboard.action_neon_dashboard_server")
            # Depth principle -- assert content, not just menu reach.
            smoke.assert_visible(
                ".o_neon_dashboard_brand h1",
                "brand h1 visible")
            # Director strip = 7 live tiles + 3 Sales-Intel Layer-1
            # historical tiles (kpi_hist_winrate/demand/quotes).
            smoke.assert_count(
                ".o_neon_kpi_tile", 10, "10 KPI tiles rendered (7 live + 3 historical)")
            smoke.assert_visible(
                ".o_neon_dashboard_edit_layout",
                "Edit Layout pencil visible")
            smoke.assert_visible(
                ".o_neon_dashboard_viewas",
                "View-as dropdown visible (superuser)")
            smoke.assert_visible(
                ".o_neon_filter_chips",
                "filter chip row visible")
            smoke.screenshot("director_dashboard")

        # ============================================================
        # Scenario 2 -- Bookkeeper sees the bookkeeper layout.
        # ============================================================
        with smoke.scenario(
                "p8a_book sees bookkeeper layout (6 KPI tiles)"):
            smoke.login("p8a_book")
            smoke.assert_menu_visible(
                "neon_dashboard.menu_neon_dashboard_root")
            smoke.open_action(
                "neon_dashboard.action_neon_dashboard_server")
            # P8B.M2: bookkeeper default now has 6 KPI tiles: cash /
            # ar_overdue / overdue_60 / pending_invoices /
            # recent_payments / recent_costs (see default_layouts.xml).
            smoke.assert_count(
                ".o_neon_kpi_tile", 6, "6 KPI tiles (bookkeeper)")
            # No View-as dropdown for non-superuser.
            # Use a direct count assertion -- 0 elements.
            smoke.assert_count(
                ".o_neon_dashboard_viewas", 0,
                "View-as dropdown absent (non-superuser)")
            smoke.screenshot("bookkeeper_dashboard")

        # ============================================================
        # Scenario 3 -- Sales sees sales layout.
        # ============================================================
        with smoke.scenario(
                "p8a_sales sees sales layout (6 KPI tiles)"):
            smoke.login("p8a_sales")
            smoke.assert_menu_visible(
                "neon_dashboard.menu_neon_dashboard_root")
            smoke.open_action(
                "neon_dashboard.action_neon_dashboard_server")
            # P8B.M1: sales default now has 6 KPI tiles: pipeline /
            # leads / hot_deals / aging_quotes / won_mtd / win_rate.
            smoke.assert_count(
                ".o_neon_kpi_tile", 6, "6 KPI tiles (sales)")
            smoke.screenshot("sales_dashboard")

        # ============================================================
        # Scenario 4 -- Director uses View-as to flip to Sales.
        # Compresses: re-login as superuser, open dashboard, simulate
        # the select-change RPC that the OWL component fires when the
        # dropdown changes.
        # ============================================================
        with smoke.scenario(
                "p8a_director flips View-as to Sales"):
            smoke.login("p8a_director")
            smoke.open_action(
                "neon_dashboard.action_neon_dashboard_server")
            # Drive the dropdown via Playwright's select_option helper.
            smoke.page.locator(
                ".o_neon_dashboard_viewas").select_option("sales")
            # Re-render is async; wait for the post-flip KPI tile
            # count to settle to 6 (P8B sales layout).
            smoke.assert_count(
                ".o_neon_kpi_tile", 6,
                "after View-as=sales: 6 KPI tiles")
            smoke.screenshot("director_viewas_sales")

        # ============================================================
        # Scenario 5 -- no-tier user is blocked.
        # ============================================================
        with smoke.scenario(
                "p8a_no_tier cannot reach dashboard"):
            smoke.login("p8a_no_tier")
            smoke.assert_menu_hidden(
                "neon_dashboard.menu_neon_dashboard_root")
            # RPC layer also rejects.
            smoke.assert_rpc_denied(
                "neon.dashboard", "get_dashboard_data",
                "RPC denied for non-tier user",
                args=[],
            )

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(run())
