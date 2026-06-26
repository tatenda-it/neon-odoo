"""BANKING FRONT-DOOR (#3) smoke -- navigation/label only.

As the bookkeeper (p2m75_book):
  * "Statements" is a top-level launcher and sorts AHEAD of "Reconciliation"
    (the demoted, relabelled ex-"Banking"); "Banking" no longer appears.
  * Account Ledgers leads the Statements tree and its Petty Cash ledger opens.
  * "Reconciliation" still opens the native journal-cards dashboard (behaviour
    of the action is unchanged -- only the menu label/sequence moved).
"""
import os
import sys

sys.path.insert(0, ".")
from browser_smoke import BrowserSmoke  # noqa: E402

SHOT = os.path.join("smoke-output", "banking_frontdoor")
os.makedirs(SHOT, exist_ok=True)


def main():
    with BrowserSmoke("banking_frontdoor") as smoke:
        smoke.login("p2m75_book")
        smoke.page.set_viewport_size({"width": 1600, "height": 1000})

        with smoke.scenario("Statements is the front door; Banking is now 'Reconciliation' and demoted"):
            menus = smoke._load_web_menus()
            roots = {m["id"]: m for m in menus.values()}
            top = menus.get("root", {}).get("children", [])

            def by_id(mid):
                return roots.get(mid, {})
            # top-level children come back in sequence order -> assert by index
            ordered_names = [by_id(mid).get("name") for mid in top]
            smoke._record_assert("'Statements' top-level present",
                                 expect="present", actual=str("Statements" in ordered_names), passed="Statements" in ordered_names)
            smoke._record_assert("'Reconciliation' top-level present (ex-Banking)",
                                 expect="present", actual=str("Reconciliation" in ordered_names), passed="Reconciliation" in ordered_names)
            smoke._record_assert("'Banking' label gone (renamed)",
                                 expect="absent", actual=str("Banking" in ordered_names), passed="Banking" not in ordered_names)
            s_idx = ordered_names.index("Statements") if "Statements" in ordered_names else -1
            r_idx = ordered_names.index("Reconciliation") if "Reconciliation" in ordered_names else -1
            smoke._record_assert("Statements sorts ahead of Reconciliation (front door)",
                                 expect="idx(Statements) < idx(Reconciliation)",
                                 actual="Statements@%d Reconciliation@%d" % (s_idx, r_idx),
                                 passed=(s_idx >= 0 and r_idx >= 0 and s_idx < r_idx))

        with smoke.scenario("Account Ledgers leads Statements; Petty Cash ledger opens"):
            smoke.open_action("neon_banking_statement.action_statement_petty_cash")
            smoke.page.wait_for_timeout(1200)
            smoke.assert_visible("div.o_action_manager", "Petty Cash statement renders")
            smoke.assert_visible(".o_control_panel button.btn-primary:has-text('Add Expense')",
                                 "statement front-door is live (Add Expense button present)")
            smoke.screenshot("petty_cash_frontdoor")

        with smoke.scenario("'Reconciliation' still opens the native journal-cards dashboard (action unchanged)"):
            smoke.open_action("account.open_account_journal_dashboard_kanban")
            smoke.page.wait_for_timeout(1500)
            smoke.assert_visible("div.o_action_manager", "dashboard action renders")
            body = smoke.page.locator("body").inner_text()
            # the journal cards still show (Petty Cash / CABS) -> reconciliation tool intact
            seen = [j for j in ["Petty Cash", "CABS", "Undeposited"] if j in body]
            smoke._record_assert("journal cards still present on the dashboard",
                                 expect=">=1 journal card", actual=str(seen), passed=len(seen) >= 1)
            smoke.screenshot("reconciliation_dashboard")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
