"""QUOTE-UX-3b browser smoke -- whole-quote discount on the Odoo form.

Scenario (as p2m75_sales, the fixture quote's salesperson):
  A  a draft quote shows the "Apply Whole-Quote Discount" button; clicking it
     opens the wizard; entering a discount amount and clicking Apply distributes
     it (the UX-3 per-line discount_pct columns fill) and the wa12_discount_note
     label renders read-only in the footer.

The distribution math + every UserError path + the wizard's action_apply wiring
are proven deterministically in the model smoke quoteux3b_smoke.py; WA parity is
pwa12_6 S13/S14. This browser smoke proves the end-to-end FORM path
(button -> wizard -> apply -> rendered result).

Setup creates a self-contained [TEST-QUX3CB] draft quote with two priced lines
(no discount), commits, and tears down at the end.
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke  # noqa: F401

DB = "neon_crm"

_SETUP_SCRIPT = """
from datetime import date, timedelta
sales = env['res.users'].search([('login','=','p2m75_sales')], limit=1).id
usd = env.ref('base.USD').id
partner = env['res.partner'].create({'name':'[TEST-QUX3CB] Client','is_company':True}).id
venue = env['res.partner'].create({'name':'[TEST-QUX3CB] Venue','is_company':True}).id
job = env['commercial.job'].create({'partner_id':partner,'venue_id':venue,
    'event_date':(date.today()+timedelta(days=30)).isoformat(),'currency_id':usd}).id
event_job = env['commercial.event.job'].create({'commercial_job_id':job}).id
quote = env['neon.finance.quote'].create({'event_job_id':event_job,'currency_id':usd,
    'salesperson_id':sales}).id
l1 = env['neon.finance.quote.line'].create({'quote_id':quote,'line_type':'equipment',
    'name':'[TEST-QUX3CB] RIG A','quantity':1.0,'duration_days':1,'unit_rate':200.0,
    'pricing_status':'manual'}).id
l2 = env['neon.finance.quote.line'].create({'quote_id':quote,'line_type':'equipment',
    'name':'[TEST-QUX3CB] RIG B','quantity':1.0,'duration_days':1,'unit_rate':100.0,
    'pricing_status':'manual'}).id
env.cr.commit()
print('IDS_JSON=' + repr({'quote':quote,'l1':l1,'l2':l2,
    'event_job':event_job,'job':job,'partner':partner,'venue':venue}))
"""

_TEARDOWN_TEMPLATE = """
ids = {ids_repr}
try:
    env['neon.finance.quote'].browse(ids['quote']).write(
        {{'state':'cancelled','cancelled_reason':'quoteux3b browser teardown'}})
except Exception:
    pass
for model, key in [
    ('neon.finance.quote.line','l1'), ('neon.finance.quote.line','l2'),
    ('neon.finance.quote','quote'), ('commercial.event.job','event_job'),
    ('commercial.job','job'), ('res.partner','partner'), ('res.partner','venue'),
]:
    try:
        env[model].browse(ids[key]).unlink()
    except Exception as e:
        print('teardown unlink failed for', model, ids[key], ':', e)
env.cr.commit()
print('TEARDOWN_OK')
"""


def _run_odoo_shell(script: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "--project-directory", "C:/Users/Neon/neon-odoo",
         "exec", "-T", "odoo", "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"), capture_output=True, timeout=180,
    )
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def _setup() -> dict:
    out = _run_odoo_shell(_SETUP_SCRIPT)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out)
        raise RuntimeError("setup did not produce IDS_JSON marker")
    return eval(m.group(1), {"__builtins__": {}}, {})


def _teardown(ids: dict) -> None:
    out = _run_odoo_shell(_TEARDOWN_TEMPLATE.format(ids_repr=repr(ids)))
    if "TEARDOWN_OK" not in out:
        print("[quoteux3b] teardown warning:\n" + out[-1500:])


def main() -> int:
    print("[quoteux3b] setup: creating [TEST-QUX3CB] draft quote ...")
    ids = _setup()
    print(f"[quoteux3b] setup ok: quote={ids['quote']}")
    try:
        with BrowserSmoke("quoteux3b") as smoke:
            form_url = (f"{smoke.base_url}/web#id={ids['quote']}"
                        f"&model=neon.finance.quote&view_type=form")

            with smoke.scenario(
                    "A: whole-quote discount button -> wizard -> apply"):
                smoke.login("p2m75_sales")
                smoke.page.goto(form_url, wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "quote form view")
                smoke.assert_visible(
                    "button[name='action_open_whole_quote_discount_wizard']",
                    "'Apply Whole-Quote Discount' button visible on a draft")
                # open the wizard
                smoke.click(
                    "button[name='action_open_whole_quote_discount_wizard']",
                    name="open the whole-quote discount wizard")
                smoke.assert_visible(
                    ".modal .o_form_view", "wizard modal opened")
                smoke.assert_visible(
                    ".modal [name='amount']", "wizard exposes the amount field")
                # enter a 50 discount and apply
                smoke.page.fill(".modal [name='amount'] input", "50")
                smoke.click(".modal button[name='action_apply']",
                            name="click Apply in the wizard")
                smoke.page.wait_for_selector(".modal .o_form_view",
                                             state="detached", timeout=15000)
                # the achieved-drop label now renders read-only in the footer
                smoke.assert_visible(
                    "[name='wa12_discount_note']:has-text('Discount')",
                    "wa12_discount_note label renders after apply")
                smoke.screenshot("A_whole_quote_discount_applied")

        return smoke.summary()
    finally:
        print("[quoteux3b] teardown: removing [TEST-QUX3CB] fixtures ...")
        _teardown(ids)


if __name__ == "__main__":
    sys.exit(main())
