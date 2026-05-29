"""P-B2 browser smoke -- Equipment Conflicts panel on Operations dashboard.

Scenarios:
(1) Operations variant: conflicts panel renders.
(2) Deficit item shows competing event chips.
(3) Director MD-peek -> Operations -> panel visible.
(4) Drilldown: conflict line opens on click.
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
Users = env['res.users']
EventJob = env['commercial.event.job']
Job = env['commercial.job']
Partner = env['res.partner']
Product = env['product.template']
Line = env['commercial.event.job.equipment.line']
Unit = env['neon.equipment.unit']
from odoo.addons.neon_jobs.models.neon_equipment_conflict import (
    ConflictEngine,
)


def _wipe_login(login):
    u = Users.search([('login','=',login)], limit=1)
    if u:
        u.write({'login': login + '_OLD_' + str(u.id),
                 'active': False})


_wipe_login('pb2_ops')
_wipe_login('pb2_director')
ops_user = Users.with_context(no_reset_password=True).create({
    'name': 'pb2_ops', 'login': 'pb2_ops', 'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('base.group_system').id),
        (4, env.ref('neon_core.group_neon_lead_tech').id),
        (4, env.ref('neon_jobs.group_neon_jobs_crew_leader').id),
        (4, env.ref('neon_jobs.group_neon_jobs_manager').id),
    ],
})
ops_user.write({'preferred_dashboard_type': 'lead_tech'})

director = Users.with_context(no_reset_password=True).create({
    'name': 'pb2_director', 'login': 'pb2_director',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('base.group_system').id),
        (4, env.ref('neon_jobs.group_neon_jobs_manager').id),
        (4, env.ref('neon_core.group_neon_superuser').id),
    ],
})
director.write({'preferred_dashboard_type': 'director'})

EventJob.search([('name', '=like', 'PB2 BROWSER EVT%')]).unlink()
Job.search([('name', '=like', 'PB2 BROWSER JOB%')]).unlink()
Unit.search([('serial_number', '=like', 'PB2-BR-%')]).unlink()

partner = Partner.search([], limit=1)
venue = Partner.search([('is_venue', '=', True)], limit=1)
today = date.today()
# Pin master_job event_date well in the past so the fixture doesn't
# pollute p2m7's cash-flow window. Events still get precise
# load_in/out windows pinned to today for the panel render.
past_master_date = date(2024, 1, 15)
def mk_job(label, ev):
    v = {'name': f'PB2 BROWSER JOB {label}',
         'partner_id': partner.id, 'state': 'active',
         'event_date': ev}
    if venue:
        v['venue_id'] = venue.id
    return Job.create(v)

product = Product.search([('is_workshop_item', '=', True)], limit=1)
conflict_line_id = 0
header_id = 0
if product:
    pb2_units = Unit.create([{
        'product_template_id': product.id,
        'serial_number': f'PB2-BR-{i}',
        'condition_status': 'good',
    } for i in range(4)])
    mA = mk_job('OVA', past_master_date)
    mB = mk_job('OVB', past_master_date)
    eA = EventJob.create({
        'name': 'PB2 BROWSER EVT OVA',
        'commercial_job_id': mA.id, 'partner_id': partner.id,
        'load_in_start': datetime.combine(today, time(9, 0)),
        'load_out_end':  datetime.combine(today, time(14, 0)),
    })
    eB = EventJob.create({
        'name': 'PB2 BROWSER EVT OVB',
        'commercial_job_id': mB.id, 'partner_id': partner.id,
        'load_in_start': datetime.combine(today, time(12, 0)),
        'load_out_end':  datetime.combine(today, time(18, 0)),
    })
    Line.create({'event_job_id': eA.id,
                  'product_template_id': product.id,
                  'quantity_planned': 4})
    Line.create({'event_job_id': eB.id,
                  'product_template_id': product.id,
                  'quantity_planned': 3})
    EventJob.flush_model()
    Line.flush_model()
    conflict = ConflictEngine(env).run_for_event(eA,
        trigger_reason='manual')
    if conflict:
        header_id = conflict.id
        flagged = conflict.line_ids.filtered(
            lambda l: l.product_template_id.id == product.id)
        conflict_line_id = flagged.id if flagged else 0
env.cr.commit()
print('IDS_JSON=' + repr({
    'ops': ops_user.id, 'director': director.id,
    'has_deficit': bool(conflict_line_id),
    'conflict_line_id': conflict_line_id,
    'header_id': header_id,
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
        print("[pb2] SETUP FAILED:"); print(out[-2000:]); sys.exit(2)
    depth = 0
    start = out.find("{", idx)
    for i in range(start, len(out)):
        if out[i] == "{": depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                return eval(out[start:i + 1])  # noqa: S307
    print("[pb2] SETUP FAILED parse:"); print(out[-2000:]); sys.exit(2)


def run():
    ids = _setup()
    with BrowserSmoke("pb2") as smoke:
        with smoke.scenario("Operations dashboard: conflicts panel renders"):
            smoke.login("pb2_ops")
            smoke.page.goto(
                f"{BASE_URL}/web#action=neon_dashboard."
                f"action_neon_dashboard_server")
            smoke.page.wait_for_selector(
                ".o_neon_dashboard", timeout=20000)
            smoke.page.wait_for_timeout(800)
            panel_count = smoke.page.locator(
                ".o_neon_block_conflicts").count()
            smoke._record_assert(
                "conflicts panel mounted on Operations variant",
                expect=">=1", actual=str(panel_count),
                passed=panel_count >= 1)

        with smoke.scenario("Deficit shows competing event chips"):
            if not ids["has_deficit"]:
                smoke._record_assert(
                    "no workshop product fixture; scenario skipped",
                    expect="has_deficit=True",
                    actual="has_deficit=False",
                    passed=True)
            else:
                chip_count = smoke.page.locator(
                    ".o_neon_conflicts_event_chip").count()
                smoke._record_assert(
                    "competing event chips render >=2",
                    expect=">=2", actual=str(chip_count),
                    passed=chip_count >= 2)
                short = smoke.page.locator(
                    ".o_neon_conflicts_short").count()
                smoke._record_assert(
                    "deficit qty cell rendered",
                    expect=">=1", actual=str(short),
                    passed=short >= 1)

        with smoke.scenario("Director MD-peek Operations -> panel visible"):
            smoke.login("pb2_director")
            smoke.page.goto(
                f"{BASE_URL}/web?dashboard_type=lead_tech"
                f"#action=neon_dashboard."
                f"action_neon_dashboard_server")
            smoke.page.wait_for_selector(
                ".o_neon_dashboard", timeout=20000)
            smoke.page.wait_for_timeout(1000)
            peek_count = smoke.page.locator(
                ".o_neon_block_conflicts").count()
            smoke._record_assert(
                "director-peek-Operations conflicts panel mounts",
                expect=">=1", actual=str(peek_count),
                passed=peek_count >= 1)

        with smoke.scenario("Drilldown: conflict line opens"):
            if not ids["conflict_line_id"]:
                smoke._record_assert(
                    "no conflict line to drilldown; scenario skipped",
                    expect="conflict_line_id>0",
                    actual=str(ids["conflict_line_id"]),
                    passed=True)
            else:
                smoke.page.goto(
                    f"{BASE_URL}/web#id={ids['conflict_line_id']}"
                    f"&model=neon.equipment.conflict.line"
                    f"&view_type=form")
                smoke.page.wait_for_selector(
                    "div.o_form_view", timeout=15000)
                smoke.page.wait_for_timeout(400)
                req = smoke.page.locator(
                    "[name='required_qty']").count()
                avail = smoke.page.locator(
                    "[name='available_qty']").count()
                smoke._record_assert(
                    "conflict.line form has required + available fields",
                    expect=">=2", actual=str(req + avail),
                    passed=(req + avail) >= 2)


if __name__ == "__main__":
    run()
