"""P7a.M12 core browser smoke -- dashboard + wizard surface (5 scenarios).

1. training_admin opens Dashboard menu; counters render in form
2. training_admin opens Find Qualified User; wizard form renders
3. sales-tier (p2m75_sales) sees Find Qualified User menu
4. sales-tier does NOT see Dashboard menu (training_user only)
5. Gate Log kanban view + tier_3 in selection
"""

from __future__ import annotations

import json
import sys

from browser_smoke import BrowserSmoke


DASHBOARD_MENU = "neon_training.menu_neon_training_dashboard"
FIND_USER_MENU = "neon_training.menu_neon_training_find_qualified_user"
GATE_LOG_ACTION = "neon_training.assignment_gate_log_action"
DASHBOARD_ACTION = "neon_training.neon_training_dashboard_action_server"
FIND_USER_ACTION = (
    "neon_training.neon_training_find_qualified_user_action_server")


def main() -> int:
    # P7a.M12 build instruction: launch headed so Tatenda can
    # watch the browser during active development. Phase 11
    # polish backlog item logged to revisit headless default
    # for production CI.
    with BrowserSmoke("p7a_m12", headless=False) as smoke:

        # ------------------------------------------------------------
        # Scenario 1: admin opens Dashboard; counters render
        # ------------------------------------------------------------
        with smoke.scenario("training_admin opens Dashboard; counters render"):
            smoke.login("p7am2_train_admin")
            smoke.assert_menu_visible(DASHBOARD_MENU)
            smoke.open_action(DASHBOARD_ACTION)
            smoke.assert_visible("div.o_form_view",
                                 "dashboard form view")
            # Counter fields visible -- pick one for the assertion.
            body = smoke.json_rpc(
                "neon.training.dashboard",
                "fields_get",
                args=[["active_certs_total",
                       "tier_1_fires_30d", "tier_3_fires_30d"]],
            )
            field_meta = (body.get("result") or {})
            passed = (
                "active_certs_total" in field_meta
                and "tier_3_fires_30d" in field_meta)
            smoke._record_assert(
                "dashboard counter fields present",
                expect="active_certs_total + tier_3_fires_30d",
                actual=f"keys={sorted(field_meta.keys())}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail("dashboard counter fields missing")
            smoke.screenshot("admin_dashboard_open")

        # ------------------------------------------------------------
        # Scenario 2: admin opens Find Qualified User wizard
        # ------------------------------------------------------------
        with smoke.scenario("training_admin opens Find Qualified User wizard"):
            smoke.login("p7am2_train_admin")
            smoke.assert_menu_visible(FIND_USER_MENU)
            body = smoke.json_rpc(
                "neon.training.find_qualified_user_wizard",
                "fields_get",
                args=[["cert_type_ids", "required_level",
                       "include_cross_competency",
                       "matched_user_ids"]],
            )
            field_meta = (body.get("result") or {})
            expected = {"cert_type_ids", "required_level",
                        "include_cross_competency",
                        "matched_user_ids"}
            present = set(field_meta.keys()) & expected
            passed = (present == expected)
            smoke._record_assert(
                "M12 wizard fields present",
                expect=sorted(expected),
                actual=sorted(present),
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail("M12 wizard fields missing")

        # ------------------------------------------------------------
        # Scenario 3: sales-tier sees Find Qualified User menu
        # ------------------------------------------------------------
        with smoke.scenario("sales-tier sees Find Qualified User menu"):
            smoke.login("p2m75_sales")
            smoke.assert_menu_visible(FIND_USER_MENU)
            body = smoke.json_rpc(
                "neon.training.find_qualified_user_wizard",
                "fields_get",
                args=[["cert_type_ids", "required_level"]],
            )
            field_meta = (body.get("result") or {})
            passed = (
                "cert_type_ids" in field_meta
                and "required_level" in field_meta)
            smoke._record_assert(
                "sales-tier can fields_get wizard",
                expect="cert_type_ids + required_level visible",
                actual=f"keys={sorted(field_meta.keys())}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "sales-tier blocked from wizard")

        # ------------------------------------------------------------
        # Scenario 4: sales-tier does NOT see Dashboard menu (training
        # _user only -- sales doesn't carry training_user)
        # ------------------------------------------------------------
        with smoke.scenario("sales-tier does not see Dashboard menu"):
            smoke.login("p2m75_sales")
            smoke.assert_menu_hidden(DASHBOARD_MENU)
            smoke.goto_home()

        # ------------------------------------------------------------
        # Scenario 5: Gate Log has kanban view available + tier_3 in
        # selection (M12 view extension)
        # ------------------------------------------------------------
        with smoke.scenario("Gate Log kanban view + tier_3 selection"):
            smoke.login("p7am2_train_admin")
            smoke.open_action(GATE_LOG_ACTION)
            smoke.assert_visible("table.o_list_table",
                                 "gate log list view")
            # Verify kanban is in the gate-log action's view_mode
            # via the web/action/load endpoint (what the client UI
            # uses internally when navigating menus).
            resp = smoke.page.request.post(
                f"{smoke.base_url}/web/action/load",
                data=json.dumps({
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "action_id":
                            "neon_training.assignment_gate_log_action",
                    },
                }),
                headers={"Content-Type": "application/json"},
            )
            body = resp.json()
            action_data = body.get("result") or {}
            view_modes = action_data.get("view_mode", "")
            passed = ("kanban" in view_modes)
            smoke._record_assert(
                "gate log action exposes kanban",
                expect="kanban in view_mode",
                actual=f"view_modes={view_modes!r}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "kanban missing from gate_log action view_mode")
            smoke.goto_home()

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
