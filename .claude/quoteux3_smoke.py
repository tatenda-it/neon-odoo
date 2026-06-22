"""QUOTE-UX-3 model smoke — engine line discount surfaced on the Odoo form.

The discount fields + mutual-exclusion constraint/onchanges + the
_compute_subtotal -> totals chain ALREADY existed (used by the WA flow + PDF);
QUOTE-UX-3 is a view-only surfacing. This smoke proves the substance the form
relies on, deterministically (the live OWL keystroke recompute is flaky in
headless Playwright -- proven here, per the fixs1 precedent):

  - discount_pct folds into line_subtotal: unit_rate*(1-pct/100)*qty*days;
  - discount_amount folds in: (unit_rate-amount)*qty*days;
  - the onchange clears the sibling (discount_pct set -> discount_amount 0);
  - _check_discount raises when BOTH are set, and when amount > unit_rate;
  - the quote totals (untaxed / VAT / total) reflect the discounted subtotals;
  - wa12_discount_note stores (the read-only label the footer shows);
  - the FORM VIEW now lists discount_pct, discount_amount, wa12_discount_note,
    and the discount columns are default-VISIBLE (optional="show", not "hide").

All writes roll back.
"""
from odoo import fields
from odoo.exceptions import ValidationError

results = []


def chk(n, c):
    results.append((n, bool(c)))
    print(("  ok  " if c else "FAIL  ") + n)


USD = env.ref('base.USD')
rep = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1)
L = env['neon.finance.quote.line']


def mk_quote():
    partner = env['res.partner'].create(
        {'name': '[TEST-QUX3] Client', 'is_company': True})
    venue = env['res.partner'].create(
        {'name': '[TEST-QUX3] Venue', 'is_company': True})
    job = env['commercial.job'].create({
        'partner_id': partner.id, 'venue_id': venue.id,
        'event_date': fields.Date.today(), 'currency_id': USD.id})
    ej = env['commercial.event.job'].create({'commercial_job_id': job.id})
    return env['neon.finance.quote'].create({
        'event_job_id': ej.id, 'currency_id': USD.id,
        'salesperson_id': rep.id})


try:
    # 1. discount_pct folds into line_subtotal: 100*(1-0.10)*2*3 = 540
    q = mk_quote()
    l = L.create({'quote_id': q.id, 'line_type': 'equipment', 'name': 'RIG',
                  'quantity': 2.0, 'duration_days': 3, 'unit_rate': 100.0,
                  'pricing_status': 'manual', 'discount_pct': 10.0})
    chk("discount_pct folds into line_subtotal (540)",
        abs(l.line_subtotal - 540.0) < 0.01)
    env.cr.rollback()

    # 2. discount_amount folds in: (100-25)*2*3 = 450
    q = mk_quote()
    l = L.create({'quote_id': q.id, 'line_type': 'equipment', 'name': 'RIG',
                  'quantity': 2.0, 'duration_days': 3, 'unit_rate': 100.0,
                  'pricing_status': 'manual', 'discount_amount': 25.0})
    chk("discount_amount folds into line_subtotal (450)",
        abs(l.line_subtotal - 450.0) < 0.01)
    env.cr.rollback()

    # 3. onchange clears the sibling (in-memory .new() -> no DB constraint)
    nl = L.new({'unit_rate': 100.0, 'discount_amount': 20.0,
                'discount_pct': 10.0})
    nl._onchange_discount_pct()
    chk("onchange: setting discount_pct clears discount_amount",
        nl.discount_amount == 0.0)
    nl2 = L.new({'unit_rate': 100.0, 'discount_pct': 10.0,
                 'discount_amount': 20.0})
    nl2._onchange_discount_amount()
    chk("onchange: setting discount_amount clears discount_pct",
        nl2.discount_pct == 0.0)

    # 4. _check_discount raises when BOTH set
    q = mk_quote()
    raised = False
    try:
        L.create({'quote_id': q.id, 'line_type': 'equipment', 'name': 'RIG',
                  'quantity': 1.0, 'duration_days': 1, 'unit_rate': 100.0,
                  'pricing_status': 'manual', 'discount_pct': 10.0,
                  'discount_amount': 5.0})
    except ValidationError:
        raised = True
    chk("_check_discount raises when BOTH pct + amount set", raised)
    env.cr.rollback()

    # 5. _check_discount raises when amount > unit_rate (markup guard)
    q = mk_quote()
    raised = False
    try:
        L.create({'quote_id': q.id, 'line_type': 'equipment', 'name': 'RIG',
                  'quantity': 1.0, 'duration_days': 1, 'unit_rate': 100.0,
                  'pricing_status': 'manual', 'discount_amount': 150.0})
    except ValidationError:
        raised = True
    chk("_check_discount raises when amount > unit_rate", raised)
    env.cr.rollback()

    # 6. quote totals reflect the discounted subtotals. (The line auto-applies
    #    the default sale VAT, so amount_untaxed is the discounted base and VAT
    #    lands on top of it; clearing the tax collapses total to that base.)
    q = mk_quote()
    l = L.create({'quote_id': q.id, 'line_type': 'equipment', 'name': 'RIG',
                  'quantity': 1.0, 'duration_days': 1, 'unit_rate': 200.0,
                  'pricing_status': 'manual', 'discount_pct': 25.0})
    chk("quote amount_untaxed reflects discount (150)",
        abs(q.amount_untaxed - 150.0) < 0.01)
    if l.tax_id:
        chk("VAT applies on the DISCOUNTED base (total == line_total_taxed)",
            q.amount_tax > 0 and abs(q.amount_total - l.line_total_taxed) < 0.01)
    else:
        chk("VAT applies on the DISCOUNTED base (no default tax -- skipped)",
            True)
    # no-tax path: clearing the tax -> total collapses to the discounted base
    l.tax_id = False
    chk("no-tax: amount_total == discounted subtotal (150), VAT 0",
        abs(q.amount_total - 150.0) < 0.01 and abs(q.amount_tax) < 0.01)
    env.cr.rollback()

    # 7. wa12_discount_note stores (the read-only label the footer shows)
    q = mk_quote()
    q.wa12_discount_note = "Discount USD 50.00 (incl. VAT)"
    chk("wa12_discount_note stores the display label",
        q.wa12_discount_note == "Discount USD 50.00 (incl. VAT)")
    env.cr.rollback()

    # 8. the FORM VIEW now lists the three fields, discount columns default-shown
    arch = env.ref('neon_finance.neon_finance_quote_view_form').arch
    chk("form view lists discount_pct", 'name="discount_pct"' in arch)
    chk("form view lists discount_amount", 'name="discount_amount"' in arch)
    chk("form view lists wa12_discount_note",
        'name="wa12_discount_note"' in arch)
    # scoped to the discount_pct element: it carries optional="show", not "hide"
    seg = (arch.split('name="discount_pct"', 1)[1][:80]
           if 'name="discount_pct"' in arch else '')
    chk("discount_pct column default-VISIBLE (optional=show, not hide)",
        'optional="show"' in seg and 'optional="hide"' not in seg)
finally:
    env.cr.rollback()

passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
