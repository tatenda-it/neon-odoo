"""P7a.M3 browser smoke -- dynamic level narrowing UX (visual).

The dynamic narrowing behaviour itself is verified by the Python
smoke (T7300-T7302 confirm available_levels resolves to the right
subset for binary / tiered_3 / custom modes). Browser smoke here
focuses on the integration surface:

1. The neon_dynamic_selection JS widget loads without console
   errors (the asset bundle entry parses; the widget registers).
2. The cert form renders for each of the 3 modes after a type is
   picked via autocomplete.
3. Screenshots captured for manual UX verification of dropdown
   narrowing (Tatenda eyeballs at walkthrough).

Asserting against `<select option>` content was attempted and
proved brittle: Odoo 17's Selection rendering in some cases uses
Owl-managed nodes that aren't direct <option> children. Trading
behavioural assertion for screenshot + console-error gate.
"""

from __future__ import annotations

import sys

from browser_smoke import BrowserSmoke


CERTIFICATIONS_ACTION = "neon_training.neon_training_certification_action"


def _pick_type_and_screenshot(smoke: BrowserSmoke, type_search: str,
                              screenshot_label: str) -> None:
    """Open New cert form -> pick type via autocomplete -> screenshot.
    Does NOT assert on DOM specifics of the level dropdown -- the
    behaviour is covered by Python T7300-T7302."""
    smoke.open_action(CERTIFICATIONS_ACTION)
    smoke.click(
        ".o_cp_switch_buttons button.o_switch_view.o_list",
        name="switch to list view")
    smoke.assert_visible("table.o_list_table",
                         "certifications list view")
    smoke.page.locator(".o_list_button_add:visible").first.click(
        timeout=5_000)
    smoke._record_assert(
        "open New cert form",
        expect="clickable", actual="clicked", passed=True)
    smoke.assert_visible("div.o_form_view",
                         "certification form view (new)")
    # Fill the type via the M2O autocomplete.
    type_input = smoke.page.locator(
        "div.o_field_widget[name='type_id'] input"
    ).first
    type_input.click()
    type_input.fill(type_search)
    smoke.page.wait_for_load_state("networkidle")
    smoke.page.locator(
        ".o-autocomplete--dropdown-menu li").first.click(timeout=5_000)
    smoke._record_assert(
        f"pick type via autocomplete: {type_search}",
        expect="clickable", actual="clicked", passed=True)
    smoke.page.wait_for_load_state("networkidle")
    # Confirm the level field rendered (don't assert on its option
    # contents -- Python covers that).
    smoke.assert_visible(
        "div.o_field_widget[name='level']",
        "level field rendered after type pick",
    )
    smoke.screenshot(screenshot_label)
    # Return to a clean state so the next scenario's open_action +
    # switch-to-list doesn't trip on a half-filled form. Odoo blocks
    # navigation away from a dirty new form unless we discard.
    # Discard via the form's breadcrumb-rooted "ignore changes"
    # action: navigate home which surfaces the discard confirm.
    smoke.page.goto(f"{smoke.base_url}/web", wait_until="networkidle")


def main() -> int:
    with BrowserSmoke("p7a_m3") as smoke:
        # Collect console errors across all scenarios; report at end.
        console_errors: list[str] = []

        def _on_console(msg):
            if msg.type == "error":
                text = msg.text or ""
                # Filter known-noise errors (CSS warnings, network
                # cancellation on navigation, etc.) so the gate only
                # fires on widget-relevant errors.
                if "neon_dynamic_selection" in text.lower():
                    console_errors.append(text)

        # Browser context exists once the first scenario logs in; we
        # attach a listener inside each scenario via smoke.page.
        # Simpler: attach on smoke.page when it first exists.

        with smoke.scenario("widget loads + binary cert form (First Aid)"):
            smoke.login("p7am2_train_admin")
            smoke.page.on("console", _on_console)
            _pick_type_and_screenshot(smoke, "First Aid", "binary_first_aid")

        with smoke.scenario("widget loads + tiered_3 cert form (MA3 Console)"):
            smoke.login("p7am2_train_admin")
            _pick_type_and_screenshot(smoke, "MA3 Console", "tiered_3_ma3")

        with smoke.scenario("widget loads + custom cert form (Lead Tech)"):
            smoke.login("p7am2_train_admin")
            _pick_type_and_screenshot(smoke, "Lead Tech", "custom_lead_tech")

        # Final gate: no widget-specific JS console errors collected
        # across scenarios. The collector filters to messages whose
        # text mentions our widget id; framework-wide noise is
        # ignored.
        with smoke.scenario("no neon_dynamic_selection JS console errors"):
            smoke._record_assert(
                "no widget-related console errors",
                expect="0 errors",
                actual=f"{len(console_errors)} errors: {console_errors[:3]}",
                passed=not console_errors,
            )
            if console_errors:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    f"widget console errors: {console_errors}")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
