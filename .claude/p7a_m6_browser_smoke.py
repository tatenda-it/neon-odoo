"""P7a.M6 browser smoke -- cross-competency surface verification (3 scenarios).

The model behaviour + TODO surface mechanics are verified by the
Python smoke (T7600-T7621). Browser smoke covers the rendered
surface:

1. Signoff user reaches Training -> Cross-Competencies; list/
   kanban renders.
2. Signoff opens a New form; key field labels present (event,
   observation, performance rating).
3. Training_user does NOT see the Cross-Competencies menu
   (admin/signoff-only per menu groups).
"""

from __future__ import annotations

import sys

from browser_smoke import BrowserSmoke


CROSS_COMPETENCIES_ACTION = (
    "neon_training.neon_training_cross_competency_action")
CROSS_COMPETENCIES_MENU = (
    "neon_training.menu_neon_training_cross_competencies")
TRAINING_ROOT_MENU = "neon_training.menu_neon_training_root"


def main() -> int:
    with BrowserSmoke("p7a_m6") as smoke:

        # ------------------------------------------------------------
        # Scenario 1: signoff reaches Cross-Competencies list.
        # ------------------------------------------------------------
        with smoke.scenario("signoff reaches Cross-Competencies list"):
            smoke.login("p7am2_train_signoff")
            smoke.assert_menu_visible(TRAINING_ROOT_MENU)
            smoke.assert_menu_visible(CROSS_COMPETENCIES_MENU)
            smoke.open_action(CROSS_COMPETENCIES_ACTION)
            smoke.click(
                ".o_cp_switch_buttons button.o_switch_view.o_list",
                name="switch to list view")
            smoke.assert_visible("table.o_list_table",
                                 "cross-competencies list view")
            smoke.screenshot("signoff_cross_competency_list")

        # ------------------------------------------------------------
        # Scenario 2: signoff opens New cross-competency form; key
        # fields present.
        # ------------------------------------------------------------
        with smoke.scenario("signoff opens New cross-competency form"):
            smoke.login("p7am2_train_signoff")
            smoke.open_action(CROSS_COMPETENCIES_ACTION)
            smoke.click(
                ".o_cp_switch_buttons button.o_switch_view.o_list",
                name="switch to list view")
            smoke.page.locator(".o_list_button_add:visible").first.click(
                timeout=5_000)
            smoke._record_assert(
                "open New cross-competency form",
                expect="clickable", actual="clicked", passed=True)
            smoke.assert_visible("div.o_form_view",
                                 "cross-competency form view (new)")
            smoke.assert_visible(
                "div.o_field_widget[name='user_id']",
                "user_id field rendered")
            smoke.assert_visible(
                "div.o_field_widget[name='certification_type_id']",
                "certification_type_id field rendered")
            smoke.assert_visible(
                "div.o_field_widget[name='demonstrated_through_event_id']",
                "demonstrated_through_event_id field rendered")
            smoke.assert_visible(
                "div.o_field_widget[name='performance_rating']",
                "performance_rating field rendered")
            smoke.assert_visible("div.oe_chatter",
                                 "chatter rendered (mail.thread)")
            smoke.screenshot("signoff_cross_competency_form_new")
            smoke.page.goto(f"{smoke.base_url}/web",
                            wait_until="networkidle")

        # ------------------------------------------------------------
        # Scenario 3: training_user CANNOT see Cross-Competencies
        # menu. Crew see their own via portal (Phase 7b), not via
        # the admin backend menu.
        # ------------------------------------------------------------
        with smoke.scenario("training_user cannot see Cross-Competencies menu (negative)"):
            smoke.login("p7am2_train_user")
            smoke.assert_menu_visible(TRAINING_ROOT_MENU)
            smoke.assert_menu_hidden(CROSS_COMPETENCIES_MENU)
            smoke.goto_home()

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
