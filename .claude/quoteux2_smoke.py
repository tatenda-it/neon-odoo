"""QUOTE-UX-2 (Solution A) model smoke — retire the stock quote door.

Asserts the data-level outcome of making the engine quote the single door:
  - the 5 stock sale.order quote/order/to-invoice menus are gated to the
    legacy group (held by NOBODY) -> invisible to every tier;
  - CRM "My Quotations" (266) is redirected onto the engine quote action and
    gated to the quoting tiers;
  - a findable top-level "My Quotation" menu points at the engine action;
  - the Invoicing -> Customers -> Quotes engine menu is unchanged;
  - the ZWG list_price pricelist is deactivated;
  - the 3 existing stock orders that referenced it are UNTOUCHED;
  - a rep sees the engine doors but none of the stock doors (and a non-super
    director tier also no longer sees stock Orders);
  - the engine quote itself still creates + computes (the hide broke nothing).

Everything that writes rolls back.
"""
from odoo import fields

results = []


def chk(n, c):
    results.append((n, bool(c)))
    print(("  ok  " if c else "FAIL  ") + n)


def gids(rec):
    return set(rec.groups_id.ids)


leg = env.ref('neon_sales.group_neon_legacy_stock_sales')
eng = env.ref('neon_finance.neon_finance_quote_action')
fin = (env.ref('neon_finance.group_neon_finance_sales')
       | env.ref('neon_finance.group_neon_finance_bookkeeper')
       | env.ref('neon_finance.group_neon_finance_approver'))
Menu = env['ir.ui.menu']

STOCK = ['sale.menu_sale_quotations', 'sale.menu_sale_order',
         'sale.menu_sale_invoicing', 'sale.menu_sale_order_invoice',
         'sale.menu_sale_order_upselling']

# --- legacy group + hidden stock doors ---
chk("legacy group held by NOBODY", len(leg.users) == 0)
for xid in STOCK:
    m = env.ref(xid)
    chk("hidden: %s gated to legacy-only" % xid, gids(m) == {leg.id})
    chk("hidden: %s reachable by 0 users" % xid, len(m.groups_id.users) == 0)

# --- CRM "My Quotations" redirected to the engine ---
m266 = env.ref('sale_crm.sale_order_menu_quotations_crm')
chk("266 action repointed to the ENGINE quote action",
    bool(m266.action) and m266.action._name == 'ir.actions.act_window'
    and m266.action.id == eng.id)
chk("266 gated to the quoting groups", gids(m266) == set(fin.ids))

# --- top-level findable door ---
top = env.ref('neon_sales.menu_neon_quotes_toplevel')
chk("top-level 'My Quotation' is parentless (top-level)", not top.parent_id)
chk("top-level action is the engine quote action",
    bool(top.action) and top.action.id == eng.id)
chk("top-level gated to the quoting groups", gids(top) == set(fin.ids))

# --- finance Invoicing engine menu untouched ---
inv = env.ref('neon_finance.menu_neon_finance_quotes')
chk("Invoicing->Customers->Quotes engine menu intact",
    bool(inv.action) and inv.action.id == eng.id)

# --- ZWG pricelist neutralised + 3 existing orders intact ---
pl = env.ref('neon_sales.pricelist_neon_zwg')
chk("ZWG pricelist deactivated", not pl.active)
baseline = {10: 15619.01, 9: 1039.50, 4: 15303.75}
for oid, base in baseline.items():
    o = env['sale.order'].browse(oid)
    chk("stock order %d (%s) untouched by deactivation" % (oid, o.name),
        o.exists() and abs(o.amount_total - base) < 0.01
        and o.pricelist_id.id == pl.id)

# --- rep visibility: engine doors yes, stock doors no ---
rep = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1)
for xid in STOCK[:3]:
    chk("rep does NOT see %s" % xid,
        not Menu.with_user(rep).search([('id', '=', env.ref(xid).id)]))
for xid in ['sale_crm.sale_order_menu_quotations_crm',
            'neon_sales.menu_neon_quotes_toplevel',
            'neon_finance.menu_neon_finance_quotes']:
    chk("rep SEES %s" % xid,
        bool(Menu.with_user(rep).search([('id', '=', env.ref(xid).id)])))

# --- a non-superuser director tier (approver) also loses stock Orders ---
appr = env['res.users'].search([('login', '=', 'p2m75_approver')], limit=1)
chk("approver does NOT see stock Orders",
    not Menu.with_user(appr).search(
        [('id', '=', env.ref('sale.menu_sale_order').id)]))

# --- engine quote still works (create + compute) ---
try:
    USD = env.ref('base.USD')
    partner = env['res.partner'].create(
        {'name': '[TEST-QUX2] Client', 'is_company': True})
    venue = env['res.partner'].create(
        {'name': '[TEST-QUX2] Venue', 'is_company': True})
    job = env['commercial.job'].create({
        'partner_id': partner.id, 'venue_id': venue.id,
        'event_date': fields.Date.today(), 'currency_id': USD.id})
    ej = env['commercial.event.job'].create({'commercial_job_id': job.id})
    q = env['neon.finance.quote'].create({
        'event_job_id': ej.id, 'currency_id': USD.id,
        'salesperson_id': rep.id})
    env['neon.finance.quote.line'].create({
        'quote_id': q.id, 'line_type': 'equipment', 'name': 'TEST RIG',
        'quantity': 1.0, 'duration_days': 2, 'unit_rate': 250.0,
        'pricing_status': 'manual'})
    chk("engine quote still creates + computes total",
        q.amount_total > 0
        and abs(q.amount_total
                - sum(q.line_ids.mapped('line_total_taxed'))) < 0.01)
finally:
    env.cr.rollback()

passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
