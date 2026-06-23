"""UX-B-RATE model smoke -- product-level neon_unit_rate (catalogue hire rate).

Proves the computed field resolves the engine's day-1 USD rate via the SAME
tiers the quote line uses (product rule -> category fallback), is blank when no
rule resolves, is NON-STORED (live), and that Solution B's gating is intact
(non-workshop SKUs keep list_price). Display-only -- engine untouched.

All writes roll back.
"""
from odoo import fields

results = []


def chk(n, c):
    results.append((n, bool(c)))
    print(("  ok  " if c else "FAIL  ") + n)


USD = env.ref('base.USD')
P = env['product.template']
Rule = env['neon.finance.pricing.rule']
Br = env['neon.finance.pricing.bracket']
Cat = env['neon.equipment.category']


def mk_rule(vals):
    r = Rule.create(vals)
    Br.create({'rule_id': r.id, 'sequence': 1, 'day_from': 1, 'day_to': -1,
               'multiplier': 1.0})
    return r


try:
    cat1 = Cat.create({'name': '[TEST-UXBR] Cat1', 'code': 'TUXBR1'})
    cat2 = Cat.create({'name': '[TEST-UXBR] Cat2', 'code': 'TUXBR2'})
    cat3 = Cat.create({'name': '[TEST-UXBR] Cat3 norule', 'code': 'TUXBR3'})

    # 1) product-scoped USD rule -> neon_unit_rate == base_rate
    ws = P.create({'name': '[TEST-UXBR] Rig', 'is_workshop_item': True,
                   'equipment_category_id': cat1.id, 'type': 'consu'})
    mk_rule({'product_template_id': ws.id, 'currency_id': USD.id,
             'base_rate': 250.0, 'effective_date': '2020-01-01'})
    ws.invalidate_recordset()
    chk("product-scoped rule -> neon_unit_rate == base_rate 250",
        abs(ws.neon_unit_rate - 250.0) < 0.01 and ws.neon_unit_rate_has_rule)
    chk("neon_unit_rate currency is USD", ws.neon_unit_rate_currency_id == USD)

    # 2) category fallback: product with NO product rule, category has a rule
    mk_rule({'category_id': cat2.id, 'currency_id': USD.id,
             'base_rate': 80.0, 'effective_date': '2020-01-01'})
    ws2 = P.create({'name': '[TEST-UXBR] Rig2', 'is_workshop_item': True,
                    'equipment_category_id': cat2.id, 'type': 'consu'})
    chk("category fallback -> neon_unit_rate == category base_rate 80",
        abs(ws2.neon_unit_rate - 80.0) < 0.01 and ws2.neon_unit_rate_has_rule)

    # 3) no resolvable rule -> blank + has_rule False (the hint path)
    ws3 = P.create({'name': '[TEST-UXBR] Rig3', 'is_workshop_item': True,
                    'equipment_category_id': cat3.id, 'type': 'consu'})
    chk("no rule -> neon_unit_rate 0 + has_rule False (hint path)",
        ws3.neon_unit_rate == 0.0 and not ws3.neon_unit_rate_has_rule)

    # 4) non-workshop SKU keeps list_price (Solution B gating intact)
    nonws = P.create({'name': '[TEST-UXBR] Plain', 'is_workshop_item': False,
                      'type': 'consu', 'list_price': 100.0})
    chk("non-workshop keeps list_price 100", abs(nonws.list_price - 100.0) < 0.01)

    # 5) field is NON-STORED (resolves live)
    chk("neon_unit_rate is non-stored", P._fields['neon_unit_rate'].store is False)

    # 6) PRIMARY beats fallback: product rule wins over its category rule
    mk_rule({'category_id': cat1.id, 'currency_id': USD.id,
             'base_rate': 999.0, 'effective_date': '2020-01-01'})
    ws.invalidate_recordset()
    chk("per-product rule (250) beats category rule (999) for the same product",
        abs(ws.neon_unit_rate - 250.0) < 0.01)

    # 7) non-stored picks up a newer effective rule live
    mk_rule({'product_template_id': ws.id, 'currency_id': USD.id,
             'base_rate': 300.0, 'effective_date': '2021-01-01'})
    ws.invalidate_recordset()
    chk("non-stored picks up the newer effective rule (300)",
        abs(ws.neon_unit_rate - 300.0) < 0.01)

    # 8) view gating intact: form inherit gates list_price + shows neon_unit_rate
    inh = env.ref('neon_jobs.product_template_view_form_inherit_workshop').arch
    chk("form inherit still gates list_price on is_workshop_item",
        "@name='list_price'" in inh and 'is_workshop_item' in inh)
    chk("form inherit surfaces neon_unit_rate", 'name="neon_unit_rate"' in inh)
    tree = env.ref('neon_jobs.product_template_view_tree_hide_saleprice').arch
    chk("list view surfaces neon_unit_rate column", 'name="neon_unit_rate"' in tree)
    kb = env.ref(
        'neon_jobs.product_template_view_kanban_hide_saleprice_workshop').arch
    chk("kanban surfaces neon_unit_rate", 'name="neon_unit_rate"' in kb)
finally:
    env.cr.rollback()

passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
