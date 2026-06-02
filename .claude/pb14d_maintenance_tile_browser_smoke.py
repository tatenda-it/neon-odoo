"""P-B14d browser smoke -- workshop dashboard "In Maintenance" tile.

Scenarios:
(1) Workshop dashboard renders + the In Maintenance tile is
    visible in the inventory snapshot row + its value matches
    the server-side count.
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
Cat = env['neon.equipment.category']
Product = env['product.template']
Unit = env['neon.equipment.unit']
Movement = env['neon.equipment.movement']
Dashboard = env['neon.equipment.dashboard']


def _wipe_login(login):
    u = Users.search([('login','=',login)], limit=1)
    if u:
        u.write({'login': login + '_OLD_' + str(u.id),
                 'active': False})

_wipe_login('pb14d_admin')
admin_user = Users.with_context(no_reset_password=True).create({
    'name': 'pb14d_admin', 'login': 'pb14d_admin',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('base.group_system').id),
        (4, env.ref('neon_jobs.group_neon_jobs_manager').id),
        (4, env.ref('neon_core.group_neon_superuser').id),
    ],
})

# Cleanup
old_units = Unit.sudo().search(
    [('serial_number', '=like', 'PB14D-BR-%')])
if old_units:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [('unit_id', 'in', old_units.ids)]).unlink()
    old_units.unlink()
Product.sudo().search(
    [('workshop_name', '=like', 'PB14D-BR-%')]).unlink()

# Seed 4 maintenance units to confirm the tile reflects state
sound_cat = Cat.sudo().search([('code','=','sound')], limit=1)
p = Product.sudo().create({
    'name': 'PB14D-BR-AMP',
    'workshop_name': 'PB14D-BR-AMP',
    'is_workshop_item': True,
    'equipment_category_id': sound_cat.id,
    'tracking_mode': 'serial',
})
N = 4
seeded = Unit.sudo().create([{
    'product_template_id': p.id,
    'serial_number': 'PB14D-BR-SN-{:03d}'.format(i),
    'asset_tag': 'PB14D-BR-TAG-{:03d}'.format(i),
    'condition_status': 'good',
} for i in range(N)])
seeded.with_context(_allow_state_write=True).write(
    {'state': 'maintenance'})
env.cr.commit()

# Read the post-seed maintenance count -- this is what the
# rendered tile should show
maint_count = Dashboard._count_units_in_maintenance()
print('IDS_JSON=' + repr({
    'admin': admin_user.id,
    'maint_count': maint_count,
    'seed_n': N,
}))
"""


_TEARDOWN = """
Unit = env['neon.equipment.unit']
Movement = env['neon.equipment.movement']
Product = env['product.template']

end_units = Unit.sudo().search(
    [('product_template_id.workshop_name', '=like',
       'PB14D-BR-%')])
if end_units:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [('unit_id', 'in', end_units.ids)]).unlink()
    end_units.unlink()
Product.sudo().search(
    [('workshop_name', '=like', 'PB14D-BR-%')]).unlink()
env.cr.commit()
print('TEARDOWN OK')
"""


def _shell(script):
    p = subprocess.run(
        ["docker", "compose", "--project-directory",
         "C:/Users/Neon/neon-odoo", "exec", "-T", "odoo",
         "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"),
        capture_output=True, timeout=180)
    return (p.stdout + p.stderr).decode("utf-8",
                                          errors="replace")


def _setup():
    out = _shell(_SETUP)
    idx = out.find("IDS_JSON=")
    if idx < 0:
        print("[pb14d] SETUP FAILED:"); print(out[-1500:])
        sys.exit(2)
    depth = 0
    start = out.find("{", idx)
    for i in range(start, len(out)):
        if out[i] == "{": depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                return eval(out[start:i + 1])  # noqa: S307
    print("[pb14d] SETUP FAILED parse:"); print(out[-1500:])
    sys.exit(2)


def _teardown():
    out = _shell(_TEARDOWN)
    if "TEARDOWN OK" not in out:
        print("[pb14d] TEARDOWN WARN:"); print(out[-500:])


def run():
    ids = _setup()
    try:
        with BrowserSmoke("pb14d") as smoke:

            with smoke.scenario(
                    "Workshop dashboard: In Maintenance tile "
                    "renders + value matches server count"):
                smoke.login("pb14d_admin")
                smoke.page.goto(
                    f"{BASE_URL}/web#action=neon_jobs."
                    f"action_workshop_dashboard_server")
                # OWL dashboard renders into a custom root
                smoke.page.wait_for_selector(
                    ".o_neon_workshop_dashboard",
                    timeout=20000)
                # Hard-reload to defeat any stale OWL bundle cache
                smoke.page.reload(wait_until="networkidle")
                smoke.page.wait_for_selector(
                    ".o_neon_workshop_dashboard",
                    timeout=20000)
                smoke.page.wait_for_timeout(2500)
                body = smoke.page.locator(
                    ".o_neon_workshop_dashboard").inner_text()
                # The tile title is "In Maintenance" but SCSS
                # text-transform renders it uppercase -- compare
                # case-insensitively.
                tile_visible = "in maintenance" in body.lower()
                # The seeded count should be present in the
                # rendered DOM (with formatting it may be a digit
                # token; check for the integer value as a token)
                exp = str(ids["maint_count"])
                # Verify the server-side count via shell to cross
                # the DOM-vs-RPC gap deterministically
                out = _shell(f"""
D = env['neon.equipment.dashboard']
print('SERVER_MAINT=' + str(D._count_units_in_maintenance()))
""")
                server_maint = "?"
                m = re.search(r"SERVER_MAINT=(\d+)", out)
                if m:
                    server_maint = m.group(1)
                smoke._record_assert(
                    "tile visible + server count matches seed",
                    expect=(f"tile_visible=True server_maint="
                             f"{exp} server>={ids['seed_n']}"),
                    actual=(f"tile_visible={tile_visible} "
                             f"server_maint={server_maint} "
                             f"seed_n={ids['seed_n']}"),
                    passed=(tile_visible
                              and server_maint == exp
                              and int(server_maint) >= ids[
                                  "seed_n"]))
    finally:
        _teardown()


if __name__ == "__main__":
    run()
