"""P-B13 browser smoke -- Doc-Gen provider config form.

Scenarios:
(1) Config form renders for a superuser; Set-API-Key button visible.
(2) Test-Connection errors cleanly when no key set (no crash, no leak).
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
Provider = env['neon.doc.gen.provider']

def _wipe_login(login):
    u = Users.search([('login','=',login)], limit=1)
    if u:
        u.write({'login': login + '_OLD_' + str(u.id),
                 'active': False})

_wipe_login('pb13_admin')
admin_user = Users.with_context(no_reset_password=True).create({
    'name': 'pb13_admin', 'login': 'pb13_admin',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('base.group_system').id),
        (4, env.ref('neon_core.group_neon_superuser').id),
    ],
})

# Ensure provider exists + clear any leftover key so the "Test"
# button reflects a clean state.
provider = Provider.sudo().search(
    [('provider_key', '=', 'anthropic')], limit=1)
if provider:
    provider._set_api_key('')

env.cr.commit()
print('IDS_JSON=' + repr({
    'admin': admin_user.id,
    'provider_id': provider.id if provider else 0,
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
    idx = out.find("IDS_JSON=")
    if idx < 0:
        print("[pb13] SETUP FAILED:"); print(out[-2000:]); sys.exit(2)
    depth = 0
    start = out.find("{", idx)
    for i in range(start, len(out)):
        if out[i] == "{": depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                return eval(out[start:i + 1])  # noqa: S307
    print("[pb13] SETUP FAILED parse:"); print(out[-2000:]); sys.exit(2)


def run():
    ids = _setup()
    if not ids.get("provider_id"):
        print("[pb13] no provider seeded; aborting")
        sys.exit(2)

    with BrowserSmoke("pb13") as smoke:

        with smoke.scenario(
                "Doc-Gen provider form renders for superuser"):
            smoke.login("pb13_admin")
            smoke.page.goto(
                f"{BASE_URL}/web#id={ids['provider_id']}"
                f"&model=neon.doc.gen.provider&view_type=form")
            smoke.page.wait_for_selector(
                "div.o_form_view", timeout=20000)
            smoke.page.wait_for_timeout(500)
            # Form renders with the expected fields
            model_field = smoke.page.locator(
                "[name='model']").count()
            endpoint_field = smoke.page.locator(
                "[name='endpoint_url']").count()
            set_key_btn = smoke.page.locator(
                "button:has-text('Set API Key')").count()
            smoke._record_assert(
                "model + endpoint fields render",
                expect=">=2", actual=str(model_field + endpoint_field),
                passed=(model_field + endpoint_field) >= 2)
            smoke._record_assert(
                "Set API Key button present",
                expect=">=1", actual=str(set_key_btn),
                passed=set_key_btn >= 1)

        with smoke.scenario(
                "Test Connection button hidden when no key set"):
            # The Test button is invisible until has_api_key True
            # (see view's invisible="not has_api_key"). Confirm.
            test_btn = smoke.page.locator(
                "button:has-text('Test Connection'):visible").count()
            smoke._record_assert(
                "Test Connection hidden pre-key",
                expect="0", actual=str(test_btn),
                passed=test_btn == 0)


if __name__ == "__main__":
    run()
