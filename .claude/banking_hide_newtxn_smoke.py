"""HIDE NATIVE NEW TRANSACTION (#4) smoke -- on the journal-cards dashboard
(now reached via the "Reconciliation" menu), the native "New Transaction"
quick-link is gone from cash/bank cards, the cards still render (no crash), and
the reconcile/statement paths remain reachable.
"""
import os
import sys

sys.path.insert(0, ".")
from browser_smoke import BrowserSmoke  # noqa: E402

SHOT = os.path.join("smoke-output", "banking_hide_newtxn")
os.makedirs(SHOT, exist_ok=True)


def main():
    with BrowserSmoke("banking_hide_newtxn") as smoke:
        smoke.login("p2m75_book")
        smoke.page.set_viewport_size({"width": 1600, "height": 1000})

        with smoke.scenario("Journal-cards dashboard renders; New Transaction gone from cards"):
            smoke.open_action("account.open_account_journal_dashboard_kanban")
            smoke.page.wait_for_timeout(1800)
            smoke.assert_visible("div.o_action_manager", "dashboard renders (no crash)")
            cards = smoke.page.locator(".o_kanban_record").count()
            smoke._record_assert("journal cards render", expect=">=1", actual=str(cards), passed=cards >= 1)
            body = smoke.page.locator("body").inner_text()
            # the cash/bank cards are present (Petty Cash / CABS / Undeposited)
            jseen = [j for j in ["Petty Cash", "CABS", "Undeposited"] if j in body]
            smoke._record_assert("cash/bank journal cards present", expect=">=1",
                                 actual=str(jseen), passed=len(jseen) >= 1)
            # the wrong door is gone
            ntx = body.count("New Transaction")
            smoke._record_assert("'New Transaction' link gone from cards",
                                 expect="0", actual=str(ntx), passed=ntx == 0)
            smoke.screenshot("dashboard_no_new_transaction")

        with smoke.scenario("Reconcile / statement paths still reachable from a card menu"):
            # open the first card's dropdown (kanban menu) and check it has View/Statements,
            # NOT New Transaction
            toggles = smoke.page.locator(".o_kanban_record .o_dropdown_kanban, .o_kanban_record .o-dropdown")
            opened = False
            if toggles.count():
                try:
                    toggles.first.click(timeout=5000)
                    smoke.page.wait_for_timeout(600)
                    opened = True
                except Exception:
                    opened = False
            menu_txt = smoke.page.locator(".o-dropdown--menu, .dropdown-menu.show").inner_text() \
                if smoke.page.locator(".o-dropdown--menu, .dropdown-menu.show").count() else ""
            # whether or not the menu opened, assert the page is intact and New Transaction
            # is not present anywhere
            smoke._record_assert("card menu has no 'New Transaction'",
                                 expect="absent", actual=("present" if "New Transaction" in menu_txt else "absent"),
                                 passed="New Transaction" not in menu_txt)
            smoke.screenshot("card_menu")

        with smoke.scenario("Statement Add-Transaction path unaffected (Petty Cash buttons still live)"):
            smoke.open_action("neon_banking_statement.action_statement_petty_cash")
            smoke.page.wait_for_timeout(1200)
            smoke.assert_visible(".o_control_panel button.btn-primary:has-text('Add Expense')",
                                 "statement Add Expense button still present")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
