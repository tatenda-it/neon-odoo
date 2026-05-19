"""P6.M8 smoke -- invoice PDF QWeb template inherit.

Template structural sanity:
T2000  inherited template exists in registry
T2001  template arch contains the ZIMRA strip anchor
T2002  template arch contains the stage indicator anchor
T2003  template arch contains the payment terms block
T2004  template arch contains the banking block
T2005  template arch contains the T&Cs footer

Rendered HTML behaviour:
T2010  ZIMRA strip renders when at least one of TIN/BPN/VAT is set
T2011  ZIMRA strip suppressed when all three are null
T2012  stage indicator renders for multi-stage SCH- invoice
T2013  stage indicator suppressed for single-stage invoice
T2014  stage indicator suppressed for non-SCH- (vendor bill) invoice
T2015  payment terms block renders when invoice_origin -> quote -> term
T2016  payment terms block suppressed when origin parse fails
T2017  banking block highlights the matched currency
T2018  banking block renders for an invoice in either currency
"""
import re
from datetime import date, timedelta

from odoo.exceptions import UserError


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

ICP = env["ir.config_parameter"]
Move = env["account.move"]
Quote = env["neon.finance.quote"]
QuoteLine = env["neon.finance.quote.line"]
Sched = env["neon.finance.invoice.schedule"]
Term = env["neon.finance.payment.term"]
EventJob = env["commercial.event.job"]
View = env["ir.ui.view"]

usd = env.ref("base.USD")
zwg = env.ref("neon_finance.currency_zwg")
sales_user = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
assert sales_user

company = env.ref("base.main_company")
partner_for_inv = env["res.partner"].create({
    "name": "P6M8 Smoke Client", "is_company": True,
})
venue = env["res.partner"].create({
    "name": "P6M8 Smoke Venue", "is_company": True,
})

# Helpers ----------------------------------------------------------------

def _new_quote_with_lines(currency, sched_lines, sp=sales_user,
                          partner=partner_for_inv):
    j = env["commercial.job"].create({
        "partner_id": partner.id, "venue_id": venue.id,
        "event_date": date.today() + timedelta(days=30),
        "currency_id": currency.id,
    })
    ej = EventJob.create({"commercial_job_id": j.id})
    term = Term.create({
        "partner_id": partner.id, "deposit_pct": 50.0,
        "deposit_due_days": 0, "final_due_days": 30,
        "late_policy": "reminder",
    })
    q = Quote.create({
        "event_job_id": ej.id, "salesperson_id": sp.id,
        "currency_id": currency.id, "payment_term_id": term.id,
    })
    QuoteLine.create({
        "quote_id": q.id, "line_type": "other",
        "name": "P6M8 line", "quantity": 1, "duration_days": 1,
        "unit_rate": 1000.0, "pricing_status": "manual",
    })
    for sl in sched_lines:
        Sched.create(dict(sl, quote_id=q.id, currency_id=currency.id))
    q.sudo().write({"state": "sent"})
    q.sudo().with_user(sp).action_accept()
    q.invalidate_recordset()
    return q


def _render(invoice):
    """Render the QWeb invoice template against an invoice; returns
    HTML string. The standard print uses Report.report_action which
    needs wkhtmltopdf -- skip the PDF binding and call the QWeb
    renderer directly for assertion purposes."""
    rendered, _content_type = env["ir.actions.report"]._render_qweb_html(
        "account.report_invoice", invoice.ids)
    return rendered.decode("utf-8") if isinstance(rendered, bytes) else rendered


# ============================================================
print()
print("=" * 72)
print("T2000 - inherited template exists in registry")
print("=" * 72)
view = env.ref(
    "neon_finance.report_invoice_document_neon_finance", raise_if_not_found=False)
ok = bool(view)
print("  view id:", view.id if view else None)
print("T2000:", "PASS" if ok else "FAIL")
results["T2000"] = ok


# ============================================================
print()
print("=" * 72)
print("T2001 - arch contains ZIMRA strip anchor (name='neon_zimra_strip')")
print("=" * 72)
arch = view.arch
ok = 'name="neon_zimra_strip"' in arch
print("  has anchor:", ok)
print("T2001:", "PASS" if ok else "FAIL")
results["T2001"] = ok


# ============================================================
print()
print("=" * 72)
print("T2002 - arch contains stage indicator anchor")
print("=" * 72)
ok = 'name="neon_stage_indicator"' in arch
print("  has anchor:", ok)
print("T2002:", "PASS" if ok else "FAIL")
results["T2002"] = ok


# ============================================================
print()
print("=" * 72)
print("T2003 - arch contains payment terms block")
print("=" * 72)
ok = 'name="neon_payment_terms"' in arch
print("  has anchor:", ok)
print("T2003:", "PASS" if ok else "FAIL")
results["T2003"] = ok


# ============================================================
print()
print("=" * 72)
print("T2004 - arch contains banking block")
print("=" * 72)
ok = 'name="neon_banking"' in arch
print("  has anchor:", ok)
print("T2004:", "PASS" if ok else "FAIL")
results["T2004"] = ok


# ============================================================
print()
print("=" * 72)
print("T2005 - arch contains T&Cs footer")
print("=" * 72)
ok = 'name="neon_tcs_placeholder"' in arch
print("  has anchor:", ok)
print("T2005:", "PASS" if ok else "FAIL")
results["T2005"] = ok


# ============================================================
print()
print("=" * 72)
print("T2010 - ZIMRA strip renders when VAT is set")
print("=" * 72)
# Ensure VAT is set on the company partner (probe confirmed it is)
assert company.partner_id.vat, "test prerequisite: company VAT empty"
q_t2010 = _new_quote_with_lines(usd, [
    {"sequence": 1, "stage": "deposit",
     "trigger": "on_acceptance", "percentage": 100.0},
])
inv_t2010 = q_t2010.invoice_schedule_ids[0].invoice_id
html_t2010 = _render(inv_t2010)
ok = "Tax Information:" in html_t2010 and company.partner_id.vat in html_t2010
print("  has Tax Information block:", "Tax Information:" in html_t2010,
      "VAT in html:", company.partner_id.vat in html_t2010)
print("T2010:", "PASS" if ok else "FAIL")
results["T2010"] = ok


# ============================================================
print()
print("=" * 72)
print("T2011 - ZIMRA strip suppressed when TIN+BPN+VAT all null")
print("=" * 72)
# Temporarily clear all three to simulate fresh-install state
prior = {
    "vat": company.partner_id.vat,
    "tin": company.x_zimra_tin,
    "bpn": company.x_zimra_bpn,
}
company.partner_id.sudo().write({"vat": False})
company.sudo().write({"x_zimra_tin": False, "x_zimra_bpn": False})
html_t2011 = _render(inv_t2010)
ok = "Tax Information:" not in html_t2011
print("  Tax Information absent:", ok)
# Restore
company.partner_id.sudo().write({"vat": prior["vat"]})
company.sudo().write({"x_zimra_tin": prior["tin"], "x_zimra_bpn": prior["bpn"]})
print("T2011:", "PASS" if ok else "FAIL")
results["T2011"] = ok


# ============================================================
print()
print("=" * 72)
print("T2012 - stage indicator renders for multi-stage SCH- invoice")
print("=" * 72)
q_t2012 = _new_quote_with_lines(usd, [
    {"sequence": 1, "stage": "deposit",
     "trigger": "on_acceptance", "percentage": 50.0},
    {"sequence": 2, "stage": "final",
     "trigger": "on_acceptance", "percentage": 50.0},
])
# Both fire on accept -> two invoices
invs_t2012 = q_t2012.invoice_schedule_ids.mapped("invoice_id")
html_t2012 = _render(invs_t2012[0])
# QWeb renders `<t t-out>` values with surrounding whitespace from
# the template indentation; tolerate that in the assertion.
ok = ("Stage" in html_t2012
      and re.search(r"of\s+2\b", html_t2012) is not None)
print("  has 'Stage' + 'of 2' (ws-tolerant):", ok)
print("T2012:", "PASS" if ok else "FAIL")
results["T2012"] = ok


# ============================================================
print()
print("=" * 72)
print("T2013 - stage indicator suppressed for single-stage invoice")
print("=" * 72)
# T2010's invoice is single-stage 100%
html_t2013 = _render(inv_t2010)
# Single-stage = the t-if `_sched_total > 1` guard suppresses the
# whole `neon_stage_indicator` block. Anti-marker: the literal
# "of 1" pattern from our template's "of <t-out _sched_total>".
# Be ws-tolerant per T2012's lesson.
ok = re.search(r"of\s+1\b", html_t2013) is None
print("  no single-stage indicator:", ok)
print("T2013:", "PASS" if ok else "FAIL")
results["T2013"] = ok


# ============================================================
print()
print("=" * 72)
print("T2014 - stage indicator suppressed for non-SCH- invoice")
print("=" * 72)
# Build an invoice with no ref / arbitrary ref
plain_inv = Move.sudo().create({
    "move_type": "out_invoice",
    "partner_id": partner_for_inv.id,
    "currency_id": usd.id,
    "ref": "PLAIN-001",
    "invoice_line_ids": [(0, 0, {
        "name": "manual line",
        "quantity": 1.0, "price_unit": 500.0,
    })],
})
html_t2014 = _render(plain_inv)
ok = re.search(r"of\s+[2-9]\b", html_t2014) is None
print("  no stage 'of N>1' for non-SCH invoice:", ok)
print("T2014:", "PASS" if ok else "FAIL")
results["T2014"] = ok


# ============================================================
print()
print("=" * 72)
print("T2015 - payment terms block renders when origin -> quote -> term")
print("=" * 72)
html_t2015 = _render(inv_t2010)
# Payment term name shape: "50% deposit (on acceptance) / 30d final / reminder"
expected = q_t2010.payment_term_id.name
ok = expected in html_t2015 and "Payment Terms" in html_t2015
print("  expected term in html:", expected in html_t2015,
      "has 'Payment Terms' heading:", "Payment Terms" in html_t2015)
print("T2015:", "PASS" if ok else "FAIL")
results["T2015"] = ok


# ============================================================
print()
print("=" * 72)
print("T2016 - payment terms block suppressed when origin parse fails")
print("=" * 72)
html_t2016 = _render(plain_inv)
# plain_inv has no invoice_origin -> no payment_terms block
# Check the neon-specific heading is absent (stock invoice has its
# own "Payment Term" block from upstream; we look for our purple-
# heading literal text "Payment Terms")
# Our heading: <h5 style="color: #7165AC;...">Payment Terms</h5>
# Distinguish from Odoo's "Payment Term:" (singular) labels.
ok = "#7165AC" not in html_t2016 or (
    "Payment Terms" not in html_t2016.split("#7165AC", 1)[1][:200]
    if "#7165AC" in html_t2016 else True
)
# Simpler: the Neon banking block uses the same #7165AC heading. If
# the banking block IS rendered (it should be), #7165AC appears.
# Look for ABSENCE of the payment-term-name string instead.
ok = q_t2010.payment_term_id.name not in html_t2016
print("  Neon payment-term name absent:", ok)
print("T2016:", "PASS" if ok else "FAIL")
results["T2016"] = ok


# ============================================================
print()
print("=" * 72)
print("T2017 - banking highlights matched currency")
print("=" * 72)
html_t2017 = _render(inv_t2010)  # USD invoice
# The matched bank should carry the PAY IN THIS CURRENCY marker
ok = "PAY IN THIS CURRENCY" in html_t2017
print("  has match marker:", ok)
print("T2017:", "PASS" if ok else "FAIL")
results["T2017"] = ok


# ============================================================
print()
print("=" * 72)
print("T2018 - banking renders both accounts (USD + ZWG)")
print("=" * 72)
# Both bank account numbers should appear in the rendered HTML
ok = ("1153245035" in html_t2017 and "1153244969" in html_t2017
      and "CABS" in html_t2017)
print("  USD acc:", "1153245035" in html_t2017,
      "ZWG acc:", "1153244969" in html_t2017,
      "CABS:", "CABS" in html_t2017)
print("T2018:", "PASS" if ok else "FAIL")
results["T2018"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in (
    2000, 2001, 2002, 2003, 2004, 2005,
    2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018,
)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
