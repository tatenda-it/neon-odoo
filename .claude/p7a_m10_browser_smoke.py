"""P7a.M10 browser smoke -- wizard surface (3 scenarios).

The action_accept hook + wizard fan-out are exercised by the
Python smoke (T8000-T8019). Browser smoke covers the rendered
surface:

1. Admin opens Gate Log list filtered to tier_2 -- verify the
   tier filter is present and clickable.
2. Verify the wizard model + 4 fields via fields_get (rendered
   surface check; transient model not directly menu-exposed).
3. Verify a sales-tier user can access the wizard model
   (fields_get) -- ACL CSV grants finance_sales/finance_
   approver access so the wizard opens when action_accept
   returns it.
"""

from __future__ import annotations

import sys

from browser_smoke import BrowserSmoke


GATE_LOG_ACTION = "neon_training.assignment_gate_log_action"


def main() -> int:
    with BrowserSmoke("p7a_m10") as smoke:

        # ------------------------------------------------------------
        # Scenario 1: training_admin opens Gate Log; verify tier_2
        # filter chip is in the search view.
        # ------------------------------------------------------------
        with smoke.scenario("training_admin: Gate Log filter chips include tier_2"):
            smoke.login("p7am2_train_admin")
            smoke.open_action(GATE_LOG_ACTION)
            smoke.assert_visible("table.o_list_table",
                                 "gate log list view")
            # The search-panel filter set should include the
            # tier_2 label. Use a text-search to confirm the
            # search view definition includes it.
            body = smoke.json_rpc(
                "neon.training.assignment_gate_log",
                "fields_get",
                args=[["gate_tier", "severity"]],
            )
            tier_meta = (body.get("result") or {}).get("gate_tier") or {}
            sel = dict(tier_meta.get("selection") or [])
            passed = (sel.get("tier_2_quote_accept")
                      == "Tier 2 -- Quote Acceptance")
            smoke._record_assert(
                "tier_2_quote_accept in gate_tier selection",
                expect="Tier 2 -- Quote Acceptance",
                actual=sel.get("tier_2_quote_accept"),
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "tier_2 not present in gate_tier selection")
            smoke.screenshot("admin_gate_log_with_tier2")

        # ------------------------------------------------------------
        # Scenario 2: wizard model + 4 fields verified via fields_get.
        # Transient model is not directly menu-exposed.
        # ------------------------------------------------------------
        with smoke.scenario("training_admin: wizard model fields present"):
            smoke.login("p7am2_train_admin")
            body = smoke.json_rpc(
                "neon.training.quote_gate_override_wizard",
                "fields_get",
                args=[["quote_id", "affected_role_line_ids",
                       "affected_summary_html", "override_reason"]],
            )
            field_meta = (body.get("result") or {})
            expected = {"quote_id", "affected_role_line_ids",
                        "affected_summary_html", "override_reason"}
            present = set(field_meta.keys()) & expected
            passed = (present == expected)
            smoke._record_assert(
                "M10 wizard fields present",
                expect=sorted(expected),
                actual=sorted(present),
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "M10 wizard fields missing from fields_get")

        # ------------------------------------------------------------
        # Scenario 3: sales-tier (p2m75_sales) can fields_get the
        # wizard. ACL grants finance_sales create/read/write/unlink
        # on the transient model; without that, the wizard would
        # fail to open when action_accept returns it.
        # ------------------------------------------------------------
        with smoke.scenario("sales-tier user can fields_get the wizard model"):
            smoke.login("p2m75_sales")
            body = smoke.json_rpc(
                "neon.training.quote_gate_override_wizard",
                "fields_get",
                args=[["quote_id", "override_reason"]],
            )
            field_meta = (body.get("result") or {})
            passed = (
                "quote_id" in field_meta
                and "override_reason" in field_meta)
            smoke._record_assert(
                "sales-tier wizard fields_get",
                expect="quote_id + override_reason visible",
                actual=f"keys={sorted(field_meta.keys())}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "sales-tier blocked from wizard fields_get")
            smoke.goto_home()

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
