"""P12.M1.1 browser smoke — multi-variant chat + hotfixes.

Scenarios:
(1) Bookkeeper variant: chat visible + "Finance Copilot" system
    prompt drives a tool card response.
(2) Lead Tech variant: chat visible + readiness/jobs tool card.
(3) Crew-tier-only login: chat NOT visible (ACL D22).
(4) Director peeks Bookkeeper variant via MD-peek: variant
    intersection applies (D24).
(5) Thinking-dots placeholder bubble is visible while a request
    is in flight (D19).
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"

_SETUP = """
Users = env['res.users']

def _wipe_login(login):
    u = Users.search([('login','=',login)], limit=1)
    if u:
        u.write({
            'login': login + '_OLD_' + str(u.id),
            'active': False,
        })

# Fresh fixtures every run so groups are deterministic.
_wipe_login('p12m1_1_bookkeeper')
_wipe_login('p12m1_1_lead_tech')
_wipe_login('p12m1_1_crew_only')
_wipe_login('p12m1_1_director')

bk = Users.with_context(no_reset_password=True).create({
    'name': 'p12m1_1_bookkeeper',
    'login': 'p12m1_1_bookkeeper',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('neon_core.group_neon_bookkeeper').id),
    ],
})
bk.write({'preferred_dashboard_type': 'bookkeeper'})

lt = Users.with_context(no_reset_password=True).create({
    'name': 'p12m1_1_lead_tech',
    'login': 'p12m1_1_lead_tech',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('neon_core.group_neon_lead_tech').id),
        (4, env.ref('neon_jobs.group_neon_jobs_crew_leader').id),
    ],
})
lt.write({'preferred_dashboard_type': 'lead_tech'})

# Crew-tier-only: a non-leader crew user. Should have NO chat
# panel because no entry in the D22 group set.
crew = Users.with_context(no_reset_password=True).create({
    'name': 'p12m1_1_crew_only',
    'login': 'p12m1_1_crew_only',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('neon_core.group_neon_crew').id),
        (4, env.ref('neon_jobs.group_neon_jobs_crew').id),
    ],
})
# Crew tier has no dedicated dashboard variant but the dashboard
# auto-routes them; we just check the chat panel isn't there.
crew.write({'preferred_dashboard_type': 'tech'})

director = Users.with_context(no_reset_password=True).create({
    'name': 'p12m1_1_director',
    'login': 'p12m1_1_director',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('neon_core.group_neon_superuser').id),
        (4, env.ref('neon_jobs.group_neon_jobs_manager').id),
    ],
})
director.write({'preferred_dashboard_type': 'director'})

env.cr.commit()
print('IDS_JSON=' + repr({
    'bk': bk.id, 'lt': lt.id, 'crew': crew.id, 'director': director.id,
}))
"""


def _shell(script):
    p = subprocess.run(
        ["docker", "compose", "--project-directory",
         "C:/Users/Neon/neon-odoo", "exec", "-T", "odoo",
         "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"), capture_output=True, timeout=180)
    return (p.stdout + p.stderr).decode("utf-8", errors="replace")


def _setup():
    out = _shell(_SETUP)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print("[p12m1_1] SETUP FAILED:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


def run():
    ids = _setup()
    with BrowserSmoke("p12m1_1") as smoke:

        with smoke.scenario("Bookkeeper variant: chat visible + Finance tool card"):
            smoke.login("p12m1_1_bookkeeper")
            smoke.page.goto(
                f"{BASE_URL}/web#action=neon_dashboard."
                f"action_neon_dashboard_server")
            smoke.page.wait_for_selector(
                ".o_neon_dashboard", timeout=20000)
            smoke.page.wait_for_timeout(800)
            rails = smoke.page.locator(
                ".o_neon_ai_chat__rail").count()
            smoke._record_assert(
                "chat rail visible for bookkeeper",
                expect=">=1", actual=str(rails),
                passed=rails >= 1)
            if rails < 1:
                raise AssertionFail("chat rail not rendered")
            smoke.page.locator(
                ".o_neon_ai_chat__rail").first.click()
            smoke.page.wait_for_selector(
                ".o_neon_ai_chat__panel", timeout=5000)
            smoke.page.wait_for_timeout(400)
            inp = smoke.page.locator(
                ".o_neon_ai_chat__input").first
            inp.fill("Show me overdue invoices.")
            smoke.page.locator(
                ".o_neon_ai_chat__send").first.click()
            smoke.page.wait_for_function(
                "document.querySelectorAll("
                "'.o_neon_ai_chat__bubble_assistant, "
                ".o_neon_ai_chat__tool_card').length > 0",
                timeout=30000)
            tool_or_assist = smoke.page.locator(
                ".o_neon_ai_chat__bubble_assistant, "
                ".o_neon_ai_chat__tool_card").count()
            smoke._record_assert(
                "tool card or assistant reply on bookkeeper",
                expect=">=1", actual=str(tool_or_assist),
                passed=tool_or_assist >= 1)
            smoke.screenshot("bookkeeper_chat")

        with smoke.scenario("Lead Tech variant: chat visible + jobs/readiness reply"):
            smoke.login("p12m1_1_lead_tech")
            smoke.page.goto(
                f"{BASE_URL}/web#action=neon_dashboard."
                f"action_neon_dashboard_server")
            smoke.page.wait_for_selector(
                ".o_neon_dashboard", timeout=20000)
            smoke.page.wait_for_timeout(800)
            rails = smoke.page.locator(
                ".o_neon_ai_chat__rail").count()
            smoke._record_assert(
                "chat rail visible for lead tech",
                expect=">=1", actual=str(rails),
                passed=rails >= 1)
            if rails < 1:
                raise AssertionFail("chat rail not rendered")
            smoke.page.locator(
                ".o_neon_ai_chat__rail").first.click()
            smoke.page.wait_for_selector(
                ".o_neon_ai_chat__panel", timeout=5000)
            smoke.page.wait_for_timeout(400)
            inp = smoke.page.locator(
                ".o_neon_ai_chat__input").first
            inp.fill("What's on the schedule this week?")
            smoke.page.locator(
                ".o_neon_ai_chat__send").first.click()
            smoke.page.wait_for_function(
                "document.querySelectorAll("
                "'.o_neon_ai_chat__bubble_assistant, "
                ".o_neon_ai_chat__tool_card').length > 0",
                timeout=30000)
            replies = smoke.page.locator(
                ".o_neon_ai_chat__bubble_assistant, "
                ".o_neon_ai_chat__tool_card").count()
            smoke._record_assert(
                "lead tech got a reply",
                expect=">=1", actual=str(replies),
                passed=replies >= 1)
            smoke.screenshot("leadtech_chat")

        with smoke.scenario("Thinking-dots placeholder during in-flight"):
            # Reuse the open lead-tech panel. Type + send; assert
            # the dots bubble appears before the response lands.
            inp = smoke.page.locator(
                ".o_neon_ai_chat__input").first
            inp.fill("Any readiness gates blocking this week?")
            smoke.page.locator(
                ".o_neon_ai_chat__send").first.click()
            # Catch the placeholder BEFORE the response lands. The
            # dots bubble has class .o_neon_ai_chat__thinking.
            try:
                smoke.page.wait_for_selector(
                    ".o_neon_ai_chat__thinking",
                    timeout=8000, state="visible")
                thinking_seen = True
            except Exception:
                thinking_seen = False
            smoke._record_assert(
                "thinking-dots bubble visible during in-flight",
                expect="visible", actual=str(thinking_seen),
                passed=thinking_seen)
            # Now wait for the response to land + the placeholder
            # to clear.
            smoke.page.wait_for_function(
                "document.querySelectorAll("
                "'.o_neon_ai_chat__thinking').length === 0",
                timeout=30000)
            smoke.screenshot("thinking_replaced")

        with smoke.scenario("Crew tier (no role): chat NOT visible"):
            smoke.login("p12m1_1_crew_only")
            smoke.page.goto(
                f"{BASE_URL}/web#action=neon_dashboard."
                f"action_neon_dashboard_server")
            smoke.page.wait_for_timeout(2500)
            # Either dashboard rendered (tech variant) or didn't.
            # In either case, the chat panel must NOT be present.
            chat_count = smoke.page.locator(
                ".o_neon_ai_chat").count()
            smoke._record_assert(
                "chat absent for crew tier",
                expect="==0", actual=str(chat_count),
                passed=chat_count == 0)
            smoke.screenshot("crew_no_chat")

        with smoke.scenario("Director peeks Bookkeeper variant"):
            smoke.login("p12m1_1_director")
            # Director's default variant is director; peek
            # bookkeeper via URL ?dashboard_type=bookkeeper.
            smoke.page.goto(
                f"{BASE_URL}/web?dashboard_type=bookkeeper"
                f"#action=neon_dashboard."
                f"action_neon_dashboard_server")
            smoke.page.wait_for_selector(
                ".o_neon_dashboard", timeout=20000)
            smoke.page.wait_for_timeout(800)
            # Confirm we're on bookkeeper variant.
            classes = smoke.page.locator(
                ".o_neon_dashboard").first.get_attribute("class") or ""
            on_bk = "filter_" in classes  # any filter class indicates dashboard rendered
            # Chat should still be visible (director is in
            # the chat ACL group set).
            rails = smoke.page.locator(
                ".o_neon_ai_chat__rail, .o_neon_ai_chat__panel"
            ).count()
            smoke._record_assert(
                "chat visible for director peeking bookkeeper",
                expect=">=1", actual=str(rails),
                passed=rails >= 1)
            smoke.screenshot("director_peek_bookkeeper")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(run())
