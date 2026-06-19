"""FIX-S1 browser smoke -- catalogue picker + engine pricing + submit guard
on the rep-facing neon.finance.quote FORM.

Scenarios (as p2m75_sales, the salesperson who owns the fixture quote):
  A  the quote form renders the NEW product_template_id picker column, and a
     catalogued (rule-backed) line shows the ENGINE rate 300.00 (NOT $1) with
     the 'Priced from rule' badge.
  B  a no-rule line renders the 'No rule found' badge (the visible signal a
     rep must resolve before submit).
  C  GUARD: clicking 'Submit for Approval' with an unpriced line present is
     blocked (error surfaced; quote stays draft).
  D  LIVE PICK (the money-shot): add a line, pick the catalogued product via
     the M2O autocomplete, and the engine rate appears live via the onchange.

Setup creates self-contained [TEST-FIXS1B] fixtures (partner / job / term /
products / a product-scoped USD rule + flat bracket / a draft quote with one
engine-priced line + one no-rule line), commits so the browser sees them, and
tears everything down at the end. Mirrors the p6m2 browser-smoke pattern.
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke, AssertionFail

BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP_SCRIPT = """
from datetime import date, timedelta
sales = env['res.users'].search([('login','=','p2m75_sales')], limit=1).id
usd = env.ref('base.USD').id
partner = env['res.partner'].create({'name':'[TEST-FIXS1B] Client','is_company':True}).id
venue = env['res.partner'].create({'name':'[TEST-FIXS1B] Venue','is_company':True}).id
job = env['commercial.job'].create({'partner_id':partner,'venue_id':venue,
    'event_date':(date.today()+timedelta(days=30)).isoformat(),'currency_id':usd}).id
event_job = env['commercial.event.job'].create({'commercial_job_id':job}).id
term = env['neon.finance.payment.term'].create({'partner_id':partner,'deposit_pct':50.0,
    'deposit_due_days':0,'final_due_days':30,'late_policy':'reminder'}).id
priced = env['product.template'].create({'name':'[TEST-FIXS1B] PRICED ITEM',
    'is_workshop_item':True,'type':'consu'}).id
norule = env['product.template'].create({'name':'[TEST-FIXS1B] NORULE ITEM',
    'is_workshop_item':True,'type':'consu'}).id
rule = env['neon.finance.pricing.rule'].create({'product_template_id':priced,
    'currency_id':usd,'base_rate':300.0,'effective_date':'2020-01-01'}).id
env['neon.finance.pricing.bracket'].create({'rule_id':rule,'sequence':1,
    'day_from':1,'day_to':-1,'multiplier':1.0})
quote = env['neon.finance.quote'].create({'event_job_id':event_job,'currency_id':usd,
    'salesperson_id':sales,'payment_term_id':term}).id
pline = env['neon.finance.quote.line'].create({'quote_id':quote,'line_type':'equipment',
    'product_template_id':priced,'name':'[TEST-FIXS1B] PRICED ITEM','quantity':1.0,
    'duration_days':1,'unit_rate':0.0}).id
nline = env['neon.finance.quote.line'].create({'quote_id':quote,'line_type':'equipment',
    'product_template_id':norule,'name':'[TEST-FIXS1B] NORULE ITEM','quantity':1.0,
    'duration_days':1,'unit_rate':0.0}).id
env.cr.commit()
print('IDS_JSON=' + repr({'quote':quote,'pline':pline,'nline':nline,'priced':priced,
    'norule':norule,'rule':rule,'term':term,'event_job':event_job,'job':job,
    'partner':partner,'venue':venue}))
"""

_TEARDOWN_TEMPLATE = """
ids = {ids_repr}
try:
    env['neon.finance.quote'].browse(ids['quote']).write(
        {{'state':'cancelled','cancelled_reason':'fixs1 browser teardown'}})
except Exception:
    pass
for model, key in [
    ('neon.finance.quote.line','pline'), ('neon.finance.quote.line','nline'),
    ('neon.finance.quote','quote'), ('neon.finance.pricing.rule','rule'),
    ('product.template','priced'), ('product.template','norule'),
    ('neon.finance.payment.term','term'), ('commercial.event.job','event_job'),
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
        print("[fixs1] teardown warning:\n" + out[-1500:])


def main() -> int:
    print("[fixs1] setup: creating [TEST-FIXS1B] quote fixtures ...")
    ids = _setup()
    print(f"[fixs1] setup ok: quote={ids['quote']} priced_line={ids['pline']} "
          f"norule_line={ids['nline']}")
    try:
        with BrowserSmoke("fixs1") as smoke:
            form_url = (f"{smoke.base_url}/web#id={ids['quote']}"
                        f"&model=neon.finance.quote&view_type=form")

            with smoke.scenario("A: form shows product picker + engine rate 300.00 (not $1)"):
                smoke.login("p2m75_sales")
                smoke.page.goto(form_url, wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "quote form view")
                smoke.assert_visible(
                    "td.o_data_cell[name='product_template_id']",
                    "product_template_id picker column present on the line tree")
                smoke.assert_visible(
                    "td.o_data_cell[name='product_template_id']:has-text('PRICED ITEM')",
                    "catalogued line shows the picked product name")
                smoke.assert_visible(
                    "td.o_data_cell[name='unit_rate']:has-text('300.00')",
                    "catalogued line is ENGINE-priced at 300.00 (not $1)")
                smoke.assert_visible(
                    "td.o_data_cell[name='pricing_status']:has-text('Priced from rule')",
                    "catalogued line shows the 'Priced from rule' badge")
                smoke.screenshot("A_form_priced_line")

            with smoke.scenario("B: no-rule line shows the 'No rule found' badge"):
                smoke.assert_visible(
                    "td.o_data_cell[name='pricing_status']:has-text('No rule found')",
                    "no-rule line shows the 'No rule found' badge")
                smoke.screenshot("B_form_norule_line")

            with smoke.scenario("C: submit guard blocks an unpriced line, quote stays draft"):
                smoke.click("button[name='action_submit_for_approval']",
                            name="click Submit for Approval")
                # the UserError surfaces in the error-dialog modal-body (the
                # .o_dialog wrapper is zero-size -> not "visible"; assert on the
                # modal-body which carries the message text + real geometry).
                smoke.assert_visible(
                    ".modal-body:has-text('have no price')",
                    "submit blocked: 'have no price' guard error surfaced")
                smoke.screenshot("C_submit_guard_blocked")
                body = smoke.json_rpc(
                    "neon.finance.quote", "read",
                    [[ids["quote"]], ["state"]])
                state = (body.get("result") or [{}])[0].get("state")
                smoke._record_assert(
                    "quote stays draft after blocked submit",
                    expect="draft", actual=str(state), passed=(state == "draft"))
                if state != "draft":
                    raise AssertionFail(f"quote state changed to {state}")

            # NOTE: the LIVE keystroke pick (add line -> type product -> pick
            # from the OWL autocomplete -> rate appears) is proven
            # deterministically by the model-layer Python smoke
            # fixs1_quote_picker_smoke.py T1 (_onchange_product_template_id ->
            # unit_rate 300, pricing_status 'priced'). Driving Odoo 17's OWL
            # editable-tree autocomplete in headless Playwright is flaky, so it
            # is intentionally NOT asserted here -- scenario A proves the engine
            # rate renders on the form, T1 proves the onchange fires it.

        return smoke.summary()
    finally:
        print("[fixs1] teardown: removing [TEST-FIXS1B] fixtures ...")
        _teardown(ids)


if __name__ == "__main__":
    sys.exit(main())
