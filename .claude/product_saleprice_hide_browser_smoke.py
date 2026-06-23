"""SOLUTION B (a) browser smoke -- hide the misleading $1 "Sales Price"
(list_price) on product views for workshop (hire) items.

The engine prices hire items via pricing rules (base_rate), NOT list_price,
which sits at the default $1 on workshop items. We hide list_price on the
product form + kanban for is_workshop_item (gated; non-workshop SKUs keep it)
and optional-hide the list column. Display-only -- nothing reads list_price.

Scenarios (as p2m75_sales):
  A  WORKSHOP product form: the "Sales Price" field is NOT rendered, the
     "Hire rate is set in Finance" hint IS shown, the Workshop tab + name
     render normally.
  B  NON-WORKSHOP product form: the "Sales Price" field IS still rendered
     (the gate preserves genuine non-workshop prices).

Engine pricing is proven UNAFFECTED at setup: a quote line for the workshop
product prices at the rule's base_rate (250.00), NOT the $1 list_price.

Self-contained [TEST-SOLB] fixtures, committed, torn down at the end.
"""
from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import BrowserSmoke  # noqa: F401

DB = "neon_crm"

_SETUP_SCRIPT = """
from odoo import fields
usd = env.ref('base.USD').id
cat = env['neon.equipment.category'].search([], limit=1)
if not cat:
    cat = env['neon.equipment.category'].create({'name': '[TEST-SOLB] Cat'})
# workshop (hire) product -- list_price left at the $1 default
ws = env['product.template'].create({
    'name': '[TEST-SOLB] Workshop Rig', 'is_workshop_item': True,
    'equipment_category_id': cat.id, 'type': 'consu'})
# non-workshop SKU with a genuine price
nonws = env['product.template'].create({
    'name': '[TEST-SOLB] Plain SKU', 'is_workshop_item': False,
    'type': 'consu', 'sale_ok': True, 'list_price': 100.0})
# product-scoped pricing rule so the ENGINE prices the workshop product
rule = env['neon.finance.pricing.rule'].create({
    'product_template_id': ws.id, 'currency_id': usd, 'base_rate': 250.0,
    'effective_date': '2020-01-01'})
env['neon.finance.pricing.bracket'].create({
    'rule_id': rule.id, 'sequence': 1, 'day_from': 1, 'day_to': -1,
    'multiplier': 1.0})
# prove engine pricing: a quote line for the workshop product prices at 250
partner = env['res.partner'].create({'name': '[TEST-SOLB] Client', 'is_company': True})
venue = env['res.partner'].create({'name': '[TEST-SOLB] Venue', 'is_company': True})
job = env['commercial.job'].create({'partner_id': partner.id, 'venue_id': venue.id,
    'event_date': fields.Date.today(), 'currency_id': usd})
ej = env['commercial.event.job'].create({'commercial_job_id': job.id})
q = env['neon.finance.quote'].create({'event_job_id': ej.id, 'currency_id': usd})
line = env['neon.finance.quote.line'].create({'quote_id': q.id, 'line_type': 'equipment',
    'product_template_id': ws.id, 'name': '[TEST-SOLB] Workshop Rig',
    'quantity': 1.0, 'duration_days': 1, 'unit_rate': 0.0})
env.cr.commit()
print('ENGINE_RATE=%.2f' % line.unit_rate)
print('WS_LISTPRICE=%.2f' % ws.list_price)
print('IDS_JSON=' + repr({'ws': ws.id, 'nonws': nonws.id, 'rule': rule.id,
    'quote': q.id, 'line': line.id, 'job': job.id, 'event_job': ej.id,
    'partner': partner.id, 'venue': venue.id}))
"""

_TEARDOWN_TEMPLATE = """
ids = {ids_repr}
try:
    env['neon.finance.quote'].browse(ids['quote']).write(
        {{'state': 'cancelled', 'cancelled_reason': 'solb teardown'}})
except Exception:
    pass
for model, key in [
    ('neon.finance.quote.line', 'line'), ('neon.finance.quote', 'quote'),
    ('neon.finance.pricing.rule', 'rule'),
    ('commercial.event.job', 'event_job'), ('commercial.job', 'job'),
    ('product.template', 'ws'), ('product.template', 'nonws'),
    ('res.partner', 'partner'), ('res.partner', 'venue'),
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
    ids = eval(m.group(1), {"__builtins__": {}}, {})
    er = re.search(r"ENGINE_RATE=([0-9.]+)", out)
    lp = re.search(r"WS_LISTPRICE=([0-9.]+)", out)
    ids["_engine_rate"] = float(er.group(1)) if er else -1.0
    ids["_ws_listprice"] = float(lp.group(1)) if lp else -1.0
    return ids


def _teardown(ids: dict) -> None:
    out = _run_odoo_shell(_TEARDOWN_TEMPLATE.format(ids_repr=repr(
        {k: v for k, v in ids.items() if not k.startswith('_')})))
    if "TEARDOWN_OK" not in out:
        print("[product_saleprice_hide] teardown warning:\n" + out[-1500:])


def main() -> int:
    print("[product_saleprice_hide] setup ...")
    ids = _setup()
    print(f"[product_saleprice_hide] setup ok: ws={ids['ws']} nonws={ids['nonws']} "
          f"engine_rate={ids['_engine_rate']} ws_list_price={ids['_ws_listprice']}")
    try:
        with BrowserSmoke("product_saleprice_hide") as smoke:
            smoke.login("p2m75_sales")

            # Engine pricing is UNAFFECTED (proven at setup): the workshop
            # product's list_price is the $1 default, but the engine priced a
            # quote line for it at the rule base_rate (250).
            smoke._record_assert(
                "engine prices the workshop product at base_rate 250 (not $1)",
                expect="250.0", actual=str(ids['_engine_rate']),
                passed=abs(ids['_engine_rate'] - 250.0) < 0.01)
            smoke._record_assert(
                "workshop product list_price is the misleading $1 default",
                expect="1.0", actual=str(ids['_ws_listprice']),
                passed=abs(ids['_ws_listprice'] - 1.0) < 0.01)

            ws_url = (f"{smoke.base_url}/web#id={ids['ws']}"
                      f"&model=product.template&view_type=form")
            nonws_url = (f"{smoke.base_url}/web#id={ids['nonws']}"
                         f"&model=product.template&view_type=form")

            with smoke.scenario("A: WORKSHOP form hides $1 Sales Price + shows hint"):
                smoke.page.goto(ws_url, wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "workshop product form")
                smoke.assert_visible(
                    ".o_field_widget[name='name']:has-text('Workshop Rig')",
                    "product name renders")
                # invisible OWL field -> removed from the DOM
                n = smoke.page.locator(
                    "div.o_form_view [name='list_price']").count()
                smoke._record_assert(
                    "Sales Price (list_price) NOT rendered for a workshop item",
                    expect="0", actual=str(n), passed=(n == 0))
                smoke.assert_visible(
                    "div.text-muted:has-text('Hire rate is set in Finance')",
                    "the 'rate set in Finance > Pricing Rules' hint shows")
                smoke.assert_visible(
                    "a.nav-link:has-text('Workshop')", "Workshop tab present")
                smoke.screenshot("A_workshop_no_saleprice")

            with smoke.scenario("B: NON-WORKSHOP form keeps Sales Price"):
                smoke.page.goto(nonws_url, wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "non-workshop product form")
                n = smoke.page.locator(
                    "div.o_form_view [name='list_price']").count()
                smoke._record_assert(
                    "Sales Price (list_price) IS rendered for a non-workshop SKU",
                    expect=">=1", actual=str(n), passed=(n >= 1))
                smoke.screenshot("B_nonworkshop_keeps_saleprice")

        return smoke.summary()
    finally:
        print("[product_saleprice_hide] teardown ...")
        _teardown(ids)


if __name__ == "__main__":
    sys.exit(main())
