"""FIX-S1 smoke -- catalogue picker + engine onchange + submit guard on
neon.finance.quote(.line).

Proves, at the model layer (what the new Odoo form relies on):
  T1  onchange: picking a product WITH a rule fires the engine live
      (line_type->equipment, auto-name, unit_rate = base_rate x bracket,
      pricing_status='priced').
  T2  onchange: a product with NO rule stamps 'no_rule', unit_rate stays 0.
  T3  create(): a product line with no hand-rate is engine-priced on save.
  T4  no_rule product + hand-typed rate -> 'manual' (rep-price fallback).
  T5  GUARD: action_submit_for_approval RAISES on an unpriced line
      (unit_rate<=0) and SUCCEEDS when every line is priced.

All fixtures are created under the shell superuser and ROLLED BACK at the
end -- nothing persists. Mirrors the in-shell smoke contract
('Total: N/M passed' summary line consumed by run_regression.sh).
"""
from datetime import date, timedelta

from odoo.exceptions import UserError

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(("  ok  " if cond else "FAIL  ") + name)


USD = env.ref('base.USD')
sales = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1)

# ---------------------------------------------------------------- fixtures
partner = env['res.partner'].create(
    {'name': '[TEST-FIXS1] Client', 'is_company': True})
venue = env['res.partner'].create(
    {'name': '[TEST-FIXS1] Venue', 'is_company': True})
job = env['commercial.job'].create({
    'partner_id': partner.id, 'venue_id': venue.id,
    'event_date': (date.today() + timedelta(days=30)).isoformat(),
    'currency_id': USD.id,
})
event_job = env['commercial.event.job'].create(
    {'commercial_job_id': job.id})
term = env['neon.finance.payment.term'].create({
    'partner_id': partner.id, 'deposit_pct': 50.0,
    'deposit_due_days': 0, 'final_due_days': 30, 'late_policy': 'reminder',
})
priced_prod = env['product.template'].create({
    'name': '[TEST-FIXS1] PRICED ITEM', 'is_workshop_item': True,
    'type': 'consu',
})
norule_prod = env['product.template'].create({
    'name': '[TEST-FIXS1] NORULE ITEM', 'is_workshop_item': True,
    'type': 'consu',
})
rule = env['neon.finance.pricing.rule'].create({
    'product_template_id': priced_prod.id, 'currency_id': USD.id,
    'base_rate': 300.0, 'effective_date': '2020-01-01',
})
env['neon.finance.pricing.bracket'].create({
    'rule_id': rule.id, 'sequence': 1, 'day_from': 1, 'day_to': -1,
    'multiplier': 1.0,
})


def new_quote():
    return env['neon.finance.quote'].create({
        'event_job_id': event_job.id, 'currency_id': USD.id,
        'salesperson_id': sales.id, 'payment_term_id': term.id,
    })


# ---------------------------------------------------------------- T1 onchange (priced)
q1 = new_quote()
line = env['neon.finance.quote.line'].new({
    'quote_id': q1.id, 'product_template_id': priced_prod.id,
    'name': False, 'quantity': 1.0, 'duration_days': 1, 'unit_rate': 0.0,
})
line._onchange_product_template_id()
check("T1 onchange sets line_type=equipment", line.line_type == 'equipment')
check("T1 onchange auto-names from product",
      line.name == '[TEST-FIXS1] PRICED ITEM')
check("T1 onchange engine rate = 300 (not $1 / free-text)",
      abs(line.unit_rate - 300.0) < 0.001)
check("T1 onchange pricing_status='priced'", line.pricing_status == 'priced')

# ---------------------------------------------------------------- T2 onchange (no_rule)
line2 = env['neon.finance.quote.line'].new({
    'quote_id': q1.id, 'product_template_id': norule_prod.id,
    'name': False, 'quantity': 1.0, 'duration_days': 1, 'unit_rate': 0.0,
})
line2._onchange_product_template_id()
check("T2 no-rule product -> pricing_status='no_rule'",
      line2.pricing_status == 'no_rule')
check("T2 no-rule product -> unit_rate stays 0",
      abs(line2.unit_rate) < 0.001)

# ---------------------------------------------------------------- T3 create() prices on save
q3 = new_quote()
cl = env['neon.finance.quote.line'].create({
    'quote_id': q3.id, 'line_type': 'equipment',
    'product_template_id': priced_prod.id, 'name': 'PRICED',
    'quantity': 1.0, 'duration_days': 1, 'unit_rate': 0.0,
})
check("T3 create() engine-prices product line = 300",
      abs(cl.unit_rate - 300.0) < 0.001)
check("T3 create() pricing_status='priced'", cl.pricing_status == 'priced')

# ---------------------------------------------------------------- T4 no_rule + hand rate -> manual
cl4 = env['neon.finance.quote.line'].create({
    'quote_id': q3.id, 'line_type': 'equipment',
    'product_template_id': norule_prod.id, 'name': 'NORULE',
    'quantity': 1.0, 'duration_days': 1, 'unit_rate': 50.0,
})
check("T4 no-rule + typed rate -> pricing_status='manual'",
      cl4.pricing_status == 'manual')

# ---------------------------------------------------------------- T5 submit guard
# 5a: an unpriced line BLOCKS submit
qg = new_quote()
env['neon.finance.quote.line'].create({
    'quote_id': qg.id, 'line_type': 'other', 'name': 'UNPRICED',
    'quantity': 1.0, 'duration_days': 1, 'unit_rate': 0.0,
})
blocked = False
try:
    qg.action_submit_for_approval()
except UserError:
    blocked = True
check("T5a unpriced line BLOCKS submit (UserError)", blocked)
check("T5a quote stays draft after blocked submit", qg.state == 'draft')

# 5b: a fully-priced quote submits cleanly (guard does not false-positive)
qok = new_quote()
env['neon.finance.quote.line'].create({
    'quote_id': qok.id, 'line_type': 'equipment',
    'product_template_id': priced_prod.id, 'name': 'PRICED',
    'quantity': 1.0, 'duration_days': 1, 'unit_rate': 0.0,
})
ok = True
try:
    qok.action_submit_for_approval()
except UserError as e:
    ok = False
    print("   submit-ok unexpectedly raised:", e)
check("T5b fully-priced quote submits (no false guard block)",
      ok and qok.state in ('pending_approval', 'approved'))

# ---------------------------------------------------------------- summary + rollback
passed = sum(1 for _, okk in results if okk)
total = len(results)
print("Total: %d/%d passed" % (passed, total))
env.cr.rollback()
