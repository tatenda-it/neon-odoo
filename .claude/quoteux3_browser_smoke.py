"""QUOTE-UX-3 browser smoke -- the engine line discount on the Odoo quote form.

Scenarios (as p2m75_sales, the fixture quote's salesperson):
  A  the draft quote form renders the discount_pct AND discount_amount columns
     WITHOUT toggling any optional column (default-visible), and a line that
     already carries a discount (the WA-originated case) shows the discount
     value + the discounted line_subtotal.
  B  the read-only wa12_discount_note label renders in the totals footer.

The live OWL keystroke recompute (type a discount -> subtotal/footer update,
sibling clears) is proven deterministically in the model smoke
quoteux3_smoke.py (per the fixs1 precedent: driving Odoo 17's editable-tree
autocomplete/keystrokes in headless Playwright is flaky). The browser proves
the columns + discounted values RENDER.

Setup creates a self-contained [TEST-QUX3B] draft quote with one discount_pct
line and one discount_amount line + a whole-quote wa12_discount_note label,
commits so the browser sees it, and tears everything down at the end.
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
partner = env['res.partner'].create({'name':'[TEST-QUX3B] Client','is_company':True}).id
venue = env['res.partner'].create({'name':'[TEST-QUX3B] Venue','is_company':True}).id
job = env['commercial.job'].create({'partner_id':partner,'venue_id':venue,
    'event_date':(date.today()+timedelta(days=30)).isoformat(),'currency_id':usd}).id
event_job = env['commercial.event.job'].create({'commercial_job_id':job}).id
quote = env['neon.finance.quote'].create({'event_job_id':event_job,'currency_id':usd,
    'salesperson_id':sales,'wa12_discount_note':'Discount USD 50.00 (incl. VAT)'}).id
# pct line: 100 * (1-0.10) * 1 * 1 = 90.00
lpct = env['neon.finance.quote.line'].create({'quote_id':quote,'line_type':'equipment',
    'name':'[TEST-QUX3B] PCT LINE','quantity':1.0,'duration_days':1,'unit_rate':100.0,
    'pricing_status':'manual','discount_pct':10.0}).id
# amount line: (200-50) * 1 * 1 = 150.00
lamt = env['neon.finance.quote.line'].create({'quote_id':quote,'line_type':'equipment',
    'name':'[TEST-QUX3B] AMT LINE','quantity':1.0,'duration_days':1,'unit_rate':200.0,
    'pricing_status':'manual','discount_amount':50.0}).id
env.cr.commit()
print('IDS_JSON=' + repr({'quote':quote,'lpct':lpct,'lamt':lamt,
    'event_job':event_job,'job':job,'partner':partner,'venue':venue}))
"""

_TEARDOWN_TEMPLATE = """
ids = {ids_repr}
try:
    env['neon.finance.quote'].browse(ids['quote']).write(
        {{'state':'cancelled','cancelled_reason':'quoteux3 browser teardown'}})
except Exception:
    pass
for model, key in [
    ('neon.finance.quote.line','lpct'), ('neon.finance.quote.line','lamt'),
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
        print("[quoteux3] teardown warning:\n" + out[-1500:])


def main() -> int:
    print("[quoteux3] setup: creating [TEST-QUX3B] discount quote ...")
    ids = _setup()
    print(f"[quoteux3] setup ok: quote={ids['quote']} "
          f"pct_line={ids['lpct']} amt_line={ids['lamt']}")
    try:
        with BrowserSmoke("quoteux3") as smoke:
            form_url = (f"{smoke.base_url}/web#id={ids['quote']}"
                        f"&model=neon.finance.quote&view_type=form")

            with smoke.scenario(
                    "A: discount columns default-visible + discounted values"):
                smoke.login("p2m75_sales")
                smoke.page.goto(form_url, wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "quote form view")
                # columns present WITHOUT toggling any optional column
                smoke.assert_visible(
                    "td.o_data_cell[name='discount_pct']",
                    "discount_pct column default-visible on the line tree")
                smoke.assert_visible(
                    "td.o_data_cell[name='discount_amount']",
                    "discount_amount column default-visible on the line tree")
                # the WA-originated discount value shows without toggling
                smoke.assert_visible(
                    "td.o_data_cell[name='discount_amount']:has-text('50.00')",
                    "discount_amount value 50.00 renders (WA-originated)")
                # the discounted subtotals render: pct line 90.00, amt line 150.00
                smoke.assert_visible(
                    "td.o_data_cell[name='line_subtotal']:has-text('90.00')",
                    "pct-discounted line_subtotal renders 90.00")
                smoke.assert_visible(
                    "td.o_data_cell[name='line_subtotal']:has-text('150.00')",
                    "amount-discounted line_subtotal renders 150.00")
                smoke.screenshot("A_discount_columns")

            with smoke.scenario(
                    "B: wa12_discount_note read-only label in the footer"):
                smoke.assert_visible(
                    "[name='wa12_discount_note']:has-text('Discount USD 50.00')",
                    "whole-quote discount label renders read-only")
                smoke.screenshot("B_discount_note")

        return smoke.summary()
    finally:
        print("[quoteux3] teardown: removing [TEST-QUX3B] fixtures ...")
        _teardown(ids)


if __name__ == "__main__":
    sys.exit(main())
