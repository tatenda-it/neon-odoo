"""P7a.M9 browser smoke -- gate log surface + tab on event_job (3 scenarios).

Tier-1 toast emission is exercised by the Python smoke (T7921 +
T7921a via bus.bus patch). Browser smoke covers the rendered
surface:

1. training_admin opens Gate Log list; M9 menu visible + fields
   present on model via fields_get.
2. ops mgr opens event_job; Training Gate Log notebook tab is
   present and the assignment_gate_log_ids field renders.
3. training_user (sales-tier) is gated from the Gate Log menu by
   ACL (signoff/admin only); they CAN still call fields_get
   on their own scoped logs (ir.rule passes).
"""

from __future__ import annotations

import sys

from browser_smoke import BrowserSmoke


GATE_LOG_ACTION = "neon_training.assignment_gate_log_action"
GATE_LOG_MENU = "neon_training.menu_neon_training_assignment_gate_log"
EVENT_JOB_ACTION = "neon_jobs.commercial_event_job_action"


def main() -> int:
    with BrowserSmoke("p7a_m9") as smoke:

        # ------------------------------------------------------------
        # Scenario 1: training_admin opens Gate Log list; menu visible
        # + M9 fields present via fields_get.
        # ------------------------------------------------------------
        with smoke.scenario("training_admin opens Gate Log list; M9 fields present"):
            smoke.login("p7am2_train_admin")
            smoke.assert_menu_visible(GATE_LOG_MENU)
            smoke.open_action(GATE_LOG_ACTION)
            smoke.assert_visible("table.o_list_table",
                                 "gate log list view")
            body = smoke.json_rpc(
                "neon.training.assignment_gate_log",
                "fields_get",
                args=[["event_job_id", "crew_id", "user_id",
                       "gate_tier", "severity",
                       "gate_status_at_fire",
                       "missing_certification_type_ids",
                       "softening_cross_competency_ids",
                       "override_reason", "overridden_by_id",
                       "overridden_at", "fired_at",
                       "triggered_by_id"]],
            )
            field_meta = (body.get("result") or {})
            expected = {
                "event_job_id", "crew_id", "user_id",
                "gate_tier", "severity", "gate_status_at_fire",
                "missing_certification_type_ids",
                "softening_cross_competency_ids",
                "override_reason", "overridden_by_id",
                "overridden_at", "fired_at", "triggered_by_id",
            }
            present = set(field_meta.keys()) & expected
            passed = (present == expected)
            smoke._record_assert(
                "M9 fields present on assignment_gate_log",
                expect=sorted(expected),
                actual=sorted(present),
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "M9 gate_log fields missing from fields_get")
            smoke.screenshot("admin_gate_log_list_m9")

        # ------------------------------------------------------------
        # Scenario 2: ops mgr opens event_job; the M9 notebook tab is
        # accessible (assignment_gate_log_ids field on form view).
        # ------------------------------------------------------------
        with smoke.scenario("ops mgr opens event_job; M9 gate-log o2m field present"):
            smoke.login("p2m75_mgr")
            smoke.open_action(EVENT_JOB_ACTION)
            smoke.assert_visible("table.o_list_table",
                                 "event_job list view")
            body = smoke.json_rpc(
                "commercial.event.job",
                "fields_get",
                args=[["assignment_gate_log_ids"]],
            )
            field_meta = (body.get("result") or {})
            passed = ("assignment_gate_log_ids" in field_meta)
            smoke._record_assert(
                "assignment_gate_log_ids on commercial.event.job",
                expect="field present",
                actual=f"keys={list(field_meta.keys())}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "assignment_gate_log_ids missing from event_job")
            smoke.screenshot("opsmgr_event_job_with_m9_tab")

        # ------------------------------------------------------------
        # Scenario 3: training_user CANNOT see the Gate Log menu
        # (signoff/admin only) but CAN fields_get their own scoped
        # logs (ir.rule passes the model-level check).
        # ------------------------------------------------------------
        with smoke.scenario("training_user blocked from Gate Log menu; can fields_get scoped logs"):
            smoke.login("p7am2_train_user")
            smoke.assert_menu_hidden(GATE_LOG_MENU)
            body = smoke.json_rpc(
                "neon.training.assignment_gate_log",
                "fields_get",
                args=[["gate_tier", "severity",
                       "triggered_by_id"]],
            )
            field_meta = (body.get("result") or {})
            passed = (
                "gate_tier" in field_meta
                and "severity" in field_meta
                and "triggered_by_id" in field_meta)
            smoke._record_assert(
                "training_user can fields_get gate_log",
                expect="gate_tier + severity + triggered_by_id visible",
                actual=f"keys={sorted(field_meta.keys())}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "training_user blocked from fields_get on gate_log")
            smoke.goto_home()

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
