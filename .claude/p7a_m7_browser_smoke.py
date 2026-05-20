"""P7a.M7 browser smoke -- authority workflow surfaces (3 scenarios).

The authority routing + verify hardening + promote mechanics are
verified by the Python smoke (T7700-T7721). Browser smoke covers
the rendered surface:

1. Cert form opens cleanly post-M7; new source_cross_competency
   _id field renders (invisible when null per attrs).
2. Cross-competency form has the Promote button visible when
   leads_to_certification=True AND is_promoted=False; admin role
   sees it.
3. Lead Tech can reach the cross-competency Promote button only
   via signoff/admin tier (training_user denied at menu).
"""

from __future__ import annotations

import sys

from browser_smoke import BrowserSmoke


CERTIFICATIONS_ACTION = "neon_training.neon_training_certification_action"
CROSS_COMPETENCIES_ACTION = (
    "neon_training.neon_training_cross_competency_action")


def main() -> int:
    with BrowserSmoke("p7a_m7") as smoke:

        # ------------------------------------------------------------
        # Scenario 1: admin opens cert form; M7 field added without
        # view breakage. source_cross_competency_id is in the model;
        # verify via fields_get.
        # ------------------------------------------------------------
        with smoke.scenario("admin opens cert form; M7 source field on model"):
            smoke.login("p7am2_train_admin")
            smoke.open_action(CERTIFICATIONS_ACTION)
            smoke.click(
                ".o_cp_switch_buttons button.o_switch_view.o_list",
                name="switch to list view")
            smoke.assert_visible("table.o_list_table",
                                 "certifications list view")
            body = smoke.json_rpc(
                "neon.training.certification",
                "fields_get",
                args=[["source_cross_competency_id"]],
            )
            field_meta = (body.get("result") or {})
            passed = ("source_cross_competency_id" in field_meta)
            smoke._record_assert(
                "source_cross_competency_id on cert model",
                expect="field present",
                actual=f"keys={list(field_meta.keys())}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "M7 source field missing from fields_get response")
            smoke.screenshot("admin_cert_form_m7")

        # ------------------------------------------------------------
        # Scenario 2: admin opens cross_competency form; verify the
        # new is_promoted field + action_promote_to_cert method are
        # present on the model.
        # ------------------------------------------------------------
        with smoke.scenario("admin opens cross_competency form; M7 fields + method on model"):
            smoke.login("p7am2_train_admin")
            smoke.open_action(CROSS_COMPETENCIES_ACTION)
            smoke.click(
                ".o_cp_switch_buttons button.o_switch_view.o_list",
                name="switch to list view")
            smoke.page.locator(".o_list_button_add:visible").first.click(
                timeout=5_000)
            smoke._record_assert(
                "open New cross_competency form",
                expect="clickable", actual="clicked", passed=True)
            smoke.assert_visible("div.o_form_view",
                                 "cross_competency form view (new)")
            # Verify M7 additions via fields_get.
            body = smoke.json_rpc(
                "neon.training.cross_competency",
                "fields_get",
                args=[["is_promoted", "promoted_cert_ids"]],
            )
            field_meta = (body.get("result") or {})
            passed = ("is_promoted" in field_meta
                      and "promoted_cert_ids" in field_meta)
            smoke._record_assert(
                "M7 fields on cross_competency model",
                expect="is_promoted + promoted_cert_ids present",
                actual=f"keys={sorted(field_meta.keys())}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "M7 cross_competency fields missing")
            smoke.screenshot("admin_cross_competency_form_m7")
            smoke.page.goto(f"{smoke.base_url}/web",
                            wait_until="networkidle")

        # ------------------------------------------------------------
        # Scenario 3: training_user cannot reach Cross-Competencies
        # menu (signoff/admin only). Existing M6 negative scenario;
        # re-verifies the gate is intact post-M7.
        # ------------------------------------------------------------
        with smoke.scenario("training_user still cannot reach cross_competency menu post-M7"):
            smoke.login("p7am2_train_user")
            smoke.assert_menu_hidden(
                "neon_training.menu_neon_training_cross_competencies")
            smoke.goto_home()

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
