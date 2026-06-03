"""P7f browser smoke -- certificate verification surface (2 scenarios).

Numbering, PDF render, revoke + the wizard's lookup logic are covered
in-process by p7f_smoke.py (T-P7F-01..33). This browser smoke exercises
the rendered surface with the depth principle:

1. signoff/admin (p7am2_train_admin) sees the 'Verify Certificate' menu,
   opens the wizard, runs a lookup, and gets a result badge back
   (menu visible -> click in -> assert content).
2. A non-privileged user (p2m75_sales) does NOT see the menu, and the
   wizard model rejects a direct RPC (AccessError) -- the who-sees-what
   boundary, verified at the RPC layer not just the UI.
"""

from __future__ import annotations

import sys

from browser_smoke import AssertionFail, BrowserSmoke

VERIFY_MENU = "neon_training.menu_neon_training_verify_cert"
VERIFY_ACTION = "neon_training.action_cert_verify_wizard"
WIZARD_MODEL = "neon.training.cert.verify.wizard"


def main() -> int:
    with BrowserSmoke("p7f") as smoke:

        # ------------------------------------------------------------
        # Scenario 1: signoff/admin -- menu visible, wizard opens, a
        # lookup returns a rendered result badge (depth).
        # ------------------------------------------------------------
        with smoke.scenario(
                "signoff/admin: Verify Certificate menu + wizard lookup"):
            smoke.login("p7am2_train_admin")
            smoke.assert_menu_visible(VERIFY_MENU)
            smoke.open_action(VERIFY_ACTION)
            # wizard form (target=new dialog) renders the query field
            smoke.assert_visible(
                ".o_field_widget[name='query']", "wizard query field")
            smoke.page.locator(
                ".o_field_widget[name='query'] input,"
                " .o_field_widget[name='query'] textarea"
            ).first.fill("NEON-XXX-0000-does-not-exist")
            smoke.click("button[name='action_lookup']", name="Look Up button")
            # depth: the lookup result badge renders for a bogus query
            smoke.assert_visible(
                "text=No certificate matches", "not-found result badge")
            smoke.screenshot("verify_wizard_notfound")

        # ------------------------------------------------------------
        # Scenario 2: non-privileged -- menu hidden + RPC denied.
        # ------------------------------------------------------------
        with smoke.scenario(
                "non-privileged (sales): Verify menu hidden + RPC denied"):
            smoke.login("p2m75_sales")
            smoke.assert_menu_hidden(VERIFY_MENU)
            smoke.assert_rpc_denied(
                WIZARD_MODEL, "create",
                "plain user cannot create verify wizard",
                args=[{}])
            smoke.goto_home()

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
