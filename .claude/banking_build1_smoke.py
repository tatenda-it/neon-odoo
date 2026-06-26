"""BUILD 1 smoke -- UI bundle: (1) Add-Transaction dropdown, (2) Accounting
rename, (3) Reporting link. Verified as the bookkeeper on the prod-matching dev.
"""
import os
import sys

sys.path.insert(0, ".")
from browser_smoke import BrowserSmoke  # noqa: E402

SHOT = os.path.join("smoke-output", "banking_build1")
os.makedirs(SHOT, exist_ok=True)

# the visible toggler is btn-primary; a hidden small-screen twin (btn-link
# dropdown-item) also carries o_neon_add_txn -> qualify with btn-primary.
TOGGLER = ".o_control_panel button.btn-primary.o_neon_add_txn"
MENU = ".o-dropdown--menu, .dropdown-menu.show"


def main():
    with BrowserSmoke("banking_build1") as smoke:
        smoke.login("p2m75_book")
        smoke.page.set_viewport_size({"width": 1600, "height": 1000})

        # PART 1 -- one dropdown replaces the inline button row
        with smoke.scenario("Part1: ONE 'Add Transaction' dropdown on Petty Cash (no inline button row)"):
            smoke.open_action("neon_banking_statement.action_statement_petty_cash")
            smoke.page.wait_for_timeout(1500)
            smoke.assert_visible("div.o_action_manager", "statement renders (OWL view ok)")
            smoke.assert_visible(TOGGLER, "Add Transaction dropdown toggler visible (no row selection)")
            # the old always-buttons row is gone: no standalone btn-primary 'Add Expense'
            old = smoke.page.locator(".o_control_panel button.btn-primary:has-text('Add Expense')").count()
            smoke._record_assert("old inline 'Add Expense' button gone", expect="0", actual=str(old), passed=old == 0)
            # open the dropdown
            smoke.page.locator(TOGGLER).first.click()
            smoke.page.wait_for_timeout(500)
            menu_txt = smoke.page.locator(MENU).first.inner_text() if smoke.page.locator(MENU).count() else ""
            for item in ["Add Expense", "Add Replenishment", "Drawings", "Commission", "Money In", "Transfer / Deposit"]:
                smoke._record_assert("Petty dropdown item: %s" % item, expect="present",
                                     actual=("yes" if item in menu_txt else "no"), passed=item in menu_txt)
            smoke.screenshot("petty_dropdown_open")
            # an item opens the wizard
            smoke.page.locator("%s .dropdown-item:has-text('Add Expense'), %s a:has-text('Add Expense')" % (MENU, MENU)).first.click()
            smoke.page.wait_for_timeout(800)
            smoke.assert_visible(".modal .o_form_view", "dropdown item opens the Add Expense wizard")
            smoke.page.locator(".modal footer button:has-text('Cancel')").first.click()
            smoke.page.wait_for_timeout(400)

        with smoke.scenario("Part1: CABS USD dropdown shows the bank set"):
            smoke.open_action("neon_banking_statement.action_statement_cabs_usd")
            smoke.page.wait_for_timeout(1200)
            smoke.assert_visible(TOGGLER, "CABS USD dropdown toggler visible")
            smoke.page.locator(TOGGLER).first.click()
            smoke.page.wait_for_timeout(500)
            menu_txt = smoke.page.locator(MENU).first.inner_text() if smoke.page.locator(MENU).count() else ""
            for item in ["Pay a Bill", "Receive a Payment", "Vendor Advance"]:
                smoke._record_assert("CABS USD dropdown item: %s" % item, expect="present",
                                     actual=("yes" if item in menu_txt else "no"), passed=item in menu_txt)
            smoke._record_assert("CABS USD has NO 'Add Replenishment' (petty-only)",
                                 expect="absent", actual=("present" if "Add Replenishment" in menu_txt else "absent"),
                                 passed="Add Replenishment" not in menu_txt)
            smoke.screenshot("cabs_usd_dropdown_open")

        # PART 2 -- Invoicing -> Accounting
        with smoke.scenario("Part2: app root reads 'Accounting' (not 'Invoicing')"):
            menus = smoke._load_web_menus()
            roots = {m["id"]: m for m in menus.values()}
            top_names = [roots.get(mid, {}).get("name") for mid in menus.get("root", {}).get("children", [])]
            smoke._record_assert("'Accounting' top-level app present", expect="present",
                                 actual=str("Accounting" in top_names), passed="Accounting" in top_names)
            smoke._record_assert("'Invoicing' top-level app gone (renamed)", expect="absent",
                                 actual=str("Invoicing" in top_names), passed="Invoicing" not in top_names)

        # PART 3 -- Reporting link
        with smoke.scenario("Part3: 'Reporting' top-level present + opens a report"):
            menus = smoke._load_web_menus()
            roots = {m["id"]: m for m in menus.values()}
            top_names = [roots.get(mid, {}).get("name") for mid in menus.get("root", {}).get("children", [])]
            smoke._record_assert("'Reporting' top-level present", expect="present",
                                 actual=str("Reporting" in top_names), passed="Reporting" in top_names)
            smoke.open_action("account_financial_report.action_trial_balance_wizard")
            smoke.page.wait_for_timeout(1200)
            smoke.assert_visible(".o_form_view, .modal .o_form_view", "Trial Balance report wizard opens")
            smoke.screenshot("reporting_trial_balance")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
