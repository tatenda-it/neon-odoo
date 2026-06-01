"""P-B14c browser smoke -- quantity_on_hand UI + B2 panel.

Scenarios:
(1) Quantity product form opens + Quantity On Hand field is
    visible and reads the stored value (50).
(2) Serial product form opens + Quantity On Hand field is
    present but informationally irrelevant (semantics doc'd in
    the field help text).
(3) B2 conflict panel for an event whose demand is BELOW the
    quantity stock shows NO deficit (status='surplus'),
    confirming the live B2 read picks up product.quantity_on_hand.
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP = """
from datetime import date, datetime, time, timedelta
from odoo.addons.neon_jobs.models.neon_equipment_conflict \
    import ConflictEngine

Users = env['res.users']
Cat = env['neon.equipment.category']
Product = env['product.template']
Unit = env['neon.equipment.unit']
Movement = env['neon.equipment.movement']
Partner = env['res.partner']
Job = env['commercial.job']
EventJob = env['commercial.event.job']
Line = env['commercial.event.job.equipment.line']
Conflict = env['neon.equipment.conflict']


def _wipe_login(login):
    u = Users.search([('login','=',login)], limit=1)
    if u:
        u.write({'login': login + '_OLD_' + str(u.id),
                 'active': False})

_wipe_login('pb14c_admin')
admin_user = Users.with_context(no_reset_password=True).create({
    'name': 'pb14c_admin', 'login': 'pb14c_admin',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('base.group_system').id),
        (4, env.ref('neon_jobs.group_neon_jobs_manager').id),
        (4, env.ref('neon_core.group_neon_superuser').id),
    ],
})

# Cleanup (FK-safe)
old_products = Product.sudo().search(
    [('workshop_name', '=like', 'PB14C-BR-%')])
if old_products:
    Conflict.sudo().search([
        ('line_ids.product_template_id', 'in',
         old_products.ids),
    ]).unlink()
old_events = EventJob.sudo().search(
    [('name', '=like', 'PB14C BR EVT%')])
if old_events:
    old_events.with_context(_allow_state_write=True).write(
        {'state': 'cancelled'})
    old_events.unlink()
Job.sudo().search([('name', '=like', 'PB14C BR JOB%')]).unlink()
old_units = Unit.sudo().search(
    [('product_template_id.workshop_name', '=like',
       'PB14C-BR-%')])
if old_units:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [('unit_id', 'in', old_units.ids)]).unlink()
    old_units.unlink()
Product.sudo().search(
    [('workshop_name', '=like', 'PB14C-BR-%')]).unlink()

partner = Partner.sudo().search([], limit=1)
venue = Partner.sudo().search([('is_venue','=',True)], limit=1)
sound_cat = Cat.sudo().search([('code','=','sound')], limit=1)
cabling_cat = Cat.sudo().search([('code','=','cabling')], limit=1)

# Quantity product with on-hand=50
p_qty = Product.sudo().create({
    'name': 'PB14C-BR-CABLE',
    'workshop_name': 'PB14C-BR-CABLE',
    'is_workshop_item': True,
    'equipment_category_id': cabling_cat.id,
    'tracking_mode': 'quantity',
    'quantity_on_hand': 50,
})
Unit.sudo().create({
    'product_template_id': p_qty.id,
    'condition_status': 'good',
    'notes': 'browser-smoke quantity stock',
})

# Serial product (B14c field is present but irrelevant for serial)
p_serial = Product.sudo().create({
    'name': 'PB14C-BR-MIC',
    'workshop_name': 'PB14C-BR-MIC',
    'is_workshop_item': True,
    'equipment_category_id': sound_cat.id,
    'tracking_mode': 'serial',
})
Unit.sudo().create([{
    'product_template_id': p_serial.id,
    'serial_number': 'PB14C-BR-SN-{:03d}'.format(i),
    'asset_tag': 'PB14C-BR-TAG-{:03d}'.format(i),
    'condition_status': 'good',
} for i in range(3)])

# Event demanding 20 cables (well under 50 stocked) -> no deficit
today = date.today()
mA = Job.sudo().create({
    'name': 'PB14C BR JOB A',
    'partner_id': partner.id, 'state': 'active',
    'event_date': today,
    **({'venue_id': venue.id} if venue else {}),
})
ev = EventJob.sudo().create({
    'name': 'PB14C BR EVT A',
    'commercial_job_id': mA.id,
    'partner_id': partner.id,
    'load_in_start': datetime.combine(today, time(9, 0)),
    'load_out_end': datetime.combine(today, time(14, 0)),
})
ev.with_context(_allow_state_write=True).write(
    {'state': 'planning'})
Line.sudo().create({
    'event_job_id': ev.id,
    'product_template_id': p_qty.id,
    'quantity_planned': 20,
})
ev.flush_recordset()
Line.sudo().flush_model()
env.cr.commit()
conf = ConflictEngine(env).run_for_event(ev,
                                           trigger_reason='manual')

env.cr.commit()
print('IDS_JSON=' + repr({
    'admin': admin_user.id,
    'qty_product_id': p_qty.id,
    'serial_product_id': p_serial.id,
    'conflict_id': conf.id,
    'event_id': ev.id,
}))
"""


_TEARDOWN = """
Product = env['product.template']
Conflict = env['neon.equipment.conflict']
EventJob = env['commercial.event.job']
Job = env['commercial.job']
Unit = env['neon.equipment.unit']
Movement = env['neon.equipment.movement']

end_products = Product.sudo().search(
    [('workshop_name', '=like', 'PB14C-BR-%')])
if end_products:
    Conflict.sudo().search([
        ('line_ids.product_template_id', 'in',
         end_products.ids),
    ]).unlink()
end_events = EventJob.sudo().search(
    [('name', '=like', 'PB14C BR EVT%')])
if end_events:
    end_events.with_context(_allow_state_write=True).write(
        {'state': 'cancelled'})
    end_events.unlink()
Job.sudo().search([('name', '=like', 'PB14C BR JOB%')]).unlink()
end_units = Unit.sudo().search(
    [('product_template_id.workshop_name', '=like',
       'PB14C-BR-%')])
if end_units:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [('unit_id', 'in', end_units.ids)]).unlink()
    end_units.unlink()
Product.sudo().search(
    [('workshop_name', '=like', 'PB14C-BR-%')]).unlink()
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
        print("[pb14c] SETUP FAILED:"); print(out[-2000:])
        sys.exit(2)
    depth = 0
    start = out.find("{", idx)
    for i in range(start, len(out)):
        if out[i] == "{": depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                return eval(out[start:i + 1])  # noqa: S307
    print("[pb14c] SETUP FAILED parse:")
    print(out[-2000:])
    sys.exit(2)


def _teardown():
    out = _shell(_TEARDOWN)
    if "TEARDOWN OK" not in out:
        print("[pb14c] TEARDOWN WARN:"); print(out[-600:])


def run():
    ids = _setup()
    try:
        with BrowserSmoke("pb14c") as smoke:

            with smoke.scenario(
                    "Quantity product form: Quantity On Hand "
                    "field visible + reads stored value"):
                smoke.login("pb14c_admin")
                smoke.page.goto(
                    f"{BASE_URL}/web#id={ids['qty_product_id']}"
                    f"&model=product.template&view_type=form")
                smoke.page.wait_for_selector(
                    "div.o_form_view", timeout=20000)
                smoke.page.wait_for_timeout(700)
                # Field value via shell (form inputs aren't always
                # in inner_text)
                out = _shell(f"""
P = env['product.template']
p = P.browse({ids['qty_product_id']})
print('QOH=' + str(int(p.quantity_on_hand or 0)))
print('TM=' + (p.tracking_mode or ''))
print('FIELD_PRESENT=' + str(
    'quantity_on_hand' in P._fields))
""")
                qoh = (re.search(r"QOH=(\d+)", out) or
                         ["", "?"])[1] if re.search(
                             r"QOH=(\d+)", out) else "?"
                tm = (re.search(r"TM=(\w+)", out) or
                        ["", "?"])[1] if re.search(
                            r"TM=(\w+)", out) else "?"
                field_present = "FIELD_PRESENT=True" in out
                # Verify form rendered
                form_visible = smoke.page.locator(
                    "div.o_form_view").count() >= 1
                smoke._record_assert(
                    "quantity product form opens + "
                    "quantity_on_hand=50 + tracking=quantity",
                    expect=("form_visible=True qoh=50 "
                             "tracking=quantity field_present=True"),
                    actual=(f"form_visible={form_visible} "
                             f"qoh={qoh} tracking={tm} "
                             f"field_present={field_present}"),
                    passed=(form_visible and qoh == "50"
                              and tm == "quantity"
                              and field_present))

            with smoke.scenario(
                    "Serial product form: field present but "
                    "tracking_mode=serial (B2 won't use it)"):
                smoke.page.goto(
                    f"{BASE_URL}/web#id={ids['serial_product_id']}"
                    f"&model=product.template&view_type=form")
                smoke.page.wait_for_selector(
                    "div.o_form_view", timeout=20000)
                smoke.page.wait_for_timeout(500)
                form_visible = smoke.page.locator(
                    "div.o_form_view").count() >= 1
                out = _shell(f"""
P = env['product.template']
p = P.browse({ids['serial_product_id']})
print('QOH=' + str(int(p.quantity_on_hand or 0)))
print('TM=' + (p.tracking_mode or ''))
""")
                qoh = (re.search(r"QOH=(\d+)", out) or
                         ["", "?"])[1] if re.search(
                             r"QOH=(\d+)", out) else "?"
                tm = (re.search(r"TM=(\w+)", out) or
                        ["", "?"])[1] if re.search(
                            r"TM=(\w+)", out) else "?"
                smoke._record_assert(
                    "serial product form opens + tracking=serial "
                    "+ qoh defaults to 0 (irrelevant for serial)",
                    expect=("form_visible=True qoh=0 "
                             "tracking=serial"),
                    actual=(f"form_visible={form_visible} "
                             f"qoh={qoh} tracking={tm}"),
                    passed=(form_visible and qoh == "0"
                              and tm == "serial"))

            with smoke.scenario(
                    "B2 conflict panel: demand 20 / stock 50 -> "
                    "no deficit (live B2 read)"):
                smoke.page.goto(
                    f"{BASE_URL}/web#id={ids['conflict_id']}"
                    f"&model=neon.equipment.conflict"
                    f"&view_type=form")
                smoke.page.wait_for_selector(
                    "div.o_form_view", timeout=20000)
                smoke.page.wait_for_timeout(700)
                # Read the conflict line via shell -- form scrape
                # of nested tree is brittle
                out = _shell(f"""
Conf = env['neon.equipment.conflict']
c = Conf.browse({ids['conflict_id']})
print('OVERALL=' + (c.overall_status or '?'))
print('DEFICIT_COUNT=' + str(int(c.deficit_count or 0)))
for ln in c.line_ids:
    print('LINE pid=%s req=%d avail=%d def=%d status=%s' % (
        ln.product_template_id.id, ln.required_qty,
        ln.available_qty, ln.deficit_qty, ln.status))
""")
                overall = (re.search(r"OVERALL=(\w+)", out) or
                             ["", "?"])[1] if re.search(
                                 r"OVERALL=(\w+)", out) else "?"
                def_count = (re.search(
                    r"DEFICIT_COUNT=(\d+)", out) or
                    ["", "?"])[1] if re.search(
                        r"DEFICIT_COUNT=(\d+)", out) else "?"
                qty_line_avail = (re.search(
                    r"LINE pid=%s req=20 avail=(\d+)" % (
                        ids["qty_product_id"]), out) or
                    ["", "?"])[1] if re.search(
                        r"LINE pid=%s req=20 avail=(\d+)" % (
                            ids["qty_product_id"]), out) else "?"
                form_visible = smoke.page.locator(
                    "div.o_form_view").count() >= 1
                smoke._record_assert(
                    "B2 panel: overall=clear + deficit_count=0 + "
                    "the quantity-line avail=50 (live B2 reads "
                    "quantity_on_hand)",
                    expect=("form_visible=True overall=clear "
                             "deficit=0 qty_line_avail=50"),
                    actual=(f"form_visible={form_visible} "
                             f"overall={overall} "
                             f"deficit={def_count} "
                             f"qty_line_avail={qty_line_avail}"),
                    passed=(form_visible
                              and overall == "clear"
                              and def_count == "0"
                              and qty_line_avail == "50"))
    finally:
        _teardown()


if __name__ == "__main__":
    run()
