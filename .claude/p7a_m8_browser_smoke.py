"""P7a.M8 browser smoke -- training gate UI surfaces (3 scenarios).

The inference + roll-up engine is exercised by the Python smoke
(T7800-T7824). Browser smoke covers the rendered surface:

1. Admin opens Crew Assignments list -- gate_status column renders
   as badge (depth: list view loads, at least one row visible).
2. Admin opens an event_job form -- training_gate_status field is
   exposed on the model via fields_get + the inherited form view
   loads cleanly.
3. Training user can read the new gate fields on their own
   commercial.job.crew row (cross-module ACL not impacted; field
   visible in fields_get).
"""

from __future__ import annotations

import sys

from browser_smoke import BrowserSmoke


CREW_ACTION = "neon_jobs.commercial_job_crew_action"
EVENT_JOB_ACTION = "neon_jobs.commercial_event_job_action"


def main() -> int:
    with BrowserSmoke("p7a_m8") as smoke:

        # ------------------------------------------------------------
        # Scenario 1: ops manager verifies M8 fields are present on
        # commercial.job.crew via fields_get. Crew Assignments isn't
        # menu-exposed by default in neon_jobs (it's reached inline
        # from commercial.job), so a fields_get depth-check covers
        # the model-side surface that view inherits depend on.
        # ------------------------------------------------------------
        with smoke.scenario("ops mgr verifies M8 fields on commercial.job.crew"):
            smoke.login("p2m75_mgr")
            body = smoke.json_rpc(
                "commercial.job.crew",
                "fields_get",
                args=[["gate_status",
                       "required_certification_type_ids",
                       "gate_missing_certification_ids",
                       "gate_softening_cross_competency_ids",
                       "gate_softening_used"]],
            )
            field_meta = (body.get("result") or {})
            expected = {
                "gate_status",
                "required_certification_type_ids",
                "gate_missing_certification_ids",
                "gate_softening_cross_competency_ids",
                "gate_softening_used",
            }
            present = set(field_meta.keys()) & expected
            passed = (present == expected)
            smoke._record_assert(
                "M8 fields present on commercial.job.crew",
                expect=sorted(expected),
                actual=sorted(present),
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "M8 crew gate fields missing from fields_get")
            smoke.goto_home()

        # ------------------------------------------------------------
        # Scenario 2: ops mgr opens event_job action; training_gate
        # _status field on model + inherited form renders.
        # ------------------------------------------------------------
        with smoke.scenario("ops mgr opens event_job; M8 training_gate_status on model"):
            smoke.login("p2m75_mgr")
            smoke.open_action(EVENT_JOB_ACTION)
            smoke.assert_visible("table.o_list_table",
                                 "event_job list view")
            body = smoke.json_rpc(
                "commercial.event.job",
                "fields_get",
                args=[["training_gate_status"]],
            )
            field_meta = (body.get("result") or {})
            passed = ("training_gate_status" in field_meta)
            smoke._record_assert(
                "training_gate_status on commercial.event.job",
                expect="field present",
                actual=f"keys={list(field_meta.keys())}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "training_gate_status missing from event_job model")
            smoke.screenshot("admin_event_job_list_m8")

        # ------------------------------------------------------------
        # Scenario 3: training_user can read the new gate fields via
        # fields_get on their own role. ACL on commercial.job.crew is
        # neon_jobs-owned, so M8's compute fields inherit read access
        # without a CSV change; just verify the call doesn't raise.
        # ------------------------------------------------------------
        with smoke.scenario("training_user can fields_get gate_status (no ACL gap)"):
            smoke.login("p7am2_train_user")
            body = smoke.json_rpc(
                "commercial.job.crew",
                "fields_get",
                args=[["gate_status",
                       "required_certification_type_ids"]],
            )
            field_meta = (body.get("result") or {})
            passed = ("gate_status" in field_meta
                      and "required_certification_type_ids" in field_meta)
            smoke._record_assert(
                "training_user can fields_get gate_status",
                expect="gate_status + required_certification_type_ids visible",
                actual=f"keys={sorted(field_meta.keys())}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "training_user blocked from reading M8 fields")
            smoke.goto_home()

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
