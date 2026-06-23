"""UX-B-RATE browser smoke -- the catalogue hire rate on the product form.

Scenarios (as p2m75_sales):
  A  workshop product WITH a USD rule: the "Hire rate (USD/day)" field renders
     the resolved value (250), and the $1 list_price is NOT shown.
  B  workshop product with NO rule: the "set via Finance > Pricing Rules" hint
     shows, and neon_unit_rate is NOT shown (no rule -> blank path).
  C  non-workshop SKU: list_price is still shown (Solution B gating intact).

The resolver tiers, no-rule fallback, non-stored behaviour, and the kanban/list
surfacing are proven in the model smoke neon_unit_rate_smoke.py. This proves the
form renders the real day-rate (not $1).

Self-contained [TEST-UXBRB] fixtures, committed, torn down at the end.
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
cat1 = env['neon.equipment.category'].create({'name':'[TEST-UXBRB] Cat1','code':'TUXBRB1'}).id
cat2 = env['neon.equipment.category'].create({'name':'[TEST-UXBRB] Cat2','code':'TUXBRB2'}).id
ws = env['product.template'].create({'name':'[TEST-UXBRB] Rig','is_workshop_item':True,
    'equipment_category_id':cat1,'type':'consu'}).id
r = env['neon.finance.pricing.rule'].create({'product_template_id':ws,'currency_id':usd,
    'base_rate':250.0,'effective_date':'2020-01-01'}).id
env['neon.finance.pricing.bracket'].create({'rule_id':r,'sequence':1,'day_from':1,
    'day_to':-1,'multiplier':1.0})
wsn = env['product.template'].create({'name':'[TEST-UXBRB] NoRule','is_workshop_item':True,
    'equipment_category_id':cat2,'type':'consu'}).id
nonws = env['product.template'].create({'name':'[TEST-UXBRB] Plain','is_workshop_item':False,
    'type':'consu','sale_ok':True,'list_price':100.0}).id
env.cr.commit()
print('IDS_JSON=' + repr({'ws':ws,'wsn':wsn,'nonws':nonws,'rule':r,'cat1':cat1,'cat2':cat2}))
"""

_TEARDOWN_TEMPLATE = """
ids = {ids_repr}
for model, key in [
    ('neon.finance.pricing.rule','rule'),
    ('product.template','ws'), ('product.template','wsn'), ('product.template','nonws'),
    ('neon.equipment.category','cat1'), ('neon.equipment.category','cat2'),
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
        print("[neon_unit_rate] teardown warning:\n" + out[-1500:])


def _form_url(smoke, rec_id):
    return (f"{smoke.base_url}/web#id={rec_id}"
            f"&model=product.template&view_type=form")


def main() -> int:
    print("[neon_unit_rate] setup ...")
    ids = _setup()
    print(f"[neon_unit_rate] setup ok: ws={ids['ws']} wsn={ids['wsn']} nonws={ids['nonws']}")
    try:
        with BrowserSmoke("neon_unit_rate") as smoke:
            smoke.login("p2m75_sales")

            with smoke.scenario("A: workshop+rule form shows Hire rate 250, no $1"):
                smoke.page.goto(_form_url(smoke, ids['ws']), wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "workshop product form")
                smoke.assert_visible(
                    ".o_field_widget[name='neon_unit_rate']:has-text('250')",
                    "Hire rate (USD/day) renders the resolved 250")
                n = smoke.page.locator(
                    "div.o_form_view [name='list_price']").count()
                smoke._record_assert(
                    "$1 list_price NOT rendered for the workshop item",
                    expect="0", actual=str(n), passed=(n == 0))
                smoke.screenshot("A_workshop_rate")

            with smoke.scenario("B: workshop no-rule form shows the hint, no rate"):
                smoke.page.goto(_form_url(smoke, ids['wsn']), wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "no-rule product form")
                smoke.assert_visible(
                    "div.text-muted:has-text('Hire rate is set in Finance')",
                    "the 'set via Pricing Rules' hint shows")
                n = smoke.page.locator(
                    "div.o_form_view .o_field_widget[name='neon_unit_rate']").count()
                smoke._record_assert(
                    "no rate field shown when no rule resolves",
                    expect="0", actual=str(n), passed=(n == 0))
                smoke.screenshot("B_norule_hint")

            with smoke.scenario("C: non-workshop SKU still shows list_price"):
                smoke.page.goto(_form_url(smoke, ids['nonws']), wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "non-workshop product form")
                n = smoke.page.locator(
                    "div.o_form_view [name='list_price']").count()
                smoke._record_assert(
                    "list_price IS rendered for the non-workshop SKU",
                    expect=">=1", actual=str(n), passed=(n >= 1))
                smoke.screenshot("C_nonworkshop_listprice")

        return smoke.summary()
    finally:
        print("[neon_unit_rate] teardown ...")
        _teardown(ids)


if __name__ == "__main__":
    sys.exit(main())
