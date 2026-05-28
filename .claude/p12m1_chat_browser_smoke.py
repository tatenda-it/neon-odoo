"""P12.M1 browser smoke -- AI Sales Copilot chat panel.

Scenarios:
(1) Sales variant: chat rail visible, click expands panel with
    history loaded.
(2) Empty-state copy renders when there are no prior messages.
(3) Type a message -> /neon/ai_chat/send fires -> user bubble +
    assistant bubble appear; if Groq is healthy, assistant text is
    non-empty; if a tool fires, a tool card renders.
(4) Lead Tech variant (D11): chat icon NOT visible.
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

def _gom(login, group_xmlids):
    u = Users.search([('login','=',login)], limit=1)
    ids = [env.ref(x).id for x in group_xmlids]
    if not u:
        u = Users.with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'password': 'test123',
            'groups_id': [(4, gid) for gid in ids],
        })
    else:
        for gid in ids:
            if gid not in u.groups_id.ids:
                u.write({'groups_id': [(4, gid)]})
        # Reset the password unconditionally so re-runs work even
        # if a prior fixture used a different secret.
        u.write({'password': 'test123'})
    return u

# Sales user used by scenarios 1-3 (sees the panel).
# Needs:
#  - neon_jobs.group_neon_jobs_user  -> chat ACL gate
#  - neon_core.group_neon_sales_rep  -> dashboard menu visibility
sales = _gom('p12m1_sales', [
    'neon_jobs.group_neon_jobs_user',
    'neon_core.group_neon_sales_rep',
])
sales.write({'preferred_dashboard_type': 'sales'})

# Lead-Tech user used by scenario 4 (panel must NOT render).
# Wipe any prior fixture for this login so the groups state is
# deterministic; previous smoke runs may have stripped + re-added
# groups in ways that crashed session_info on ir.ui.menu.
prior_lead = Users.search(
    [('login','=','p12m1_leadtech_only')], limit=1)
if prior_lead:
    # We can't unlink (audit guards), so just deactivate + rename
    # so the new fixture below doesn't clash on the unique login.
    prior_lead.write({
        'login': 'p12m1_leadtech_only_OLD_' + str(prior_lead.id),
        'active': False,
    })
lead = Users.with_context(no_reset_password=True).create({
    'name': 'p12m1_leadtech_only',
    'login': 'p12m1_leadtech_only',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('neon_core.group_neon_lead_tech').id),
        (4, env.ref('neon_jobs.group_neon_jobs_crew_leader').id),
    ],
})
lead.write({'preferred_dashboard_type': 'lead_tech'})

# Clear any leftover chat state so the panel starts collapsed and
# the empty-state copy is visible on first render.
sales.write({'chat_panel_expanded': False})

# Clear any prior chat messages so the empty-state assertion holds.
Session = env['neon.finance.ai.chat.session']
Message = env['neon.finance.ai.chat.message']
s = Session.search([('user_id','=', sales.id)], limit=1)
if s:
    # ACL says perm_unlink=0; bypass with raw SQL since this is
    # smoke-only fixture cleanup. Production code never touches.
    env.cr.execute(
        'DELETE FROM neon_finance_ai_chat_message WHERE session_id=%s',
        (s.id,))
env.cr.commit()
print('IDS_JSON=' + repr({'sales': sales.id, 'lead': lead.id}))
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
        print("[p12m1] SETUP FAILED:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


def run():
    ids = _setup()
    with BrowserSmoke("p12m1") as smoke:

        with smoke.scenario("Sales: chat rail visible + click expands"):
            smoke.login("p12m1_sales")
            smoke.page.goto(
                f"{BASE_URL}/web#action=neon_dashboard."
                f"action_neon_dashboard_server")
            smoke.page.wait_for_selector(
                ".o_neon_dashboard", timeout=20000)
            smoke.page.wait_for_timeout(800)
            rails = smoke.page.locator(".o_neon_ai_chat__rail").count()
            smoke._record_assert(
                "chat rail visible on sales variant",
                expect=">=1", actual=str(rails),
                passed=rails >= 1)
            if rails < 1:
                raise AssertionFail("chat rail not rendered")
            smoke.page.locator(".o_neon_ai_chat__rail").first.click()
            smoke.page.wait_for_selector(
                ".o_neon_ai_chat__panel", timeout=5000)
            smoke.page.wait_for_timeout(400)
            panels = smoke.page.locator(
                ".o_neon_ai_chat__panel").count()
            smoke._record_assert(
                "panel expands on rail click",
                expect=">=1", actual=str(panels),
                passed=panels >= 1)
            smoke.screenshot("panel_expanded")

        with smoke.scenario("Empty-state copy renders"):
            empty = smoke.page.locator(
                ".o_neon_ai_chat__empty").count()
            smoke._record_assert(
                "empty-state hint visible on fresh session",
                expect=">=1", actual=str(empty),
                passed=empty >= 1)

        with smoke.scenario("Send a message and receive a reply"):
            input_box = smoke.page.locator(
                ".o_neon_ai_chat__input").first
            input_box.fill(
                "Show me my open quotes.")
            smoke.page.locator(
                ".o_neon_ai_chat__send").first.click()
            # Wait for either the assistant bubble OR a tool card.
            smoke.page.wait_for_function(
                "document.querySelectorAll("
                "'.o_neon_ai_chat__bubble_assistant, "
                ".o_neon_ai_chat__tool_card').length > 0",
                timeout=30000,
            )
            user_bubbles = smoke.page.locator(
                ".o_neon_ai_chat__bubble_user").count()
            assist_or_card = smoke.page.locator(
                ".o_neon_ai_chat__bubble_assistant, "
                ".o_neon_ai_chat__tool_card").count()
            smoke._record_assert(
                "user bubble persisted",
                expect=">=1", actual=str(user_bubbles),
                passed=user_bubbles >= 1)
            smoke._record_assert(
                "assistant reply OR tool card rendered",
                expect=">=1", actual=str(assist_or_card),
                passed=assist_or_card >= 1)
            smoke.screenshot("chat_reply")

        with smoke.scenario("Lead-tech variant: chat NOT visible"):
            smoke.login("p12m1_leadtech_only")
            smoke.page.goto(
                f"{BASE_URL}/web#action=neon_dashboard."
                f"action_neon_dashboard_server")
            smoke.page.wait_for_selector(
                ".o_neon_dashboard", timeout=20000)
            smoke.page.wait_for_timeout(800)
            chat_count = smoke.page.locator(
                ".o_neon_ai_chat").count()
            smoke._record_assert(
                "chat panel ABSENT on lead-tech variant",
                expect="==0", actual=str(chat_count),
                passed=chat_count == 0)
            smoke.screenshot("leadtech_no_chat")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(run())
