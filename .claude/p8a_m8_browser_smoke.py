"""P8A.M8 browser smoke -- Tasks block + Done + filter chip
visible surfaces.

Scenarios:

1. p8a_director loads dashboard -> Tasks block renders real
   (not "Coming in M8" placeholder).
2. Seed activity via RPC -> reload -> task row visible with
   summary, source, deadline. Click Done -> row disappears,
   block re-renders.
3. Verify Done persists across reload.
4. Filter chips: Tasks visible under All, Operations, Sales,
   Finance.
"""

from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP_SCRIPT = """
# Setup: ensure p8a_director exists + grab the todo activity-type
# id for use by the browser scenario.
Users = env['res.users']

def _get_or_make(login, group_xmlid):
    user = Users.search([('login', '=', login)], limit=1)
    group = env.ref(group_xmlid)
    if not user:
        user = Users.with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'password': 'test123',
            'groups_id': [(4, group.id)],
        })
    else:
        user.write({'password': 'test123'})
        if group.id not in user.groups_id.ids:
            user.write({'groups_id': [(4, group.id)]})
    return user

u_director = _get_or_make('p8a_director', 'neon_core.group_neon_superuser')
todo = env.ref('mail.mail_activity_data_todo')
partner_model_id = env['ir.model'].search([('model', '=', 'res.partner')]).id

# NOTE: res.users.id != res.users.partner_id.id in Odoo.
# mail.activity.res_id needs the partner row id, fetched via
# the user's partner_id. Don't "fix" this back to director_id.
director_partner_id = u_director.partner_id.id

# Use res.users record (always exists) as the activity's source.
# Clean any existing M8-browser activities so the test is
# deterministic.
cleanup = env['mail.activity'].sudo().search([
    ('user_id', '=', u_director.id),
    ('summary', 'like', 'M8 browser %'),
])
if cleanup:
    cleanup.unlink()

env.cr.commit()
print('IDS_JSON=' + repr({
    'director_id': u_director.id,
    'director_partner_id': director_partner_id,
    'todo_id': todo.id,
    'partner_model_id': partner_model_id,
}))
"""


_CLEANUP_SCRIPT = """
# Best-effort cleanup -- remove any M8-browser activities left over.
ids = %(ids)s
activities = env['mail.activity'].sudo().search([
    ('user_id', '=', ids['director_id']),
    ('summary', 'like', 'M8 browser %%'),
])
if activities:
    activities.unlink()
env.cr.commit()
print('CLEANUP_OK')
"""


def _run_odoo_shell(script: str) -> str:
    proc = subprocess.run(
        [
            "docker", "compose",
            "--project-directory", "C:/Users/Neon/neon-odoo",
            "exec", "-T", "odoo",
            "odoo", "shell", "-d", DB, "--no-http",
        ],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=180,
    )
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def _setup_fixtures() -> dict:
    out = _run_odoo_shell(_SETUP_SCRIPT)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print("[p8a_m8] SETUP FAILED -- output tail:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


def _cleanup_fixtures(ids: dict) -> None:
    _run_odoo_shell(_CLEANUP_SCRIPT % {"ids": repr(ids)})


def run() -> int:
    ids = _setup_fixtures()
    try:
        with BrowserSmoke("p8a_m8") as smoke:

            # ========================================================
            # Scenario 1: Tasks block renders real (not placeholder).
            # ========================================================
            with smoke.scenario(
                    "Tasks block renders real (not placeholder)"):
                smoke.login("p8a_director")
                smoke.assert_menu_visible(
                    "neon_dashboard.menu_neon_dashboard_root")
                smoke.open_action(
                    "neon_dashboard.action_neon_dashboard_server")
                smoke.page.wait_for_selector(
                    ".o_neon_block_tasks", timeout=10000)
                placeholder = smoke.page.evaluate(
                    "() => document.body.innerText.includes('Coming in M8')"
                )
                ok = not placeholder
                smoke._record_assert(
                    "no 'Coming in M8' placeholder",
                    expect="absent",
                    actual="present" if placeholder else "absent",
                    passed=ok,
                )
                if not ok:
                    raise AssertionFail(
                        "Coming in M8 placeholder still rendered")
                smoke.screenshot("tasks_block_rendered")

            # ========================================================
            # Scenario 2: seed task -> Done flow.
            # ========================================================
            with smoke.scenario(
                    "Seed task via RPC -> Done removes it"):
                # Create one task via JSON-RPC.
                create_body = smoke.json_rpc(
                    "mail.activity",
                    "create",
                    args=[{
                        "user_id": ids["director_id"],
                        "res_model_id": ids["partner_model_id"],
                        "res_id": ids["director_partner_id"],
                        "activity_type_id": ids["todo_id"],
                        "summary": "M8 browser smoke task",
                    }],
                )
                act_id = create_body.get("result")
                if isinstance(act_id, list):
                    act_id = act_id[0]
                ok_create = isinstance(act_id, int) and act_id > 0
                smoke._record_assert(
                    "activity created via RPC",
                    expect="numeric id",
                    actual=str(act_id),
                    passed=ok_create,
                )
                if not ok_create:
                    raise AssertionFail(
                        f"activity create failed: {create_body}")

                # Reload dashboard, wait for tasks_block + the row
                # with our summary.
                smoke.open_action(
                    "neon_dashboard.action_neon_dashboard_server")
                smoke.page.wait_for_selector(
                    ".o_neon_block_tasks", timeout=10000)
                smoke.page.wait_for_function(
                    "() => document.body.innerText"
                    ".includes('M8 browser smoke task')",
                    timeout=10000,
                )

                # Count tasks rows before.
                before = smoke.page.locator(
                    ".o_neon_tasks_list .o_neon_tasks_row"
                ).count()
                # Click the Done button on the row matching our summary.
                # Locate the row by its containing text, then click Done
                # inside it.
                row = smoke.page.locator(
                    ".o_neon_tasks_row",
                    has_text="M8 browser smoke task",
                ).first
                row.locator(".o_neon_tasks_done").click()
                smoke.page.wait_for_timeout(500)
                after = smoke.page.locator(
                    ".o_neon_tasks_list .o_neon_tasks_row"
                ).count()
                ok_done = after < before
                smoke._record_assert(
                    "tasks count drops after Done",
                    expect=f"<{before}",
                    actual=str(after),
                    passed=ok_done,
                )
                if not ok_done:
                    raise AssertionFail(
                        f"Done didn't reduce visible tasks: "
                        f"{before} -> {after}")
                smoke.screenshot("after_done")

            # ========================================================
            # Scenario 3: Done persists across reload.
            # ========================================================
            with smoke.scenario("Done persists across reload"):
                smoke.open_action(
                    "neon_dashboard.action_neon_dashboard_server")
                smoke.page.wait_for_selector(
                    ".o_neon_block_tasks", timeout=10000)
                smoke.page.wait_for_timeout(500)
                present = smoke.page.evaluate(
                    "() => document.body.innerText"
                    ".includes('M8 browser smoke task')"
                )
                smoke._record_assert(
                    "completed task absent after reload",
                    expect="absent",
                    actual="present" if present else "absent",
                    passed=not present,
                )
                if present:
                    raise AssertionFail(
                        "Done flow didn't persist across reload")

            # ========================================================
            # Scenario 4: Tasks visible under all filter chips.
            # ========================================================
            with smoke.scenario(
                    "Tasks visible under all filter chips"):
                # We may have an empty tasks block; just check the
                # widget--block_tasks element is NOT display:none under
                # each filter.
                for chip in ("Operations", "Sales", "Finance", "All"):
                    smoke.page.locator(
                        ".o_neon_filter_chip", has_text=chip
                    ).first.click()
                    smoke.page.wait_for_timeout(200)
                    visible = smoke.page.evaluate(
                        "() => { var e = document.querySelector"
                        "('.widget--block_tasks'); "
                        "return e ? getComputedStyle(e).display !== 'none' : false; }"
                    )
                    smoke._record_assert(
                        f"Tasks visible under {chip} chip",
                        expect="visible",
                        actual="visible" if visible else "hidden",
                        passed=visible,
                    )
                    if not visible:
                        raise AssertionFail(
                            f"Tasks block hidden under {chip} chip")

            return smoke.summary()
    finally:
        _cleanup_fixtures(ids)


if __name__ == "__main__":
    sys.exit(run())
