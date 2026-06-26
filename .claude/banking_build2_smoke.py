"""BUILD 2 smoke -- Account Ledgers landing index + clickable breadcrumb +
Suspense hidden. Navigation only. Verified as the bookkeeper on prod-matching dev.
"""
import os
import sys

sys.path.insert(0, ".")
from browser_smoke import BrowserSmoke  # noqa: E402

SHOT = os.path.join("smoke-output", "banking_build2")
os.makedirs(SHOT, exist_ok=True)
TOGGLER = ".o_control_panel button.btn-primary.o_neon_add_txn"


def main():
    with BrowserSmoke("banking_build2") as smoke:
        smoke.login("p2m75_book")
        smoke.page.set_viewport_size({"width": 1600, "height": 1000})

        with smoke.scenario("Account Ledgers opens a landing of the 3 cash statements (no Suspense)"):
            smoke.open_action("neon_banking_statement.action_account_ledgers_index")
            smoke.page.wait_for_timeout(1500)
            smoke.assert_visible("div.o_action_manager", "landing renders")
            cards = smoke.page.locator(".o_kanban_record:not(.o_kanban_ghost)").count()
            smoke._record_assert("landing shows 3 cash cards", expect="3", actual=str(cards), passed=cards == 3)
            body = smoke.page.locator("body").inner_text()
            for j in ["Petty Cash", "CABS (USD)", "CABS (ZWG)"]:
                smoke._record_assert("landing card present: %s" % j, expect="present",
                                     actual=("yes" if j in body else "no"), passed=j in body)
            smoke._record_assert("Suspense NOT on the landing", expect="absent",
                                 actual=("present" if "Suspense" in body else "absent"),
                                 passed="Suspense" not in body)
            smoke.screenshot("account_ledgers_landing")

        with smoke.scenario("Drill into Petty Cash -> clickable 'Account Ledgers' breadcrumb + dropdown works"):
            smoke.page.locator(".o_kanban_record:has-text('Petty Cash') button:has-text('Open Statement')").first.click()
            smoke.page.wait_for_timeout(1500)
            smoke.assert_visible("div.o_action_manager", "statement renders after drill")
            crumb = smoke.page.locator(".o_breadcrumb, .breadcrumb").first.inner_text()
            smoke._record_assert("breadcrumb shows 'Account Ledgers' parent", expect="present",
                                 actual=("yes" if "Account Ledgers" in crumb else crumb[:60]),
                                 passed="Account Ledgers" in crumb)
            smoke._record_assert("breadcrumb shows the statement", expect="present",
                                 actual=("yes" if "Petty Cash" in crumb else crumb[:60]),
                                 passed="Petty Cash" in crumb)
            # the parent crumb is clickable (an <a>/button, not the active leaf)
            clickable = smoke.page.locator(".o_breadcrumb a:has-text('Account Ledgers'), "
                                           ".breadcrumb-item a:has-text('Account Ledgers')").count()
            smoke._record_assert("'Account Ledgers' crumb is clickable", expect=">=1",
                                 actual=str(clickable), passed=clickable >= 1)
            # the Add-Transaction dropdown still works on the drilled statement
            smoke.assert_visible(TOGGLER, "Add Transaction dropdown present on drilled statement")
            smoke.screenshot("petty_drilled_breadcrumb")

        with smoke.scenario("Clicking the 'Account Ledgers' crumb returns to the landing"):
            smoke.page.locator(".o_breadcrumb a:has-text('Account Ledgers'), "
                               ".breadcrumb-item a:has-text('Account Ledgers')").first.click()
            smoke.page.wait_for_timeout(1200)
            cards = smoke.page.locator(".o_kanban_record:not(.o_kanban_ghost)").count()
            smoke._record_assert("back at the landing (3 cards)", expect="3", actual=str(cards), passed=cards == 3)

        with smoke.scenario("Suspense statement is gone from the menu tree"):
            menus = smoke._load_web_menus()
            names = [m.get("name") for m in menus.values()]
            # no 'Suspense' statement menu item anywhere
            smoke._record_assert("no 'Suspense' menu item", expect="absent",
                                 actual=("present" if "Suspense" in names else "absent"),
                                 passed="Suspense" not in names)

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
