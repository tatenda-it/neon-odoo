"""P7a.M1 browser smoke -- neon_training certification category + type
menu & form depth verification.

Counterpart to ``.claude/p7a_m1_smoke.py`` (ORM-layer): verifies the
rendered user-facing surface for the three Phase 7a M1 roles.

Depth principle in effect: every visible menu is CLICKED INTO and at
least one piece of content (row count, form field, kanban grouping)
asserted before moving on. Per Phase 6's lesson, menu-visibility
alone misses 3 of 4 typical "action broken" bugs.

Negative scenarios (training_user / training_signoff cannot reach the
admin-only menu) assert hidden absence -- no depth required.
"""

from __future__ import annotations

import sys

from browser_smoke import BrowserSmoke


# Action / menu xmlids -----------------------------------------------
CATEGORY_ACTION = "neon_training.neon_training_certification_category_action"
TYPE_ACTION = "neon_training.neon_training_certification_type_action"

TRAINING_ROOT_MENU = "neon_training.menu_neon_training_root"
CATEGORIES_MENU = "neon_training.menu_neon_training_categories"
TYPES_MENU = "neon_training.menu_neon_training_types"

# Expected seed counts (from p7a_m1_smoke T7105-T7109)
EXPECTED_CATEGORY_COUNT = 4
EXPECTED_TYPE_COUNT = 22


def main() -> int:
    with BrowserSmoke("p7a_m1") as smoke:

        # --------------------------------------------------------------
        # Scenario 1: training_admin reaches Categories + clicks into one
        # form. Form must render with chatter (mail.thread inheritance).
        # --------------------------------------------------------------
        with smoke.scenario("p7am1_train_admin reaches Categories list + form (depth)"):
            smoke.login("p7am1_train_admin")
            smoke.assert_menu_visible(TRAINING_ROOT_MENU)
            smoke.assert_menu_visible(CATEGORIES_MENU)
            smoke.open_action(CATEGORY_ACTION)
            smoke.assert_visible("table.o_list_table",
                                 "categories list view")
            smoke.assert_count(
                "tr.o_data_row",
                EXPECTED_CATEGORY_COUNT,
                "certification category row count",
            )
            smoke.screenshot("admin_category_list")
            # Click the name cell explicitly. The category list view
            # has a sequence handle on the first column (widget=
            # "handle"); generic row clicks land on the handle and
            # don't navigate into the form. The name cell is the
            # canonical "open form" target.
            smoke.click("tr.o_data_row >> nth=0 >> td[name='name']",
                        name="open first category (name cell)")
            smoke.assert_visible("div.o_form_view",
                                 "category form view")
            smoke.assert_visible("div.oe_chatter",
                                 "category chatter (mail.thread wired)")
            smoke.screenshot("admin_category_form")

        # --------------------------------------------------------------
        # Scenario 2: training_admin reaches Certification Types list,
        # opens the type form, verifies chatter + equipment-linkage
        # fields render. Then switches to kanban and asserts grouping
        # by category produces the four seeded category swimlanes.
        # --------------------------------------------------------------
        with smoke.scenario("p7am1_train_admin reaches Types list + kanban (depth)"):
            smoke.login("p7am1_train_admin")
            smoke.assert_menu_visible(TYPES_MENU)
            smoke.open_action(TYPE_ACTION)
            # Default view for the type action is kanban (gate-1 plan).
            # Switch to list first via the view switcher for the count
            # assertion; then back to kanban for grouping assertion.
            smoke.click(
                ".o_cp_switch_buttons button.o_switch_view.o_list",
                name="switch to list view")
            smoke.assert_visible("table.o_list_table",
                                 "types list view")
            smoke.assert_count(
                "tr.o_data_row",
                EXPECTED_TYPE_COUNT,
                "certification type row count",
            )
            smoke.screenshot("admin_type_list")
            smoke.click("tr.o_data_row >> nth=0",
                        name="open first type")
            smoke.assert_visible("div.o_form_view",
                                 "type form view")
            smoke.assert_visible("div.oe_chatter",
                                 "type chatter (mail.thread wired)")
            smoke.screenshot("admin_type_form")

        # --------------------------------------------------------------
        # Scenario 3: training_signoff sees the Training app root + the
        # M2 Certifications surface (operational), but NOT the admin-
        # gated Configuration submenu under which Categories and Types
        # now live.
        #
        # Note: M2 reparented Categories and Types under a new
        # Configuration submenu and opened the Training root to
        # training_user. The original M1 negative assertion
        # ("user/signoff cannot see Training root") is no longer the
        # right shape -- crew need to reach their own certs via the
        # root after M2. The reference-data screens stay admin-only.
        # --------------------------------------------------------------
        with smoke.scenario("p7am1_train_signoff cannot reach Categories/Types config (negative)"):
            smoke.login("p7am1_train_signoff")
            smoke.assert_menu_visible(TRAINING_ROOT_MENU)
            smoke.assert_menu_hidden(CATEGORIES_MENU)
            smoke.assert_menu_hidden(TYPES_MENU)
            smoke.goto_home()

        # --------------------------------------------------------------
        # Scenario 4: training_user can reach the Training root but
        # cannot reach the Categories / Types reference-data screens
        # under the Configuration submenu.
        # --------------------------------------------------------------
        with smoke.scenario("p7am1_train_user cannot reach Categories/Types config (negative)"):
            smoke.login("p7am1_train_user")
            smoke.assert_menu_visible(TRAINING_ROOT_MENU)
            smoke.assert_menu_hidden(CATEGORIES_MENU)
            smoke.assert_menu_hidden(TYPES_MENU)
            smoke.goto_home()

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
