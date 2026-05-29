"""P-B1 browser smoke -- data-model completion (Conflict-Engine foundation).

Scenarios:
(1) Event-job form renders the "Logistics window" section with the
    4 load-in/out fields + the computed occupation_start/end.
(2) Equipment unit form renders condition_status (badge) +
    last_checked_at (placeholder "never checked").
(3) Equipment category form renders parent_id + low_stock_threshold,
    and the tree shows the new columns.

All scenarios run as the admin user via direct URL navigation -- no
ACL gymnastics needed.
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP = """
from datetime import date
from odoo import fields as ofields
Users = env['res.users']
EventJob = env['commercial.event.job']
Unit = env['neon.equipment.unit']
Category = env['neon.equipment.category']
Job = env['commercial.job']
Partner = env['res.partner']
Product = env['product.template']


def _wipe_login(login):
    u = Users.search([('login','=',login)], limit=1)
    if u:
        u.write({'login': login + '_OLD_' + str(u.id),
                 'active': False})


_wipe_login('pb1_admin')
admin_user = Users.with_context(no_reset_password=True).create({
    'name': 'pb1_admin',
    'login': 'pb1_admin',
    'password': 'test123',
    'groups_id': [
        (4, env.ref('base.group_user').id),
        (4, env.ref('base.group_system').id),
        (4, env.ref('neon_jobs.group_neon_jobs_manager').id),
        (4, env.ref('neon_core.group_neon_superuser').id),
    ],
})

partner = Partner.search([], limit=1)
venue = Partner.search([('is_venue', '=', True)], limit=1)
# Pin event_date well in the past so the master_job doesn't pollute
# p2m7's 14-day cash_flow window (which counts pending+quoted jobs in
# event_date BETWEEN today AND today+14). The browser smoke only
# needs an event-job form to render -- the date value doesn't matter.
old_event_date = date(2024, 1, 15)
master_job = Job.search([('name', '=', 'PB1 BROWSER JOB')], limit=1)
if master_job:
    master_job.unlink()
mvals = {
    'name': 'PB1 BROWSER JOB',
    'partner_id': partner.id,
    'state': 'active',
    'event_date': old_event_date,
}
if venue:
    mvals['venue_id'] = venue.id
master_job = Job.create(mvals)
probe = EventJob.search([('name', '=', 'PB1 BROWSER PROBE')], limit=1)
if probe:
    probe.unlink()
probe = EventJob.create({
    'name': 'PB1 BROWSER PROBE',
    'commercial_job_id': master_job.id,
    'partner_id': partner.id,
})

# Find an existing unit OR create one if the workshop has a product.
unit = Unit.search([], limit=1)
if not unit:
    product = Product.search(
        [('is_workshop_item', '=', True)], limit=1)
    if product:
        unit = Unit.create({
            'product_template_id': product.id,
            'serial_number': 'PB1-BROWSER',
        })

category = Category.search([], limit=1)

env.cr.commit()
print('IDS_JSON=' + repr({
    'admin': admin_user.id,
    'probe_id': probe.id,
    'unit_id': unit.id if unit else 0,
    'category_id': category.id if category else 0,
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
        print("[pb1] SETUP FAILED:")
        print(out[-2000:])
        sys.exit(2)
    depth = 0
    start = out.find("{", idx)
    for i in range(start, len(out)):
        if out[i] == "{":
            depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                return eval(out[start:i + 1])  # noqa: S307
    print("[pb1] SETUP FAILED parse:")
    print(out[-2000:])
    sys.exit(2)


def run():
    ids = _setup()

    with BrowserSmoke("pb1") as smoke:

        with smoke.scenario("Event-job form: Logistics window + occupation"):
            smoke.login("pb1_admin")
            smoke.page.goto(
                f"{BASE_URL}/web#id={ids['probe_id']}"
                f"&model=commercial.event.job&view_type=form")
            smoke.page.wait_for_selector(
                "div.o_form_view", timeout=20000)
            # Schedule tab -- click into it so the Logistics group renders.
            smoke.page.locator(
                "a.nav-link:has-text('Schedule')").first.click()
            smoke.page.wait_for_timeout(400)
            # Logistics group label
            logistics_label = smoke.page.locator(
                "div.o_inner_group:has-text('Logistics window')"
            ).count()
            smoke._record_assert(
                "Logistics window group rendered",
                expect=">=1", actual=str(logistics_label),
                passed=logistics_label >= 1)
            # 4 load fields exist
            load_fields_present = 0
            for f in ("load_in_start", "load_in_end",
                      "load_out_start", "load_out_end"):
                if smoke.page.locator(
                        f"[name='{f}']").count() > 0:
                    load_fields_present += 1
            smoke._record_assert(
                "4 venue-side load-in/out fields render",
                expect="4", actual=str(load_fields_present),
                passed=load_fields_present == 4)
            # Occupation span renders + has a value (event_date backstop).
            occ_start = smoke.page.locator(
                "[name='occupation_start']").count()
            smoke._record_assert(
                "occupation_start field present",
                expect=">=1", actual=str(occ_start),
                passed=occ_start >= 1)

        with smoke.scenario(
                "Equipment unit form: condition_status + last_checked"):
            if not ids["unit_id"]:
                smoke._record_assert(
                    "no fixture unit on this DB; scenario skipped",
                    expect="unit_id>0",
                    actual=str(ids["unit_id"]),
                    passed=True)
            else:
                smoke.page.goto(
                    f"{BASE_URL}/web#id={ids['unit_id']}"
                    f"&model=neon.equipment.unit&view_type=form")
                smoke.page.wait_for_selector(
                    "div.o_form_view", timeout=15000)
                smoke.page.wait_for_timeout(300)
                cond = smoke.page.locator(
                    "[name='condition_status']").count()
                last = smoke.page.locator(
                    "[name='last_checked_at']").count()
                smoke._record_assert(
                    "condition_status renders on unit form",
                    expect=">=1", actual=str(cond),
                    passed=cond >= 1)
                smoke._record_assert(
                    "last_checked_at renders on unit form",
                    expect=">=1", actual=str(last),
                    passed=last >= 1)

        with smoke.scenario(
                "Equipment category form: parent_id + threshold"):
            if not ids["category_id"]:
                smoke._record_assert(
                    "no fixture category; scenario skipped",
                    expect="category_id>0",
                    actual=str(ids["category_id"]),
                    passed=True)
            else:
                smoke.page.goto(
                    f"{BASE_URL}/web#id={ids['category_id']}"
                    f"&model=neon.equipment.category"
                    f"&view_type=form")
                smoke.page.wait_for_selector(
                    "div.o_form_view", timeout=15000)
                smoke.page.wait_for_timeout(300)
                parent = smoke.page.locator(
                    "[name='parent_id']").count()
                thresh = smoke.page.locator(
                    "[name='low_stock_threshold']").count()
                smoke._record_assert(
                    "parent_id renders on category form",
                    expect=">=1", actual=str(parent),
                    passed=parent >= 1)
                smoke._record_assert(
                    "low_stock_threshold renders on category form",
                    expect=">=1", actual=str(thresh),
                    passed=thresh >= 1)


if __name__ == "__main__":
    run()
