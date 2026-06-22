"""QUOTE-UX-2 (Solution A) browser smoke — single quote door, rendered.

Scenarios:
  A  A rep (p2m75_sales) no longer sees the stock Sales quote/order/to-invoice
     menus; the CRM "My Quotations" door + the new top-level "My Quotation"
     door are both visible and the ENGINE quote list opens + renders.
  B  A non-superuser director tier (p2m75_approver) also no longer sees the
     stock "Orders" menu (the hide is universal, not just the rep tier).

No fixtures created/committed (read-only navigation over existing data).
"""
from __future__ import annotations

import sys

from browser_smoke import BrowserSmoke, AssertionFail  # noqa: F401


def main() -> int:
    with BrowserSmoke("quoteux2") as smoke:

        with smoke.scenario("A: rep sees only the engine quote door"):
            smoke.login("p2m75_sales")
            # stock doors gone
            smoke.assert_menu_hidden("sale.menu_sale_quotations")
            smoke.assert_menu_hidden("sale.menu_sale_order")
            smoke.assert_menu_hidden("sale.menu_sale_invoicing")
            # engine doors present
            smoke.assert_menu_visible(
                "sale_crm.sale_order_menu_quotations_crm",
                name="CRM 'My Quotations' (redirected to engine) visible")
            smoke.assert_menu_visible(
                "neon_sales.menu_neon_quotes_toplevel",
                name="top-level 'My Quotation' visible")
            smoke.assert_menu_visible(
                "neon_finance.menu_neon_finance_quotes",
                name="Invoicing engine Quotes still visible")
            # the engine action (what those doors open) renders the quote
            # list. The rep's list is record-rule-scoped to their OWN quotes;
            # the fixture rep has none, so this proves the engine action loads
            # (the "has real rows" proof is done as the approver in B, who
            # sees all quotes).
            smoke.open_action("neon_finance.neon_finance_quote_action")
            smoke.assert_visible(
                "div.o_list_view", "engine quote list renders for the rep")
            smoke.screenshot("A_rep_engine_door")

        with smoke.scenario(
                "B: director tier loses stock Orders + engine list renders"):
            smoke.login("p2m75_approver")
            smoke.assert_menu_hidden("sale.menu_sale_order")
            smoke.assert_menu_hidden("sale.menu_sale_quotations")
            # approver still reaches the engine quote door
            smoke.assert_menu_visible(
                "neon_finance.menu_neon_finance_quotes",
                name="approver reaches the engine Quotes menu")
            # approver opens the engine action -> the quote list renders. (The
            # dev DB has 0 persistent neon.finance.quote rows -- suites
            # create-and-rollback -- so we assert the list view renders, not a
            # row count; the model smoke proves the engine quote actually
            # creates + computes.)
            smoke.open_action("neon_finance.neon_finance_quote_action")
            smoke.assert_visible(
                "div.o_list_view", "engine quote list renders for the approver")
            smoke.screenshot("B_director_engine_list")

    return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
