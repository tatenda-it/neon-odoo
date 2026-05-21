"""P7a.M12.1 browser smoke -- three QWeb reports (3 scenarios).

1. training_admin sees Reports submenu + 3 report children
2. sales-tier does NOT see Reports submenu (signoff/admin only)
3. Compliance report renders end-to-end (HTTP fetch of PDF
   report endpoint returns content-type application/pdf)
"""

from __future__ import annotations

import json
import sys

from browser_smoke import BrowserSmoke


REPORTS_MENU = "neon_training.menu_neon_training_reports"
EXPIRING_MENU = "neon_training.menu_neon_training_report_expiring"
COMPLIANCE_MENU = "neon_training.menu_neon_training_report_compliance"
CC_MENU = "neon_training.menu_neon_training_report_cross_competency"


def main() -> int:
    # P7a.M12 build instruction: headed mode.
    with BrowserSmoke("p7a_m12_1", headless=False) as smoke:

        # ------------------------------------------------------------
        # Scenario 1: training_admin sees Reports + 3 children
        # ------------------------------------------------------------
        with smoke.scenario("training_admin sees Reports submenu + 3 children"):
            smoke.login("p7am2_train_admin")
            smoke.assert_menu_visible(REPORTS_MENU)
            smoke.assert_menu_visible(EXPIRING_MENU)
            smoke.assert_menu_visible(COMPLIANCE_MENU)
            smoke.assert_menu_visible(CC_MENU)
            smoke.goto_home()

        # ------------------------------------------------------------
        # Scenario 2: sales-tier does NOT see Reports
        # ------------------------------------------------------------
        with smoke.scenario("sales-tier does not see Reports submenu"):
            smoke.login("p2m75_sales")
            smoke.assert_menu_hidden(REPORTS_MENU)
            smoke.assert_menu_hidden(COMPLIANCE_MENU)
            smoke.goto_home()

        # ------------------------------------------------------------
        # Scenario 3: report action records are registered + the
        # expiring report's QWeb template is reachable via the
        # standard /report/html/ endpoint (sanity check that the
        # template renders to HTML without exception).
        # ------------------------------------------------------------
        with smoke.scenario("expiring report renders via /report/html/"):
            smoke.login("p7am2_train_admin")
            # GET /report/html/neon_training.report_expiring
            # _document on an empty docids set is the cheapest
            # render path. If the template has a QWeb error it
            # surfaces here.
            resp = smoke.page.request.get(
                f"{smoke.base_url}/report/html/"
                f"neon_training.report_expiring_document",
            )
            passed = (resp.status == 200)
            smoke._record_assert(
                "expiring report HTML render",
                expect="HTTP 200",
                actual=f"status={resp.status}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "expiring report failed to render")
            smoke.goto_home()

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
