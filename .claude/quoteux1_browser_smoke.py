"""QUOTE-UX-1 browser smoke — Preview affordance + approver-sees-line-items.

Scenarios:
  A  p2m75_sales opens a DRAFT quote and sees the "Preview" button
     (review-before-submit, C).
  B  p2m75_approver opens the Approval Queue record they action and sees the
     FULL quote line items (name + rate) + the Approve button live on that
     form (D-Odoo: no click-through to the quote).

Self-contained [TEST-QUX1B] fixtures (committed for the browser to see, torn
down after). The WA approval audience is emptied during setup so submitting
the pending quote sends nothing.
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke, AssertionFail  # noqa: F401

BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP = """
from datetime import date, timedelta
import odoo.addons.neon_crew_comms.models.whatsapp_message_wa12 as _m
_m._WA12_APPROVER_UIDS = ()  # no WhatsApp send during browser-smoke setup
sales = env['res.users'].search([('login','=','p2m75_sales')], limit=1).id
usd = env.ref('base.USD').id
partner = env['res.partner'].create({'name':'[TEST-QUX1B] Client','is_company':True}).id
venue = env['res.partner'].create({'name':'[TEST-QUX1B] Venue','is_company':True}).id
job = env['commercial.job'].create({'partner_id':partner,'venue_id':venue,
    'event_date':(date.today()+timedelta(days=20)).isoformat(),'currency_id':usd}).id
ej = env['commercial.event.job'].create({'commercial_job_id':job}).id
term = env['neon.finance.payment.term'].create({'partner_id':partner,'deposit_pct':50.0,
    'deposit_due_days':0,'final_due_days':30,'late_policy':'reminder'}).id
def mkq():
    q = env['neon.finance.quote'].create({'event_job_id':ej,'currency_id':usd,
        'salesperson_id':sales,'payment_term_id':term})
    env['neon.finance.quote.line'].create({'quote_id':q.id,'line_type':'equipment',
        'name':'SOUND RIG','quantity':1.0,'duration_days':2,'unit_rate':300.0,
        'pricing_status':'manual'})
    return q
q_draft = mkq()
q_pending = mkq()
q_pending.with_user(sales).action_submit_for_approval()
appr = env['neon.finance.approval'].search([('quote_id','=',q_pending.id)], limit=1).id
env.cr.commit()
print('IDS_JSON=' + repr({'q_draft':q_draft.id,'q_pending':q_pending.id,'appr':appr,
    'term':term,'ej':ej,'job':job,'partner':partner,'venue':venue}))
"""

_TEARDOWN = """
ids = {ids_repr}
try:
    for qid in (ids['q_draft'], ids['q_pending']):
        env['neon.finance.quote'].browse(qid).write(
            {{'state':'cancelled','cancelled_reason':'quoteux1 browser teardown'}})
except Exception:
    pass
for model, key in [
    ('neon.finance.approval','appr'),
    ('neon.finance.quote','q_draft'), ('neon.finance.quote','q_pending'),
    ('neon.finance.payment.term','term'), ('commercial.event.job','ej'),
    ('commercial.job','job'), ('res.partner','partner'), ('res.partner','venue'),
]:
    try:
        env[model].browse(ids[key]).unlink()
    except Exception as e:
        print('teardown unlink failed for', model, ids[key], ':', e)
env.cr.commit()
print('TEARDOWN_OK')
"""


def _shell(script: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "--project-directory", "C:/Users/Neon/neon-odoo",
         "exec", "-T", "odoo", "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"), capture_output=True, timeout=180)
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def _setup() -> dict:
    out = _shell(_SETUP)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out)
        raise RuntimeError("setup did not produce IDS_JSON")
    return eval(m.group(1), {"__builtins__": {}}, {})


def _teardown(ids: dict) -> None:
    out = _shell(_TEARDOWN.format(ids_repr=repr(ids)))
    if "TEARDOWN_OK" not in out:
        print("[quoteux1] teardown warning:\n" + out[-1500:])


def main() -> int:
    print("[quoteux1] setup: creating [TEST-QUX1B] fixtures ...")
    ids = _setup()
    print(f"[quoteux1] setup ok: draft={ids['q_draft']} "
          f"pending={ids['q_pending']} approval={ids['appr']}")
    try:
        with BrowserSmoke("quoteux1") as smoke:

            with smoke.scenario("A: rep sees the Preview button on a draft quote"):
                smoke.login("p2m75_sales")
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['q_draft']}"
                    f"&model=neon.finance.quote&view_type=form",
                    wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "draft quote form")
                smoke.assert_visible(
                    "button[name='action_preview_quote']",
                    "Preview button visible on the draft quote (review-before-submit)")
                smoke.screenshot("A_draft_preview_button")

            with smoke.scenario("B: approver sees the full line items on the Approval Queue form"):
                smoke.login("p2m75_approver")
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['appr']}"
                    f"&model=neon.finance.approval&view_type=form",
                    wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "approval record form")
                smoke.assert_visible(
                    "td.o_data_cell[name='name']:has-text('SOUND RIG')",
                    "approver sees the quote LINE ITEM on the approval form")
                smoke.assert_visible(
                    "td.o_data_cell[name='unit_rate']:has-text('300.00')",
                    "approver sees the line RATE (300.00) on the approval form")
                smoke.assert_visible(
                    "button[name='action_approve_from_form']",
                    "Approve button visible to the approver")
                smoke.screenshot("B_approval_form_line_items")

        return smoke.summary()
    finally:
        print("[quoteux1] teardown: removing [TEST-QUX1B] fixtures ...")
        _teardown(ids)


if __name__ == "__main__":
    sys.exit(main())
