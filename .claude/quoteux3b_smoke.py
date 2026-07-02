"""QUOTE-UX-3b model smoke -- shared whole-quote discount method.

neon.finance.quote.apply_whole_quote_discount is the SINGLE implementation the
Odoo form wizard and the WhatsApp flow both call. This proves the algorithm
deterministically: uniform per-line distribution; incl-VAT vs ex-VAT basis;
the is_target (target-total) path; the realized-drop return; the
wa12_discount_note tie-out; UserError on each invalid case; idempotent
re-apply (clear-then-reapply, never stack); the wizard's action_apply wiring;
and the draft-only form button.

(WA PARITY is proven by pwa12_6 S13/S14, which drive the real refactored WA
path _wa12_whole_quote_discount -> apply_whole_quote_discount.)

All writes roll back.
"""
from odoo import fields
from odoo.exceptions import UserError

results = []


def chk(n, c):
    results.append((n, bool(c)))
    print(("  ok  " if c else "FAIL  ") + n)


USD = env.ref('base.USD')
rep = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1)
L = env['neon.finance.quote.line']


def mk_quote(rates):
    """A draft quote with one priced manual line per rate (qty 1, 1 day)."""
    partner = env['res.partner'].create(
        {'name': '[TEST-QUX3C] Client', 'is_company': True})
    venue = env['res.partner'].create(
        {'name': '[TEST-QUX3C] Venue', 'is_company': True})
    job = env['commercial.job'].create({
        'partner_id': partner.id, 'venue_id': venue.id,
        'event_date': fields.Date.today(), 'currency_id': USD.id})
    ej = env['commercial.event.job'].create({'commercial_job_id': job.id})
    q = env['neon.finance.quote'].create({
        'event_job_id': ej.id, 'currency_id': USD.id,
        'salesperson_id': rep.id})
    for i, r in enumerate(rates):
        L.create({'quote_id': q.id, 'line_type': 'equipment',
                  'name': 'RIG%d' % i, 'quantity': 1.0, 'duration_days': 1,
                  'unit_rate': r, 'pricing_status': 'manual'})
    return q


try:
    # A. incl-VAT discount amount: total drops by ~50, uniform per-line pct
    q = mk_quote([200.0, 100.0])
    base_total = q.amount_total
    realized = q.apply_whole_quote_discount(50.0)
    pcts = q.line_ids.mapped('discount_pct')
    chk("A: incl-VAT discount realized ~= 50", abs(realized - 50.0) < 0.05)
    chk("A: total dropped by ~50", abs(q.amount_total - (base_total - 50.0)) < 0.05)
    chk("A: distribution is UNIFORM across lines",
        len(set(round(p, 4) for p in pcts)) == 1 and pcts[0] > 0)
    chk("A: wa12_discount_note ties to achieved drop (incl)",
        "%.2f" % realized in (q.wa12_discount_note or "")
        and "incl" in (q.wa12_discount_note or "").lower())
    env.cr.rollback()

    # B. ex-VAT discount: untaxed (300) drops by 30
    q = mk_quote([200.0, 100.0])
    base_untaxed = q.amount_untaxed
    realized = q.apply_whole_quote_discount(30.0, ex_vat=True)
    chk("B: ex-VAT discount realized ~= 30", abs(realized - 30.0) < 0.05)
    chk("B: untaxed dropped by ~30",
        abs(q.amount_untaxed - (base_untaxed - 30.0)) < 0.05)
    chk("B: note labels ex-VAT basis",
        "ex vat" in (q.wa12_discount_note or "").lower())
    env.cr.rollback()

    # C. is_target (incl-VAT target total) -> total lands ~= 200
    q = mk_quote([200.0, 100.0])
    base_total = q.amount_total
    realized = q.apply_whole_quote_discount(200.0, is_target=True)
    chk("C: target total lands ~= 200", abs(q.amount_total - 200.0) < 0.05)
    chk("C: realized ~= base - 200", abs(realized - (base_total - 200.0)) < 0.05)
    env.cr.rollback()

    # D. idempotent re-apply: 50 then 30 -> clears first, total = base - 30
    q = mk_quote([200.0, 100.0])
    base_total = q.amount_total
    q.apply_whole_quote_discount(50.0)
    q.apply_whole_quote_discount(30.0)
    chk("D: re-apply REPLACES (not stacks): total = base - 30",
        abs(q.amount_total - (base_total - 30.0)) < 0.05)
    env.cr.rollback()

    # E. UserError cases
    def raises(fn):
        try:
            fn()
            return False
        except UserError:
            return True

    q = mk_quote([])  # no lines
    chk("E1: no lines raises", raises(lambda: q.apply_whole_quote_discount(10.0)))
    env.cr.rollback()

    q = mk_quote([0.0])  # unpriced -> base 0 <= placeholder
    chk("E2: base at/below placeholder raises",
        raises(lambda: q.apply_whole_quote_discount(10.0)))
    env.cr.rollback()

    q = mk_quote([200.0, 100.0])
    bt = q.amount_total
    chk("E3: target >= base raises",
        raises(lambda: q.apply_whole_quote_discount(bt + 10.0, is_target=True)))
    env.cr.rollback()

    q = mk_quote([200.0, 100.0])
    chk("E4: target <= 0 raises",
        raises(lambda: q.apply_whole_quote_discount(0.0, is_target=True)))
    env.cr.rollback()

    q = mk_quote([200.0, 100.0])
    bt = q.amount_total
    chk("E5: discount >= base raises",
        raises(lambda: q.apply_whole_quote_discount(bt + 10.0)))
    env.cr.rollback()

    # F. the wizard's action_apply wires to the shared method
    q = mk_quote([200.0, 100.0])
    base_total = q.amount_total
    wiz = env['neon.finance.whole.quote.discount.wizard'].create({
        'quote_id': q.id, 'mode': 'discount', 'basis': 'incl', 'amount': 50.0})
    wiz.action_apply()
    chk("F: wizard action_apply applies the discount (~50 off)",
        abs(q.amount_total - (base_total - 50.0)) < 0.05
        and bool(q.wa12_discount_note))
    env.cr.rollback()

    # G. PART 2 header polish (2026-07-02, Tatenda): the header BUTTON was
    # REMOVED; the form face of the whole-quote discount is now the INLINE
    # whole_quote_discount field in the totals summary (draft-only editable),
    # wired to the SAME shared apply_whole_quote_discount. The wizard model +
    # action method stay on the model (WA + programmatic modes) -- only the
    # form button went. New-spec assertions:
    arch = env.ref('neon_finance.neon_finance_quote_view_form').arch
    # split on the FIELD TAG, not the bare name (an arch comment mentions
    # apply_whole_quote_discount, which contains the name as a substring)
    tag = 'name="whole_quote_discount"'
    seg = arch.split(tag, 1)[1][:200] if tag in arch else ''
    chk("G: header button REMOVED; inline whole_quote_discount field present",
        'action_open_whole_quote_discount_wizard' not in arch
        and tag in arch)
    chk("G: inline discount is draft-only (readonly state != draft)",
        "state != 'draft'" in seg)
finally:
    env.cr.rollback()

passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
