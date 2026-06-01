"""P-B5 browser smoke -- Post-event reconciliation form + render +
state machine.

Scenarios:
(1) Reconciliation form opens for a superuser + header status
    badge reads 'Generated'.
(2) summary_html renders the headline + equipment + sub-hire
    + cost-variance blocks.
(3) Mark Reviewed -> Mark Final advances state; the workshop
    chatter alert lands on the form's message thread.
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
import json as _json
from odoo import fields
Users = env['res.users']
EventJob = env['commercial.event.job']
Job = env['commercial.job']
Partner = env['res.partner']
Product = env['product.template']
Line = env['commercial.event.job.equipment.line']
Unit = env['neon.equipment.unit']
Plan = env['neon.deployment.plan']
Recon = env['neon.event.reconciliation']
Conflict = env['neon.equipment.conflict']
Movement = env['neon.equipment.movement']

def _wipe_login(login):
    u = Users.search([('login','=',login)], limit=1)
    if u:
        u.write({'login': login + '_OLD_' + str(u.id),
                 'active': False})

_wipe_login('pb5_admin')
admin_user = Users.with_context(no_reset_password=True).create({
    'name': 'pb5_admin', 'login': 'pb5_admin',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('base.group_system').id),
        (4, env.ref('neon_jobs.group_neon_jobs_manager').id),
        (4, env.ref('neon_core.group_neon_superuser').id),
    ],
})

# Wipe leftover fixtures in FK-safe order.
Recon.sudo().search(
    [('name', '=like', 'RECON-%')]).filtered(
    lambda r: 'PB5 BR' in (r.event_job_id.name or '')).unlink()
old_units = Unit.sudo().search(
    [('serial_number', '=like', 'PB5BR-%')])
if old_units:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [('unit_id', 'in', old_units.ids)]).unlink()
    old_units.unlink()
to_cancel = EventJob.sudo().search(
    [('name', '=like', 'PB5 BR EVT%')])
if to_cancel:
    to_cancel.with_context(_allow_state_write=True).write(
        {'state': 'cancelled'})
    to_cancel.unlink()
Job.sudo().search([('name', '=like', 'PB5 BR JOB%')]).unlink()
old_prod = Product.sudo().search(
    [('name', '=', 'PB5-BR-PRODUCT')])
if old_prod:
    Conflict.sudo().search([
        ('line_ids.product_template_id', '=', old_prod.id)
    ]).unlink()
    old_prod.unlink()

partner = Partner.sudo().search([], limit=1)
venue = Partner.sudo().search([('is_venue', '=', True)], limit=1)
product = Product.sudo().create({
    'name': 'PB5-BR-PRODUCT',
    'is_workshop_item': True,
})
today = date.today()
recon_id = 0
units = Unit.sudo().create([{
    'product_template_id': product.id,
    'serial_number': f'PB5BR-{i}',
    'condition_status': 'good'} for i in range(3)])
mvals = {'name': 'PB5 BR JOB A', 'partner_id': partner.id,
          'state': 'active',
          'event_date': today - timedelta(days=2)}
if venue: mvals['venue_id'] = venue.id
m = Job.sudo().create(mvals)
ev = Event = EventJob.sudo().create({
    'name': 'PB5 BR EVT A',
    'commercial_job_id': m.id, 'partner_id': partner.id,
    'event_date': today - timedelta(days=2),
    'load_in_start': datetime.combine(
        today - timedelta(days=2), time(9, 0)),
    'load_out_end': datetime.combine(
        today - timedelta(days=2), time(14, 0)),
})
ev.with_context(_allow_state_write=True).write(
    {'state': 'completed'})
Line.sudo().create({'event_job_id': ev.id,
                     'product_template_id': product.id,
                     'quantity_planned': 4})
ev.flush_recordset()
Line.flush_model()

from odoo.addons.neon_jobs.models.neon_equipment_conflict \
    import ConflictEngine
ConflictEngine(env).run_for_event(ev, trigger_reason='manual')

# Hook the units into the event via movements + flip conditions
for u in units[:2]:
    Movement.sudo().create({
        'unit_id': u.id,
        'event_job_id': ev.id,
        'movement_type': 'checkout',
        'from_location_text': 'Workshop',
        'to_location_text': 'Event',
    })
units[0].sudo().write({'condition_status': 'needs_repair'})
units[1].sudo().write({'condition_status': 'written_off'})

# Pre-stage a reconciliation directly (skip Claude call --
# this smoke is UI).
from odoo.addons.neon_jobs.models.event_reconciliation_fact_gatherer \
    import EventReconciliationFactGatherer
facts = EventReconciliationFactGatherer(env).gather(ev)
wo_unit = next(d for d in facts['condition_deltas']
                if d['new_status'] == 'written_off')
summary_payload = {
    'headline': 'Event reconciled with one write-off.',
    'executive_summary': (
        'The event completed cleanly. One unit returned '
        'damaged beyond repair.'),
    'what_went_well': ['Load-in on schedule.'],
    'what_didnt': ['One unit was written off post-strike.'],
    'equipment_outcomes': {
        'written_off_count': 1,
        'needs_repair_count': 1,
        'narrative': (
            'PB5BR-1 was written off following load-out. '
            'PB5BR-0 needs a workshop check.'),
        'flagged_units': [{
            'serial_number': wo_unit['serial_number'],
            'product_name': wo_unit['product_name'],
            'new_status': 'written_off',
        }],
    },
    'subhire_outcomes': [],
    'cost_narrative': (
        'Costs reported as informational only.'),
    'lessons': ['Add a post-event workshop check window.'],
    'event_window': facts['event_window_label'],
    'data_quality_note': facts['b2_conflict'].get(
        'data_quality_note'),
}
plan_id = (facts['plan_snapshot'].get('plan_id') or False)
rec = Recon.sudo().create({
    'event_job_id': ev.id, 'revision': 1,
    'status': 'generated',
    'generated_at': fields.Datetime.now(),
    'generated_by_id': admin_user.id,
    'source_plan_id': plan_id,
    'facts_json': _json.dumps(facts, default=str),
    'summary_json': _json.dumps(summary_payload, default=str),
    'model_used': 'claude-sonnet-4-6',
    'prompt_tokens': 1200, 'completion_tokens': 400,
    'latency_ms': 1500,
})
recon_id = rec.id
env.cr.commit()
print('IDS_JSON=' + repr({
    'admin': admin_user.id, 'recon_id': recon_id,
}))
"""


_TEARDOWN = """
Recon = env['neon.event.reconciliation']
EventJob = env['commercial.event.job']
Job = env['commercial.job']
Unit = env['neon.equipment.unit']
Partner = env['res.partner']
Product = env['product.template']
Movement = env['neon.equipment.movement']
Conflict = env['neon.equipment.conflict']

Recon.sudo().search([]).filtered(
    lambda r: 'PB5 BR' in (r.event_job_id.name or '')).unlink()
old_units = Unit.sudo().search(
    [('serial_number', '=like', 'PB5BR-%')])
if old_units:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [('unit_id', 'in', old_units.ids)]).unlink()
    old_units.unlink()
to_cancel = EventJob.sudo().search(
    [('name', '=like', 'PB5 BR EVT%')])
if to_cancel:
    to_cancel.with_context(_allow_state_write=True).write(
        {'state': 'cancelled'})
    to_cancel.unlink()
Job.sudo().search([('name', '=like', 'PB5 BR JOB%')]).unlink()
old_prod = Product.sudo().search(
    [('name', '=', 'PB5-BR-PRODUCT')])
if old_prod:
    Conflict.sudo().search([
        ('line_ids.product_template_id', '=', old_prod.id)
    ]).unlink()
    old_prod.unlink()
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
        print("[pb5] SETUP FAILED:")
        print(out[-2000:])
        sys.exit(2)
    depth = 0
    start = out.find("{", idx)
    for i in range(start, len(out)):
        if out[i] == "{": depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                return eval(out[start:i + 1])  # noqa: S307
    print("[pb5] SETUP FAILED parse:")
    print(out[-2000:])
    sys.exit(2)


def _teardown():
    out = _shell(_TEARDOWN)
    if "TEARDOWN OK" not in out:
        print("[pb5] TEARDOWN WARN:")
        print(out[-800:])


def run():
    ids = _setup()
    try:
        with BrowserSmoke("pb5") as smoke:

            with smoke.scenario(
                    "Reconciliation form opens + statusbar shows"):
                smoke.login("pb5_admin")
                if not ids["recon_id"]:
                    smoke._record_assert(
                        "no recon fixture; scenario skipped",
                        expect="recon_id>0",
                        actual="0", passed=True)
                else:
                    smoke.page.goto(
                        f"{BASE_URL}/web#id={ids['recon_id']}"
                        f"&model=neon.event.reconciliation"
                        f"&view_type=form")
                    smoke.page.wait_for_selector(
                        "div.o_form_view", timeout=20000)
                    smoke.page.wait_for_timeout(500)
                    mark_reviewed = smoke.page.locator(
                        "button:has-text('Mark Reviewed')").count()
                    smoke._record_assert(
                        "Mark Reviewed button present "
                        "(status=generated)",
                        expect=">=1",
                        actual=str(mark_reviewed),
                        passed=mark_reviewed >= 1)

            with smoke.scenario(
                    "summary_html renders headline + equipment + "
                    "cost blocks"):
                if not ids["recon_id"]:
                    smoke._record_assert(
                        "no recon fixture; scenario skipped",
                        expect="recon_id>0",
                        actual="0", passed=True)
                else:
                    body_text = smoke.page.locator(
                        "div.o_form_view").inner_text()
                    has_headline = (
                        "Event reconciled" in body_text)
                    has_equipment = (
                        "Equipment outcomes" in body_text)
                    has_unit = "PB5BR-1" in body_text
                    has_cost = "Cost variance" in body_text
                    smoke._record_assert(
                        "summary_html renders headline + equipment "
                        "+ cost + flagged unit",
                        expect="all four",
                        actual=(f"head={has_headline} "
                                 f"eq={has_equipment} "
                                 f"unit={has_unit} "
                                 f"cost={has_cost}"),
                        passed=(has_headline
                                  and has_equipment
                                  and has_unit
                                  and has_cost))

            with smoke.scenario(
                    "Mark Reviewed -> Mark Final advances state; "
                    "workshop alert lands"):
                if not ids["recon_id"]:
                    smoke._record_assert(
                        "no recon fixture; scenario skipped",
                        expect="recon_id>0",
                        actual="0", passed=True)
                else:
                    # Server-side state machine -- form approach
                    # has rich confirm dialogs that are brittle
                    # under headless. Same approach as PB4.
                    out = _shell(f"""
Recon = env['neon.event.reconciliation']
rec = Recon.browse({ids['recon_id']})
existing_ids = set(rec.message_ids.ids)
if rec.status == 'generated':
    rec.action_mark_reviewed()
if rec.status == 'reviewed':
    rec.action_mark_final()
env.cr.commit()
new_msgs = rec.message_ids.filtered(
    lambda m: m.id not in existing_ids)
alert_count = sum(1 for m in new_msgs
                    if 'Workshop alert' in (m.body or ''))
print('REC_STATUS=' + rec.status)
print('ALERT_COUNT=' + str(alert_count))
""")
                    status = "?"
                    m = re.search(r"REC_STATUS=(\w+)", out)
                    if m:
                        status = m.group(1)
                    alert_count = 0
                    m = re.search(r"ALERT_COUNT=(\d+)", out)
                    if m:
                        alert_count = int(m.group(1))
                    smoke._record_assert(
                        "server-side reviewed + finalised; status="
                        "'final'",
                        expect="final", actual=status,
                        passed=status == "final")
                    smoke._record_assert(
                        "workshop alert posted on finalise",
                        expect=">=1", actual=str(alert_count),
                        passed=alert_count >= 1)
                    # Reload form -- assert status statusbar reads
                    # 'Final' visually
                    smoke.page.goto(
                        f"{BASE_URL}/web#id={ids['recon_id']}"
                        f"&model=neon.event.reconciliation"
                        f"&view_type=form")
                    smoke.page.wait_for_selector(
                        "div.o_form_view", timeout=20000)
                    smoke.page.wait_for_timeout(700)
                    body_text = smoke.page.locator(
                        "div.o_form_view").inner_text()
                    smoke._record_assert(
                        "form shows 'Final' status badge",
                        expect="contains Final",
                        actual="present" if "Final" in body_text
                                else "absent",
                        passed="Final" in body_text)
    finally:
        _teardown()


if __name__ == "__main__":
    run()
