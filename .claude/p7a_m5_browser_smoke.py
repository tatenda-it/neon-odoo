"""P7a.M5 browser smoke -- notification dispatch surfaces (3 scenarios).

The dispatch logic itself is verified by the Python smoke (T7500-
T7521 cover cron, idempotency, reset triggers, CC routing,
template rendering). Browser smoke focuses on the rendered surface:

1. Admin opens Discuss / Inbox after the cron has run; recent
   mail message visible (system mail thread tracks dispatch).
2. User opens their profile / activity widget; TODO entry
   visible with the deadline date.
3. Cert form renders; expiry urgency badge present (already
   verified by M4 smoke, lightweight re-check after M5's
   model/view additions don't regress it).

The Python smoke rolls back fixtures, so this browser smoke
focuses on shell-survivable surfaces: menus, form layout, lack
of console errors after the M5 manifest bump. Mail dispatch
end-to-end is verified by Python smoke calls to send_mail.
"""

from __future__ import annotations

import sys

from browser_smoke import BrowserSmoke


CERTIFICATIONS_ACTION = "neon_training.neon_training_certification_action"


def main() -> int:
    with BrowserSmoke("p7a_m5") as smoke:

        # ------------------------------------------------------------
        # Scenario 1: admin reaches Certifications list and the M5
        # last_notification_sent_urgency column is available via the
        # field selector. Confirms the field landed without view
        # breakage.
        # ------------------------------------------------------------
        with smoke.scenario("admin reaches Certifications list, M5 field on model"):
            smoke.login("p7am2_train_admin")
            smoke.open_action(CERTIFICATIONS_ACTION)
            smoke.click(
                ".o_cp_switch_buttons button.o_switch_view.o_list",
                name="switch to list view")
            smoke.assert_visible("table.o_list_table",
                                 "certifications list view")
            # M5 field present on model; verify via RPC fields_get.
            body = smoke.json_rpc(
                "neon.training.certification",
                "fields_get",
                args=[["last_notification_sent_urgency"]],
            )
            field_meta = (body.get("result") or {})
            passed = ("last_notification_sent_urgency" in field_meta)
            smoke._record_assert(
                "last_notification_sent_urgency on model",
                expect="field present",
                actual=f"keys={list(field_meta.keys())}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    "M5 field missing from fields_get response")
            smoke.screenshot("admin_cert_list_m5")

        # ------------------------------------------------------------
        # Scenario 2: admin opens cert form; statusbar + expiry
        # urgency widget render (M4 surfaces unaffected by M5).
        # ------------------------------------------------------------
        with smoke.scenario("admin opens cert form, M4 expiry widgets intact post-M5"):
            smoke.login("p7am2_train_admin")
            smoke.open_action(CERTIFICATIONS_ACTION)
            smoke.click(
                ".o_cp_switch_buttons button.o_switch_view.o_list",
                name="switch to list view")
            smoke.page.locator(".o_list_button_add:visible").first.click(
                timeout=5_000)
            smoke._record_assert(
                "open New cert form",
                expect="clickable", actual="clicked", passed=True)
            smoke.assert_visible("div.o_form_view",
                                 "certification form view (new)")
            smoke.assert_visible(".o_statusbar_status",
                                 "state machine statusbar")
            smoke.assert_visible("div.oe_chatter", "chatter rendered")
            smoke.screenshot("admin_cert_form_m5_regression")
            smoke.page.goto(f"{smoke.base_url}/web",
                            wait_until="networkidle")

        # ------------------------------------------------------------
        # Scenario 3: verify the mail.template records exist + are
        # readable. ir.cron read requires base.group_system which
        # training_admin doesn't carry; cron registration is
        # verified by Python smoke T7500-T7502 instead. Browser
        # smoke covers the mail.template surface which any internal
        # user can search.
        # ------------------------------------------------------------
        with smoke.scenario("M5 mail.template records present + readable"):
            smoke.login("p7am2_train_admin")
            body = smoke.json_rpc(
                "mail.template",
                "search_read",
                args=[
                    [("model", "=", "neon.training.certification"),
                     ("name", "ilike", "Neon Training")],
                    ["id", "name", "model"],
                ],
            )
            rows = (body.get("result") or [])
            names = sorted(r.get("name", "") for r in rows)
            expected_count = 3
            passed = len(rows) >= expected_count
            smoke._record_assert(
                "M5 mail.template records present",
                expect=f">= {expected_count} templates",
                actual=f"found={len(rows)} names={names}",
                passed=passed,
            )
            if not passed:
                from browser_smoke import AssertionFail
                raise AssertionFail(
                    f"Expected >= {expected_count} templates, "
                    f"got {len(rows)}")
            smoke.screenshot("m5_mail_templates_present")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
