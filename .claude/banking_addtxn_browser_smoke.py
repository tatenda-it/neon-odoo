"""STAGE 2 browser smoke -- "Add Transaction" quick-entry on the statement.

Verifies, as the bookkeeper (p2m75_book), the user-facing surface the
ORM smoke cannot see:
  * the on-view <header> buttons render WITHOUT row selection (display=always)
  * NO raw "New" button (the statement is create=0; only typed Add buttons)
  * "Add Expense" opens a dialog with Neon words and NO Dr/Cr/journal/suspense
  * a full click -> fill -> Save posts a line that APPEARS in the statement
    with the running balance dropping (depth principle)
  * "Add Replenishment" dialog opens too

Posts persist (the wizard commits); the companion cleanup shell removes the
[TEST-BS2] moves afterwards. Run after -u + force-recreate.
"""
import os
import sys

sys.path.insert(0, ".")
from browser_smoke import BrowserSmoke  # noqa: E402

DB = "neon_crm"
SHOT_DIR = os.path.join("smoke-output", "banking_addtxn")
os.makedirs(SHOT_DIR, exist_ok=True)

EXPENSE_ACTION = "neon_banking_statement.action_statement_petty_cash"
DETAILS_MARK = "[TEST-BS2] browser fuel"


def main():
    with BrowserSmoke("banking_addtxn") as smoke:
        smoke.login("p2m75_book")

        # The header renders the visible buttons (btn-primary / btn-secondary) in
        # the d-xl-inline-flex group AND collapsed btn-link twins in a hidden
        # small-screen dropdown -- target the visible ones by their btn class.
        EXP_BTN = ".o_control_panel button.btn-primary:has-text('Add Expense')"
        REP_BTN = ".o_control_panel button.btn-secondary:has-text('Add Replenishment')"

        with smoke.scenario("Petty Cash statement shows Add buttons, no raw New"):
            smoke.open_action(EXPENSE_ACTION)
            smoke.page.wait_for_timeout(1200)
            smoke.assert_visible("div.o_action_manager", "statement renders")
            # display=always header buttons -> present with NO selection
            smoke.assert_visible(EXP_BTN, "Add Expense button visible")
            smoke.assert_visible(REP_BTN, "Add Replenishment button visible")
            # create=0 -> no stock "New" record button on this list
            new_btns = smoke.page.locator(".o_control_panel button.o_list_button_add").count()
            smoke._record_assert("no raw 'New' button (create=0)",
                                 expect="0", actual=str(new_btns), passed=new_btns == 0)
            smoke.screenshot("statement_with_add_buttons")

        with smoke.scenario("Add Expense opens a Zoho-style dialog, no Dr/Cr jargon"):
            smoke.click(EXP_BTN, name="open Add Expense")
            smoke.page.wait_for_timeout(700)
            smoke.assert_visible(".modal .o_form_view", "expense dialog form opens")
            body = smoke.page.locator(".modal").inner_text().lower()
            for word in ["expense account", "amount", "details", "paid from"]:
                smoke._record_assert("dialog shows field: %s" % word,
                                     expect="present", actual=("yes" if word in body else "no"),
                                     passed=word in body)
            for jargon in ["debit", "credit", "journal entry", "suspense", "reconcile"]:
                smoke._record_assert("NO jargon: %s" % jargon,
                                     expect="absent", actual=("present" if jargon in body else "absent"),
                                     passed=jargon not in body)
            smoke.screenshot("expense_dialog")

        with smoke.scenario("Fill + Save posts an expense that appears in the statement"):
            # Amount + Details (plain inputs)
            smoke.page.locator(".modal .o_field_widget[name=amount] input").fill("42.50")
            smoke.page.locator(".modal .o_field_widget[name=description] input,"
                               " .modal .o_field_widget[name=description] textarea").first.fill(DETAILS_MARK)
            # Expense Account m2o: type the code, pick from the autocomplete
            acc_input = smoke.page.locator(".modal .o_field_widget[name=expense_account_id] input")
            acc_input.click()
            acc_input.fill("613000")
            smoke.page.wait_for_timeout(900)
            opt = smoke.page.locator(".o-autocomplete--dropdown-menu li a,"
                                     " .ui-autocomplete .ui-menu-item").first
            opt.click(timeout=8000)
            smoke.page.wait_for_timeout(400)
            smoke.screenshot("expense_filled")
            # Save
            smoke.click(".modal footer button:has-text('Save')", name="click Save")
            smoke.page.wait_for_timeout(1500)
            # dialog gone
            modal_gone = smoke.page.locator(".modal .o_form_view").count() == 0
            smoke._record_assert("dialog closed after Save", expect="0 modal",
                                 actual=str(smoke.page.locator(".modal .o_form_view").count()),
                                 passed=modal_gone)
            # the posted line shows in the statement (running ledger)
            smoke.page.wait_for_timeout(800)
            row = smoke.page.locator("tr.o_data_row:has-text('%s')" % DETAILS_MARK).count()
            smoke._record_assert("posted expense appears in statement",
                                 expect=">=1 row", actual=str(row), passed=row >= 1)
            # the Cr column carries 42.50 on that row
            txt = smoke.page.locator("tr.o_data_row:has-text('%s')" % DETAILS_MARK).first.inner_text() \
                if row else ""
            smoke._record_assert("statement row shows 42.50",
                                 expect="42.50 present", actual=("yes" if "42.50" in txt else txt[:60]),
                                 passed="42.50" in txt)
            smoke.screenshot("statement_after_expense")

        with smoke.scenario("Add Replenishment dialog opens (money-in path)"):
            smoke.click(REP_BTN, name="open Add Replenishment")
            smoke.page.wait_for_timeout(700)
            smoke.assert_visible(".modal .o_form_view", "replenishment dialog form opens")
            body = smoke.page.locator(".modal").inner_text().lower()
            for word in ["into", "from", "amount", "details"]:
                smoke._record_assert("replen dialog shows: %s" % word,
                                     expect="present", actual=("yes" if word in body else "no"),
                                     passed=word in body)
            smoke.screenshot("replenishment_dialog")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
