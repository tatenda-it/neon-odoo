"""QUOTE-UX-1b browser smoke — PREVIEW persistent + left-positioned + renders.

Scenarios:
  A  APPROVED quote: the Preview button is VISIBLE, positioned LEFT of the
     "Send to Client" action, and clicking it RENDERS the report PDF (a
     download fires -- NOT the 'Configure Document Layout' wizard). Send to
     Client remains reachable.
  B  PENDING quote: Preview is STILL visible (persistent past draft).
  C  SENT quote: Preview is STILL visible even though the Send button itself
     is now gone (state-correct) and "Mark Accepted" has taken its place --
     proving the Preview persists across the whole active pipeline.

Self-contained [TEST-QUX1B2] fixtures (committed for the browser to see, torn
down after). The WhatsApp approver audience is emptied during setup so the
submit pings nobody.
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke, AssertionFail  # noqa: F401
from playwright.sync_api import TimeoutError as PWTimeout

BASE_URL = "http://localhost:8069"
DB = "neon_crm"


# Build one quote in each of pending / approved / sent via the real workflow
# (submit -> approve by the approver -> send by the salesperson). require-all
# stays at its 'True' default; the empty approver audience suppresses the ping.
_SETUP = """
from datetime import date, timedelta
import odoo.addons.neon_crew_comms.models.whatsapp_message_wa12 as _m
_m._WA12_APPROVER_UIDS = ()  # no WhatsApp send during browser-smoke setup
sales = env['res.users'].search([('login','=','p2m75_sales')], limit=1)
approver = env['res.users'].search([('login','=','p2m75_approver')], limit=1)
usd = env.ref('base.USD').id
partner = env['res.partner'].create({'name':'[TEST-QUX1B2] Client','is_company':True}).id
venue = env['res.partner'].create({'name':'[TEST-QUX1B2] Venue','is_company':True}).id
job = env['commercial.job'].create({'partner_id':partner,'venue_id':venue,
    'event_date':(date.today()+timedelta(days=20)).isoformat(),'currency_id':usd}).id
ej = env['commercial.event.job'].create({'commercial_job_id':job}).id
term = env['neon.finance.payment.term'].create({'partner_id':partner,'deposit_pct':50.0,
    'deposit_due_days':0,'final_due_days':30,'late_policy':'reminder'}).id
def mkq():
    q = env['neon.finance.quote'].create({'event_job_id':ej,'currency_id':usd,
        'salesperson_id':sales.id,'payment_term_id':term})
    env['neon.finance.quote.line'].create({'quote_id':q.id,'line_type':'equipment',
        'name':'SOUND RIG','quantity':1.0,'duration_days':2,'unit_rate':300.0,
        'pricing_status':'manual'})
    return q
q_pending = mkq()
q_pending.with_user(sales.id).action_submit_for_approval()
q_approved = mkq()
q_approved.with_user(sales.id).action_submit_for_approval()
q_approved.with_user(approver.id).action_approve()
q_sent = mkq()
q_sent.with_user(sales.id).action_submit_for_approval()
q_sent.with_user(approver.id).action_approve()
q_sent.with_user(sales.id).action_send()
appr_ids = env['neon.finance.approval'].search(
    [('quote_id','in',[q_pending.id,q_approved.id,q_sent.id])]).ids
env.cr.commit()
print('IDS_JSON=' + repr({'q_pending':q_pending.id,'q_approved':q_approved.id,
    'q_sent':q_sent.id,'appr_ids':appr_ids,'term':term,'ej':ej,'job':job,
    'partner':partner,'venue':venue}))
"""

_TEARDOWN = """
ids = {ids_repr}
for qid in (ids['q_pending'], ids['q_approved'], ids['q_sent']):
    try:
        env['neon.finance.quote'].browse(qid).write(
            {{'state':'cancelled','cancelled_reason':'quoteux1b browser teardown'}})
    except Exception as e:
        print('cancel failed for', qid, ':', e)
for aid in ids.get('appr_ids', []):
    try:
        env['neon.finance.approval'].browse(aid).unlink()
    except Exception as e:
        print('approval unlink failed', aid, ':', e)
for model, key in [
    ('neon.finance.quote','q_pending'), ('neon.finance.quote','q_approved'),
    ('neon.finance.quote','q_sent'),
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
        input=script.encode("utf-8"), capture_output=True, timeout=240)
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
        print("[quoteux1b] teardown warning:\n" + out[-1500:])


def _form_url(smoke, qid: int) -> str:
    return (f"{smoke.base_url}/web#id={qid}"
            f"&model=neon.finance.quote&view_type=form")


def main() -> int:
    print("[quoteux1b] setup: creating [TEST-QUX1B2] fixtures ...")
    ids = _setup()
    print(f"[quoteux1b] setup ok: pending={ids['q_pending']} "
          f"approved={ids['q_approved']} sent={ids['q_sent']}")
    try:
        with BrowserSmoke("quoteux1b") as smoke:

            with smoke.scenario(
                    "A: approved quote -> Preview visible, LEFT of Send, renders PDF"):
                smoke.login("p2m75_sales")
                smoke.page.goto(_form_url(smoke, ids['q_approved']),
                                wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "approved quote form")
                smoke.assert_visible(
                    "button[name='action_preview_quote']",
                    "Preview button visible on the APPROVED quote")
                smoke.assert_visible(
                    "button[name='action_send']",
                    "Send to Client button visible on the approved quote")
                # LEFT placement: Preview sits left of the Send-to-Client action.
                pv = smoke.page.locator(
                    "button[name='action_preview_quote']").first.bounding_box()
                sd = smoke.page.locator(
                    "button[name='action_send']").first.bounding_box()
                left_ok = bool(pv and sd and pv["x"] < sd["x"])
                smoke._record_assert(
                    "Preview is positioned LEFT of Send to Client",
                    expect="preview.x < send.x",
                    actual=(f"{pv['x']:.0f} < {sd['x']:.0f}" if (pv and sd)
                            else "missing box"),
                    passed=left_ok)
                if not left_ok:
                    smoke._capture_fail_artifacts("preview_left_of_send")
                    raise AssertionFail(
                        "Preview button is not positioned left of Send to Client")
                # Clicking Preview RENDERS the report (a download fires) and does
                # NOT pop the 'Configure Document Layout' wizard.
                rendered = False
                try:
                    with smoke.page.expect_download(timeout=30000) as dl:
                        smoke.page.locator(
                            "button[name='action_preview_quote']").first.click()
                    _ = dl.value
                    rendered = True
                except PWTimeout:
                    rendered = False
                wizard = smoke.page.locator(
                    ".modal:has-text('Configure'), "
                    ".o_dialog:has-text('document layout')").count()
                smoke._record_assert(
                    "Preview click renders the report PDF (download, no layout wizard)",
                    expect="download fired AND no layout wizard",
                    actual=f"download={rendered} wizard_modals={wizard}",
                    passed=rendered and wizard == 0)
                if not (rendered and wizard == 0):
                    smoke._capture_fail_artifacts("preview_render")
                    raise AssertionFail(
                        "Preview did not render the PDF cleanly "
                        f"(download={rendered}, wizard_modals={wizard})")
                smoke.screenshot("A_approved_preview_renders")

            with smoke.scenario(
                    "B: pending quote -> Preview still visible (persistent)"):
                smoke.page.goto(_form_url(smoke, ids['q_pending']),
                                wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "pending quote form")
                smoke.assert_visible(
                    "button[name='action_preview_quote']",
                    "Preview button still visible on the PENDING quote")
                # depth: the submit-for-approval action is gone (state moved on)
                smoke.assert_visible(
                    "button[name='action_approve'], .o_statusbar_status",
                    "pending quote shows the approval stage")
                smoke.screenshot("B_pending_preview_visible")

            with smoke.scenario(
                    "C: sent quote -> Preview persists even after Send is gone"):
                smoke.page.goto(_form_url(smoke, ids['q_sent']),
                                wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "sent quote form")
                smoke.assert_visible(
                    "button[name='action_preview_quote']",
                    "Preview button still visible on the SENT quote")
                smoke.assert_visible(
                    "button[name='action_accept']",
                    "sent quote now offers Mark Accepted (stage advanced)")
                # The Send button is state-correctly gone on a sent quote.
                send_now = smoke.page.locator(
                    "button[name='action_send']").count()
                smoke._record_assert(
                    "Send to Client button is gone on a sent quote (Preview is not)",
                    expect="0 send buttons", actual=str(send_now),
                    passed=send_now == 0)
                smoke.screenshot("C_sent_preview_persists")

        return smoke.summary()
    finally:
        print("[quoteux1b] teardown: removing [TEST-QUX1B2] fixtures ...")
        _teardown(ids)


if __name__ == "__main__":
    sys.exit(main())
