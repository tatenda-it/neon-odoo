"""P6.M1 browser smoke -- pricing-rule menu & form depth verification.

Counterpart to ``.claude/p6m1_smoke.py`` (ORM-layer): this run verifies
the *rendered* user-facing surface for the four P6.M1 roles. Acts as
the proof-of-concept for the autonomous browser smoke pipeline.

Of the 4 P6.M1 bugs found during manual smoking yesterday:

* Menu parent gating (Bookkeeper couldn't reach Configuration submenu)
  --- caught here by ``assert_menu_visible(menu_neon_finance_pricing_rules)``.
* Wrong XML id on rule list view
  --- caught here by ``open_action`` + ``assert_count("tr.o_data_row", 18)``,
  which fails if the action's tree view can't load.
* App root narrowing (Bookkeeper lost Invoicing app icon)
  --- caught here by the visibility check above (load_web_menus filters
  by group; absence of ``account.menu_finance`` in the tree would
  cascade to the child being invisible too).
* Bookkeeper minimal-role check
  --- caught by the full p2m75_book scenario passing end-to-end.

i.e. 4/4 of yesterday's bugs would have been caught had this smoke
been in place.
"""

from __future__ import annotations

import sys

from browser_smoke import BrowserSmoke


PRICING_RULE_ACTION = "neon_finance.neon_finance_pricing_rule_action"
FINANCE_PARENT_MENU = "neon_finance.menu_neon_finance_config"
PRICING_RULES_MENU = "neon_finance.menu_neon_finance_pricing_rules"
ACCOUNTING_APP_MENU = "account.menu_finance"

EXPECTED_RULE_COUNT = 18         # 9 categories x 2 currencies (USD + ZiG)
EXPECTED_BRACKETS_PER_RULE = 4   # 1-2, 3-7, 8-14, 15-inf


def main() -> int:
    with BrowserSmoke("p6m1") as smoke:

        # --------------------------------------------------------------
        # p2m75_book: reaches Configuration > Finance > Pricing Rules,
        # sees all 18 rules, opens one rule and verifies the bracket
        # notebook tab is populated. Depth principle in action: a green
        # menu visibility check alone would not have caught yesterday's
        # action-broken bugs.
        # --------------------------------------------------------------
        with smoke.scenario("p2m75_book reaches Pricing Rules and rule form (depth)"):
            smoke.login("p2m75_book")
            smoke.assert_menu_visible(PRICING_RULES_MENU)
            smoke.open_action(PRICING_RULE_ACTION)
            smoke.assert_visible("table.o_list_table", "pricing rules list view")
            smoke.assert_count("tr.o_data_row", EXPECTED_RULE_COUNT, "pricing rule row count")
            smoke.screenshot("book_pricing_rules_list")
            smoke.click("tr.o_data_row >> nth=0", name="open first pricing rule")
            smoke.assert_visible("div.o_form_view", "pricing rule form view")
            smoke.assert_visible("[name='bracket_ids']", "brackets one2many container")
            smoke.assert_count(
                "[name='bracket_ids'] tr.o_data_row",
                EXPECTED_BRACKETS_PER_RULE,
                "brackets row count on opened rule",
            )
            smoke.screenshot("book_pricing_rule_form_brackets")

        # --------------------------------------------------------------
        # p2m75_approver: identical depth requirement. Different group
        # gate (group_neon_finance_approver), same expected reach.
        # --------------------------------------------------------------
        with smoke.scenario("p2m75_approver reaches Pricing Rules and rule form (depth)"):
            smoke.login("p2m75_approver")
            smoke.assert_menu_visible(PRICING_RULES_MENU)
            smoke.open_action(PRICING_RULE_ACTION)
            smoke.assert_visible("table.o_list_table", "pricing rules list view")
            smoke.assert_count("tr.o_data_row", EXPECTED_RULE_COUNT, "pricing rule row count")
            smoke.screenshot("approver_pricing_rules_list")
            smoke.click("tr.o_data_row >> nth=0", name="open first pricing rule")
            smoke.assert_visible("div.o_form_view", "pricing rule form view")
            smoke.assert_count(
                "[name='bracket_ids'] tr.o_data_row",
                EXPECTED_BRACKETS_PER_RULE,
                "brackets row count on opened rule",
            )
            smoke.screenshot("approver_pricing_rule_form_brackets")

        # --------------------------------------------------------------
        # p2m75_mgr: operations manager (NOT a finance role). Should
        # reach the Invoicing app (carries neon_jobs_manager which is
        # in the menu_finance groups_id list), but the Finance
        # intermediate menu under Configuration must NOT appear.
        # Negative test --- no depth needed; absence is the evidence.
        # --------------------------------------------------------------
        with smoke.scenario("p2m75_mgr cannot reach Finance submenu (negative)"):
            smoke.login("p2m75_mgr")
            smoke.assert_menu_visible(ACCOUNTING_APP_MENU)  # has neon_jobs_manager
            smoke.assert_menu_hidden(FINANCE_PARENT_MENU)
            smoke.assert_menu_hidden(PRICING_RULES_MENU)
            smoke.goto_home()
            smoke.screenshot("mgr_home_no_finance_submenu")

        # --------------------------------------------------------------
        # p2m75_crew: no finance reach at all. Invoicing app must not
        # show in their launcher AND the underlying model must reject
        # a direct RPC. Single RPC call inside the browser context
        # proves the negative for a UI surface where absence alone is
        # only soft evidence (a hidden menu could still be hit by URL).
        # --------------------------------------------------------------
        with smoke.scenario("p2m75_crew cannot reach Invoicing app + RPC blocked (negative + RPC)"):
            smoke.login("p2m75_crew")
            smoke.assert_menu_hidden(ACCOUNTING_APP_MENU)
            smoke.assert_menu_hidden(PRICING_RULES_MENU)
            smoke.goto_home()
            smoke.screenshot("crew_home_no_invoicing_app")
            smoke.assert_rpc_denied(
                "neon.finance.pricing.rule",
                "search_read",
                "neon.finance.pricing.rule RPC denied for crew",
                args=[[], ["id", "name"]],
            )

    return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
