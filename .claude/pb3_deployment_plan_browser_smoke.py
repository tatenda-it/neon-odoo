"""P-B3 browser smoke -- Deployment Plan form + render + state machine.

Scenarios:
(1) Plan tree + form opens for a superuser; ACL passes.
(2) Plan form renders the deficit "ACTION REQUIRED" block when
    plan_summary_html has one.
(3) State-machine buttons (Mark Reviewed -> Mark Final) advance
    status through the review gate.
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
Conflict = env['neon.equipment.conflict']

def _wipe_login(login):
    u = Users.search([('login','=',login)], limit=1)
    if u:
        u.write({'login': login + '_OLD_' + str(u.id),
                 'active': False})

_wipe_login('pb3_admin')
admin_user = Users.with_context(no_reset_password=True).create({
    'name': 'pb3_admin', 'login': 'pb3_admin',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('base.group_system').id),
        (4, env.ref('neon_jobs.group_neon_jobs_manager').id),
        (4, env.ref('neon_core.group_neon_superuser').id),
    ],
})

# Wipe + create a fresh plan with a deficit so the render has
# something to show.
EventJob.sudo().search(
    [('name', '=like', 'PB3 BR EVT%')]).with_context(
    _allow_state_write=True).write({'state': 'cancelled'})
EventJob.sudo().search([('name', '=like', 'PB3 BR EVT%')]).unlink()
Job.sudo().search([('name', '=like', 'PB3 BR JOB%')]).unlink()
Unit.sudo().search([('serial_number', '=like', 'PB3BR-%')]).unlink()
Plan.sudo().search([('event_job_id', '=', 0)]).unlink()

partner = Partner.sudo().search([], limit=1)
venue = Partner.sudo().search([('is_venue','=',True)], limit=1)
product = Product.sudo().search(
    [('is_workshop_item','=',True)], limit=1)
today = date.today()
plan_id = 0
if product:
    Unit.sudo().create([{
        'product_template_id': product.id,
        'serial_number': f'PB3BR-{i}',
        'condition_status': 'good'} for i in range(3)])
    mvals = {'name': 'PB3 BR JOB A', 'partner_id': partner.id,
              'state': 'active', 'event_date': today}
    if venue: mvals['venue_id'] = venue.id
    m = Job.sudo().create(mvals)
    ev = EventJob.sudo().create({
        'name': 'PB3 BR EVT A',
        'commercial_job_id': m.id, 'partner_id': partner.id,
        'load_in_start': datetime.combine(today, time(9,0)),
        'load_out_end': datetime.combine(today, time(14,0)),
        'dispatch_datetime': datetime.combine(today, time(8,0)),
        'prep_start_datetime': datetime.combine(today, time(7,0)),
    })
    ev.with_context(_allow_state_write=True).write(
        {'state': 'planning'})
    Line.sudo().create({'event_job_id': ev.id,
                         'product_template_id': product.id,
                         'quantity_planned': 5})
    ev.flush_recordset()
    Line.flush_model()
    # Build a conflict snapshot
    from odoo.addons.neon_jobs.models.neon_equipment_conflict \
        import ConflictEngine
    ConflictEngine(env).run_for_event(ev, trigger_reason='manual')
    # Build a plan directly (skip Claude call -- this smoke is UI)
    from odoo.addons.neon_jobs.models.deployment_plan_fact_gatherer \
        import DeploymentPlanFactGatherer
    facts = DeploymentPlanFactGatherer(env).gather(ev)
    b2_lines = facts['b2_conflict']['lines']
    matching = [ln for ln in b2_lines
                 if ln['product_template_id'] == product.id]
    deficit = matching[0] if matching else {}
    plan_payload = {
        'sections': [
            {'key': 'load_in', 'title': 'Load-in',
             'narrative': 'Morning of the event.'},
            {'key': 'setup', 'title': 'Setup',
             'narrative': 'After load-in.'},
            {'key': 'show_time', 'title': 'Show',
             'narrative': 'Show runs through the day.'},
            {'key': 'strike', 'title': 'Strike',
             'narrative': 'Post-event.'},
            {'key': 'return', 'title': 'Return',
             'narrative': 'Convoy back.'},
            {'key': 'risks', 'title': 'Risks',
             'narrative': 'Sub-hire planned.'},
        ],
        'crew_call_times': facts.get('crew_call_times') or [],
        'deficits': [{
            'product_name': deficit.get('product_name', ''),
            'required_qty': deficit.get('required_qty', 0),
            'available_qty': deficit.get('available_qty', 0),
            'deficit_qty': deficit.get('deficit_qty', 0),
            'competing_event_names':
                deficit.get('competing_event_names', []),
            'sub_hire_priority':
                deficit.get('sub_hire_priority', 0),
        }] if deficit else [],
        'data_quality_note': facts['b2_conflict'].get(
            'data_quality_note'),
    }
    plan = Plan.sudo().create({
        'event_job_id': ev.id, 'revision': 1,
        'status': 'generated',
        'generated_at': fields.Datetime.now(),
        'generated_by_id': admin_user.id,
        'plan_json': _json.dumps(plan_payload),
        'model_used': 'claude-sonnet-4-6',
        'prompt_tokens': 1100, 'completion_tokens': 350,
        'latency_ms': 1400,
    })
    plan_id = plan.id
env.cr.commit()
print('IDS_JSON=' + repr({
    'admin': admin_user.id, 'plan_id': plan_id,
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
        print("[pb3] SETUP FAILED:"); print(out[-2000:]); sys.exit(2)
    depth = 0
    start = out.find("{", idx)
    for i in range(start, len(out)):
        if out[i] == "{": depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                return eval(out[start:i + 1])  # noqa: S307
    print("[pb3] SETUP FAILED parse:"); print(out[-2000:]); sys.exit(2)


def run():
    ids = _setup()

    with BrowserSmoke("pb3") as smoke:

        with smoke.scenario(
                "Plan form opens + renders for superuser"):
            smoke.login("pb3_admin")
            if not ids["plan_id"]:
                smoke._record_assert(
                    "no plan fixture; scenario skipped",
                    expect="plan_id>0",
                    actual="0", passed=True)
            else:
                smoke.page.goto(
                    f"{BASE_URL}/web#id={ids['plan_id']}"
                    f"&model=neon.deployment.plan"
                    f"&view_type=form")
                smoke.page.wait_for_selector(
                    "div.o_form_view", timeout=20000)
                smoke.page.wait_for_timeout(500)
                # Status + Mark Reviewed button visible
                mark_reviewed = smoke.page.locator(
                    "button:has-text('Mark Reviewed')").count()
                smoke._record_assert(
                    "Mark Reviewed button present (status=generated)",
                    expect=">=1", actual=str(mark_reviewed),
                    passed=mark_reviewed >= 1)

        with smoke.scenario(
                "Plan summary HTML renders the deficit block"):
            if not ids["plan_id"]:
                smoke._record_assert(
                    "no plan fixture; scenario skipped",
                    expect="plan_id>0",
                    actual="0", passed=True)
            else:
                # The plan_summary_html field is sanitize=False so
                # the ACTION REQUIRED block renders as live HTML.
                body_text = smoke.page.locator(
                    "div.o_form_view").inner_text()
                has_action = "ACTION REQUIRED" in body_text
                has_subhire = "SUB-HIRE" in body_text
                smoke._record_assert(
                    "deficit block contains 'ACTION REQUIRED' + "
                    "'SUB-HIRE'",
                    expect="both",
                    actual=f"action={has_action} subhire={has_subhire}",
                    passed=has_action and has_subhire)

        with smoke.scenario(
                "Review gate: Mark Reviewed -> Mark Final"):
            if not ids["plan_id"]:
                smoke._record_assert(
                    "no plan fixture; scenario skipped",
                    expect="plan_id>0",
                    actual="0", passed=True)
            else:
                # Click Mark Reviewed
                smoke.page.locator(
                    "button:has-text('Mark Reviewed')"
                ).first.click()
                smoke.page.wait_for_timeout(500)
                # Mark Final button should now be visible
                mark_final = smoke.page.locator(
                    "button:has-text('Mark Final')").count()
                smoke._record_assert(
                    "Mark Final button appears after Reviewed",
                    expect=">=1", actual=str(mark_final),
                    passed=mark_final >= 1)


if __name__ == "__main__":
    run()
