"""P-HIST-INTEL browser smoke — director Historical Intelligence band + the
three standalone deep-dive pivots over the INERT Zoho archive.

Depth principle:
  * Director dashboard renders the dedicated "Historical · Zoho import" band
    (block + the 3 hist KPI tiles + the "Zoho import" badge + part titles).
  * A hist KPI tile DEEP-LINKS to its standalone pivot (click -> .o_pivot).
  * Each standalone pivot opens AND shows the USD currency guard facet
    (never-blend: the action opens USD-filtered + grouped-by-currency).
  * The LIVE tiles still render alongside (no live-tile breakage).

Fixtures (odoo shell, superuser): a [TEST-HISD] director user (superuser tier,
password test123) + one [TEST-HISD] archive quote. Torn down at the end
(deleting the user cascades its lazy-created dashboard row).

Run from the host venv:
  .\\.claude\\.venv-browser\\Scripts\\python .\\.claude\\phist_intel_browser_smoke.py
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"

DASH_ACTION = "neon_dashboard.action_neon_dashboard_server"
DEMAND_ACTION = "neon_migration.action_hist_demand"
WINLOSS_ACTION = "neon_migration.action_hist_winloss"
REALISATION_ACTION = "neon_migration.action_hist_realisation"

_SETUP_SCRIPT = """
env = env(context=dict(env.context, tracking_disable=True))
U = env['res.users']
QA = env['neon.finance.quote.archive']
U.with_context(active_test=False).search(
    [('login', '=', 'phisd_director')]).unlink()
QA.with_context(active_test=False).search(
    [('zoho_estimate_number', '=like', 'TESTHISD-%')]).unlink()
su = env.ref('neon_core.group_neon_superuser')
director = U.create({
    'name': '[TEST-HISD] Director', 'login': 'phisd_director',
    'password': 'test123', 'groups_id': [(4, su.id)],
}).id
arch = QA.create({
    'zoho_estimate_number': 'TESTHISD-001', 'status_bucket': 'won',
    'currency_code': 'USD', 'quotation_date': '2025-07-01',
    'amount_total': 500.0,
    'line_ids': [(0, 0, {'name': 'HISD SMOKE', 'category_prefix': 'TESTHISDCAT',
                         'quantity': 2.0, 'line_total': 500.0})],
}).id
env.cr.commit()
print('IDS_JSON=' + repr({'director_id': director, 'arch_id': arch}))
"""

_TEARDOWN_TEMPLATE = """
ids = {ids_repr}
for model, key in [('neon.finance.quote.archive', 'arch_id'),
                   ('res.users', 'director_id')]:
    try:
        env[model].browse(ids[key]).unlink()
    except Exception as e:
        print('teardown unlink failed for', model, ids[key], ':', e)
env.cr.commit()
print('TEARDOWN_OK')
"""


def _run_odoo_shell(script: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "--project-directory", "C:/Users/Neon/neon-odoo",
         "exec", "-T", "odoo", "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"), capture_output=True, timeout=180)
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def _setup() -> dict:
    out = _run_odoo_shell(_SETUP_SCRIPT)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out)
        raise RuntimeError("setup did not produce IDS_JSON marker")
    return eval(m.group(1), {"__builtins__": {}}, {})


def _teardown(ids: dict) -> None:
    out = _run_odoo_shell(_TEARDOWN_TEMPLATE.format(ids_repr=repr(ids)))
    if "TEARDOWN_OK" not in out:
        print("[phist_intel] teardown warning:\n" + out[-1200:])


def main() -> int:
    print("[phist_intel] setup: director + archive fixture ...")
    ids = _setup()
    print("[phist_intel] setup ok: director=%s arch=%s"
          % (ids["director_id"], ids["arch_id"]))
    try:
        with BrowserSmoke("phist_intel") as smoke:
            with smoke.scenario("Director dashboard renders Historical band"):
                smoke.login("phisd_director")
                smoke.open_action(DASH_ACTION)
                smoke.assert_visible(".o_neon_dashboard",
                                     "dashboard root renders")
                # The dedicated Historical band + its block + badge.
                smoke.assert_visible(".o_neon_row_historical",
                                     "dedicated Historical section renders")
                smoke.assert_visible(".o_neon_block_hist",
                                     "Historical Intelligence block renders")
                smoke.assert_visible(
                    ".o_neon_hist_badge:has-text('Zoho import')",
                    "Zoho-import reference badge labels the block")
                # The 3 hist KPI tiles (director-only, seeded into the layout).
                smoke.assert_visible(".widget--kpi_hist_winrate",
                                     "Win Rate · Historical KPI tile renders")
                smoke.assert_visible(".widget--kpi_hist_demand",
                                     "Top Demand · Historical KPI tile renders")
                smoke.assert_visible(".widget--kpi_hist_quotes",
                                     "Quotes · Historical KPI tile renders")
                smoke.assert_visible(
                    ".o_neon_hist_part_title:has-text('Top categories')",
                    "demand part title renders (depth)")
                smoke.assert_visible(
                    ".o_neon_hist_part_title:has-text('Realised revenue')",
                    "realisation part title renders (depth)")
                # Live tiles still render alongside (no live-tile breakage).
                smoke.assert_visible(".widget--kpi_cash",
                                     "live Cash KPI still renders")
                smoke.assert_visible(".widget--kpi_pipeline",
                                     "live Pipeline KPI still renders")
                smoke.screenshot("director_historical_band")

            with smoke.scenario("Hist KPI tile deep-links to its pivot"):
                smoke.login("phisd_director")
                smoke.open_action(DASH_ACTION)
                smoke.assert_visible(".widget--kpi_hist_demand",
                                     "demand tile present before click")
                smoke.click(".widget--kpi_hist_demand",
                            name="click Top Demand historical tile")
                smoke.assert_visible(".o_pivot",
                                     "demand tile deep-links to the pivot")
                smoke.screenshot("hist_tile_deeplink_pivot")

            with smoke.scenario("Standalone pivots open + USD currency guard"):
                smoke.login("phisd_director")
                for action, label in (
                        (DEMAND_ACTION, "demand"),
                        (WINLOSS_ACTION, "win/loss"),
                        (REALISATION_ACTION, "realisation")):
                    smoke.open_action(action)
                    smoke.assert_visible(
                        ".o_pivot", "%s pivot renders" % label)
                    # USD default filter facet = the never-blend guard is on.
                    smoke.assert_visible(
                        ".o_searchview:has-text('USD'), "
                        ".o_cp_searchview:has-text('USD')",
                        "%s pivot opens USD-filtered (currency guard)" % label)
                    smoke.screenshot("pivot_%s" % label.replace("/", "_"))

        return smoke.summary()
    finally:
        print("[phist_intel] teardown ...")
        _teardown(ids)


if __name__ == "__main__":
    sys.exit(main())
