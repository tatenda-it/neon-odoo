"""P7a.M11 browser smoke -- tier 3 wizard surface (3 scenarios).

The action_move_to_in_progress hook + wizard fan-out are
exercised by the Python smoke (T8100-T8121). Browser smoke
covers the rendered surface:

1. Admin opens Gate Log list filtered to tier_3 -- verify the
   tier_3 filter is in the search view selection.
2. Verify the wizard model + 5 fields via fields_get.
3. Verify a crew_leader user can access the wizard model
   (ACL grants jobs.crew_leader + jobs.manager per DP10).
"""

from __future__ import annotations

import sys

from browser_smoke import BrowserSmoke


GATE_LOG_ACTION = "neon_training.assignment_gate_log_action"


def main() -> int:
    with BrowserSmoke("p7a_m11") as smoke:

        # ------------------------------------------------------------
        # Scenario 1: training_admin verifies tier_3 in the selection.
        # ------------------------------------------------------------
        with smoke.scenario("training_admin: Gate Log filter includes tier_3"):
            smoke.login("p7am2_train_admin")
            smoke.open_action(GATE_LOG_ACTION)
            smoke.assert_visible("table.o_list_table",
                                 "gate log list view")
            body = smoke.json_rpc(
                "neon.training.assignment_gate_log",
                "fields_get",
                args=[["gate_tier", "severity"]],
            )
            tier_meta = (body.get("result") or {}).get("gate_tier") or {}
            sel = dict(tier_meta.get("selection") or [])
            passed = (sel.get("tier_3_event_start")
                      == "Tier 3 -- Event Start")
            smoke._record_assert(
                "tier_3_event_start in gate_tier selection",
                expect="Tier 3 -- Event Start",
                actual=sel.get("tier_3_event_start"),
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "tier_3 not present in gate_tier selection")
            smoke.screenshot("admin_gate_log_with_tier3")

        # ------------------------------------------------------------
        # Scenario 2: M11 wizard model + 5 fields via fields_get.
        # ------------------------------------------------------------
        with smoke.scenario("training_admin: M11 wizard model fields present"):
            smoke.login("p7am2_train_admin")
            body = smoke.json_rpc(
                "neon.training.event_start_gate_override_wizard",
                "fields_get",
                args=[["event_job_id", "target_state",
                       "affected_role_line_ids",
                       "affected_summary_html",
                       "override_reason"]],
            )
            field_meta = (body.get("result") or {})
            expected = {"event_job_id", "target_state",
                        "affected_role_line_ids",
                        "affected_summary_html",
                        "override_reason"}
            present = set(field_meta.keys()) & expected
            passed = (present == expected)
            smoke._record_assert(
                "M11 wizard fields present",
                expect=sorted(expected),
                actual=sorted(present),
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "M11 wizard fields missing from fields_get")

        # ------------------------------------------------------------
        # Scenario 3: crew_leader-tier user can fields_get the wizard
        # model. DP10 ACL grants jobs.crew_leader + jobs.manager (NOT
        # finance roles as in M10).
        # ------------------------------------------------------------
        with smoke.scenario("crew_leader-tier user can fields_get M11 wizard"):
            smoke.login("p2m75_lead")
            body = smoke.json_rpc(
                "neon.training.event_start_gate_override_wizard",
                "fields_get",
                args=[["event_job_id", "override_reason"]],
            )
            field_meta = (body.get("result") or {})
            passed = (
                "event_job_id" in field_meta
                and "override_reason" in field_meta)
            smoke._record_assert(
                "crew_leader can fields_get M11 wizard",
                expect="event_job_id + override_reason visible",
                actual=f"keys={sorted(field_meta.keys())}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "crew_leader blocked from M11 wizard fields_get")
            smoke.goto_home()

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
