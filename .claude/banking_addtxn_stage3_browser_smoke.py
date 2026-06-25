"""STAGE 3 browser smoke -- the rest of the "Add Transaction" types.

As the bookkeeper (p2m75_book):
  * CABS USD statement shows the full Stage-3 button set (Pay a Bill, Receive a
    Payment, Vendor Advance, Money In, Drawings, Commission, Transfer/Deposit).
  * a money-out (Drawings) + a money-in (Money In) + a payment (Pay a Bill)
    dialog each open with Neon words and NO debit/credit/journal/suspense jargon.
  * a Drawings Save on Petty Cash posts and APPEARS in the statement (depth).
Posts persist; cleaned up after. Run after -u + force-recreate.
"""
import os
import sys

sys.path.insert(0, ".")
from browser_smoke import BrowserSmoke  # noqa: E402

SHOT = os.path.join("smoke-output", "banking_addtxn_stage3")
os.makedirs(SHOT, exist_ok=True)

CABS_USD = "neon_banking_statement.action_statement_cabs_usd"
PETTY = "neon_banking_statement.action_statement_petty_cash"
MARK = "[TEST-S3B] browser drawings"

# visible buttons: btn-primary (Add Expense / Pay a Bill / Receive a Payment) +
# btn-secondary (Vendor Advance / Money In / Drawings / Commission / Transfer);
# hidden small-screen twins are btn-link, so qualify by btn class.
JARGON = ["debit", "credit", "journal entry", "suspense", "reconcile"]


def cp_btn(label, cls="btn-secondary"):
    return ".o_control_panel button.%s:has-text(\"%s\")" % (cls, label)


def main():
    with BrowserSmoke("banking_addtxn_stage3") as smoke:
        smoke.login("p2m75_book")
        # CABS USD carries 8 header buttons; at the default 1400px they wrap and
        # a wrapped button's centre can be intercepted -> widen so they sit on one
        # row and every button is cleanly clickable.
        smoke.page.set_viewport_size({"width": 1920, "height": 1080})

        with smoke.scenario("CABS USD statement shows the full Stage-3 button set"):
            smoke.open_action(CABS_USD)
            smoke.page.wait_for_timeout(1200)
            smoke.assert_visible("div.o_action_manager", "statement renders")
            smoke.assert_visible(cp_btn("Pay a Bill", "btn-primary"), "Pay a Bill button")
            smoke.assert_visible(cp_btn("Receive a Payment", "btn-primary"), "Receive a Payment button")
            smoke.assert_visible(cp_btn("Vendor Advance"), "Vendor Advance button")
            smoke.assert_visible(cp_btn("Money In"), "Money In button")
            smoke.assert_visible(cp_btn("Drawings"), "Drawings button")
            smoke.assert_visible(cp_btn("Commission"), "Commission button")
            smoke.assert_visible(cp_btn("Transfer / Deposit"), "Transfer/Deposit button")
            smoke.screenshot("cabs_usd_buttons")

        with smoke.scenario("Pay a Bill dialog opens, no Dr/Cr jargon"):
            smoke.open_action(CABS_USD)
            smoke.page.wait_for_timeout(1000)
            smoke.click(cp_btn("Pay a Bill", "btn-primary"), name="open Pay a Bill")
            smoke.page.wait_for_timeout(900)
            smoke.assert_visible(".modal .o_form_view", "Pay a Bill dialog opens")
            body = smoke.page.locator(".modal").inner_text().lower()
            for w in ["bill", "vendor", "amount", "pay from"]:
                smoke._record_assert("dialog shows: %s" % w, expect="present",
                                     actual=("yes" if w in body else "no"), passed=w in body)
            for j in JARGON:
                smoke._record_assert("NO jargon: %s" % j, expect="absent",
                                     actual=("present" if j in body else "absent"), passed=j not in body)
            smoke.screenshot("pay_a_bill_dialog")
            smoke.click(".modal footer button:has-text('Cancel')", name="close Pay a Bill")
            smoke.page.wait_for_timeout(600)

        with smoke.scenario("Money In dialog opens, no jargon"):
            # re-open the action to guarantee a clean control panel (no lingering modal)
            smoke.open_action(CABS_USD)
            smoke.page.wait_for_timeout(1000)
            smoke.click(cp_btn("Money In"), name="open Money In")
            smoke.page.wait_for_timeout(700)
            smoke.assert_visible(".modal .o_form_view", "Money In dialog opens")
            body = smoke.page.locator(".modal").inner_text().lower()
            for w in ["into", "source", "amount", "details"]:
                smoke._record_assert("money-in shows: %s" % w, expect="present",
                                     actual=("yes" if w in body else "no"), passed=w in body)
            for j in JARGON:
                smoke._record_assert("NO jargon: %s" % j, expect="absent",
                                     actual=("present" if j in body else "absent"), passed=j not in body)
            smoke.click(".modal footer button:has-text('Cancel')", name="close Money In")
            smoke.page.wait_for_timeout(600)

        with smoke.scenario("Drawings Save on Petty Cash posts + appears in statement"):
            smoke.open_action(PETTY)
            smoke.page.wait_for_timeout(1000)
            smoke.click(cp_btn("Drawings"), name="open Drawings")
            smoke.page.wait_for_timeout(700)
            smoke.assert_visible(".modal .o_form_view", "Drawings dialog opens")
            body = smoke.page.locator(".modal").inner_text().lower()
            for j in JARGON:
                smoke._record_assert("NO jargon: %s" % j, expect="absent",
                                     actual=("present" if j in body else "absent"), passed=j not in body)
            # drawings_account_id defaults to 303000; fill only amount + details
            smoke.page.locator(".modal .o_field_widget[name=amount] input").fill("33.00")
            smoke.page.locator(".modal .o_field_widget[name=description] input,"
                               " .modal .o_field_widget[name=description] textarea").first.fill(MARK)
            smoke.screenshot("drawings_filled")
            smoke.click(".modal footer button:has-text('Save')", name="Save Drawings")
            smoke.page.wait_for_timeout(1500)
            gone = smoke.page.locator(".modal .o_form_view").count() == 0
            smoke._record_assert("dialog closed after Save", expect="closed",
                                 actual=("closed" if gone else "open"), passed=gone)
            smoke.page.wait_for_timeout(700)
            row = smoke.page.locator("tr.o_data_row:has-text('%s')" % MARK).count()
            smoke._record_assert("drawings appears in Petty Cash statement",
                                 expect=">=1", actual=str(row), passed=row >= 1)
            txt = smoke.page.locator("tr.o_data_row:has-text('%s')" % MARK).first.inner_text() if row else ""
            smoke._record_assert("statement row shows 33.00 (Cr)",
                                 expect="33.00", actual=("yes" if "33.00" in txt else txt[:50]),
                                 passed="33.00" in txt)
            smoke.screenshot("petty_after_drawings")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
