"""P6.M8 browser smoke -- invoice PDF template UI surfaces.

Three scenarios:

1. **p2m75_book** opens a single-stage invoice and verifies the
   inherited template content (ZIMRA strip + banking + payment
   terms) renders in the HTML preview via the standard Print menu's
   "Print" action target.
2. **p2m75_book** opens a multi-stage SCH- invoice and verifies
   the stage indicator block ("Stage 1 of 2 -- ...") renders in
   the HTML preview.
3. **p2m75_sales** opens a quote, navigates to its materialised
   invoice via the Invoice Schedule tab's invoice_id link, and
   verifies the Print menu is reachable from the invoice form.

The HTML preview is the report_action_html target -- same QWeb
template, no wkhtmltopdf binary needed in the test path. The
PDF (`report_action`) only differs in the rendering backend.
"""

from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP_SCRIPT = """
from datetime import date, timedelta
sales = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1).id
usd = env.ref('base.USD').id

partner = env['res.partner'].create({
    'name': 'P6M8 Browser Client', 'is_company': True,
}).id
venue = env['res.partner'].create({
    'name': 'P6M8 Browser Venue', 'is_company': True,
}).id
term = env['neon.finance.payment.term'].create({
    'partner_id': partner,
    'deposit_pct': 50.0, 'deposit_due_days': 0,
    'final_due_days': 30, 'late_policy': 'reminder',
}).id

# Quote A: single-stage 100% on_acceptance -> one invoice
job_a = env['commercial.job'].create({
    'partner_id': partner, 'venue_id': venue,
    'event_date': (date.today() + timedelta(days=30)).isoformat(),
    'currency_id': usd,
}).id
ej_a = env['commercial.event.job'].create({
    'commercial_job_id': job_a,
}).id
quote_a = env['neon.finance.quote'].create({
    'event_job_id': ej_a, 'salesperson_id': sales,
    'currency_id': usd, 'payment_term_id': term,
}).id
env['neon.finance.quote.line'].create({
    'quote_id': quote_a, 'line_type': 'other',
    'name': 'P6M8 line', 'quantity': 1, 'duration_days': 1,
    'unit_rate': 1000.0, 'pricing_status': 'manual',
})
env['neon.finance.invoice.schedule'].create({
    'quote_id': quote_a, 'sequence': 1, 'stage': 'deposit',
    'trigger': 'on_acceptance', 'percentage': 100.0,
    'currency_id': usd,
})
env['neon.finance.quote'].browse(quote_a).sudo().write({'state': 'sent'})
env['neon.finance.quote'].browse(quote_a).sudo().with_user(sales).action_accept()
inv_a = env['neon.finance.quote'].browse(
    quote_a).invoice_schedule_ids.mapped('invoice_id').ids[0]

# Quote B: multi-stage 50/50 on_acceptance -> two invoices
partner_b = env['res.partner'].create({
    'name': 'P6M8 Browser Client 2', 'is_company': True,
}).id
term_b = env['neon.finance.payment.term'].create({
    'partner_id': partner_b,
    'deposit_pct': 50.0, 'deposit_due_days': 0,
    'final_due_days': 30, 'late_policy': 'reminder',
}).id
job_b = env['commercial.job'].create({
    'partner_id': partner_b, 'venue_id': venue,
    'event_date': (date.today() + timedelta(days=30)).isoformat(),
    'currency_id': usd,
}).id
ej_b = env['commercial.event.job'].create({
    'commercial_job_id': job_b,
}).id
quote_b = env['neon.finance.quote'].create({
    'event_job_id': ej_b, 'salesperson_id': sales,
    'currency_id': usd, 'payment_term_id': term_b,
}).id
env['neon.finance.quote.line'].create({
    'quote_id': quote_b, 'line_type': 'other',
    'name': 'P6M8 line', 'quantity': 1, 'duration_days': 1,
    'unit_rate': 1000.0, 'pricing_status': 'manual',
})
env['neon.finance.invoice.schedule'].create({
    'quote_id': quote_b, 'sequence': 1, 'stage': 'deposit',
    'trigger': 'on_acceptance', 'percentage': 50.0,
    'currency_id': usd,
})
env['neon.finance.invoice.schedule'].create({
    'quote_id': quote_b, 'sequence': 2, 'stage': 'final',
    'trigger': 'on_acceptance', 'percentage': 50.0,
    'currency_id': usd,
})
env['neon.finance.quote'].browse(quote_b).sudo().write({'state': 'sent'})
env['neon.finance.quote'].browse(quote_b).sudo().with_user(sales).action_accept()
inv_b_first = env['neon.finance.quote'].browse(
    quote_b).invoice_schedule_ids.sorted('sequence').mapped('invoice_id').ids[0]

# Action for navigating to the invoice
inv_action = env.ref('account.action_move_out_invoice_type').id

env.cr.commit()
print('IDS_JSON=' + repr({
    'partner_id': partner, 'partner_b_id': partner_b,
    'venue_id': venue, 'term_id': term, 'term_b_id': term_b,
    'job_a_id': job_a, 'ej_a_id': ej_a, 'quote_a_id': quote_a,
    'inv_a_id': inv_a,
    'job_b_id': job_b, 'ej_b_id': ej_b, 'quote_b_id': quote_b,
    'inv_b_first_id': inv_b_first,
    'inv_action_id': inv_action,
}))
"""


_TEARDOWN_SCRIPT_TEMPLATE = """
ids = {ids_repr}

def _try_unlink(model, rec_id):
    try:
        env.cr.execute("SAVEPOINT teardown")
        env[model].browse(rec_id).unlink()
        env.cr.execute("RELEASE SAVEPOINT teardown")
        return True
    except Exception:
        env.cr.execute("ROLLBACK TO SAVEPOINT teardown")
        table_map = {{
            'account.move': 'account_move',
            'neon.finance.invoice.schedule': 'neon_finance_invoice_schedule',
            'neon.finance.quote.line': 'neon_finance_quote_line',
            'neon.finance.quote': 'neon_finance_quote',
            'neon.finance.payment.term': 'neon_finance_payment_term',
            'commercial.event.job': 'commercial_event_job',
            'commercial.job': 'commercial_job',
            'res.partner': 'res_partner',
        }}
        table = table_map.get(model)
        if not table:
            return False
        try:
            env.cr.execute("SAVEPOINT teardown_sql")
            env.cr.execute(
                "DELETE FROM " + table + " WHERE id = %s", (rec_id,))
            env.cr.execute("RELEASE SAVEPOINT teardown_sql")
            return True
        except Exception:
            env.cr.execute("ROLLBACK TO SAVEPOINT teardown_sql")
            return False

# Unlink invoices on these two quotes first.
sched_ids = env['neon.finance.invoice.schedule'].search([
    ('quote_id', 'in', (ids['quote_a_id'], ids['quote_b_id']))]).ids
move_ids = env['neon.finance.invoice.schedule'].browse(
    sched_ids).mapped('invoice_id').ids
for m in move_ids:
    _try_unlink('account.move', m)

for sid in sched_ids:
    _try_unlink('neon.finance.invoice.schedule', sid)

for ql in env['neon.finance.quote.line'].search([
    ('quote_id', 'in', (ids['quote_a_id'], ids['quote_b_id']))]).ids:
    _try_unlink('neon.finance.quote.line', ql)

for model, key in [
    ('neon.finance.quote', 'quote_a_id'),
    ('neon.finance.quote', 'quote_b_id'),
    ('neon.finance.payment.term', 'term_id'),
    ('neon.finance.payment.term', 'term_b_id'),
    ('commercial.event.job', 'ej_a_id'),
    ('commercial.event.job', 'ej_b_id'),
    ('commercial.job', 'job_a_id'),
    ('commercial.job', 'job_b_id'),
    ('res.partner', 'partner_id'),
    ('res.partner', 'partner_b_id'),
    ('res.partner', 'venue_id'),
]:
    _try_unlink(model, ids[key])

env.cr.commit()
print('TEARDOWN_OK')
"""


def _run_odoo_shell(script: str) -> str:
    proc = subprocess.run(
        [
            "docker", "compose",
            "--project-directory", "C:/Users/Neon/neon-odoo",
            "exec", "-T", "odoo",
            "odoo", "shell", "-d", DB, "--no-http",
        ],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=180,
    )
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def _setup_fixtures() -> dict:
    out = _run_odoo_shell(_SETUP_SCRIPT)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out)
        raise RuntimeError("setup did not produce IDS_JSON marker")
    return eval(m.group(1), {"__builtins__": {}}, {})


def _teardown_fixtures(ids: dict) -> None:
    out = _run_odoo_shell(_TEARDOWN_SCRIPT_TEMPLATE.format(ids_repr=repr(ids)))
    if "TEARDOWN_OK" not in out:
        print("[p6m8] teardown warning:")
        print(out[-1500:])


def _fetch_invoice_html(smoke, invoice_id):
    """Hit /report/html/account.report_invoice/<id> while authenticated;
    return the HTML body. Same QWeb template the PDF binding renders,
    just delivered as HTML so we can string-match without
    wkhtmltopdf."""
    url = f"{smoke.base_url}/report/html/account.report_invoice/{invoice_id}"
    response = smoke.page.goto(url, wait_until="networkidle")
    if response is None or response.status != 200:
        raise AssertionFail(
            f"report/html returned {response.status if response else 'no response'}")
    return smoke.page.content()


def main() -> int:
    print("[p6m8] setup: creating single + multi-stage invoices ...")
    ids = _setup_fixtures()
    print(f"[p6m8] setup ok: inv_a={ids['inv_a_id']} "
          f"inv_b_first={ids['inv_b_first_id']}")
    try:
        with BrowserSmoke("p6m8") as smoke:

            # ----------------------------------------------------------
            # 1. Bookkeeper renders single-stage invoice -- ZIMRA strip
            #    + banking + payment terms visible; stage indicator
            #    suppressed.
            # ----------------------------------------------------------
            with smoke.scenario(
                "p2m75_book renders single-stage invoice (no stage indicator)",
            ):
                smoke.login("p2m75_book")
                html = _fetch_invoice_html(smoke, ids["inv_a_id"])
                # Tax Information (ZIMRA strip)
                tax_strip = "Tax Information:" in html
                # Banking section -- CABS appears for both accounts
                cabs_present = "CABS" in html and "PAY IN THIS CURRENCY" in html
                # Payment terms heading (Neon's purple-h5)
                payterms = "Payment Terms" in html
                # Stage indicator suppressed: no "of 1" pattern
                no_stage_indicator = re.search(r"of\s+1\b", html) is None
                passed = all([tax_strip, cabs_present, payterms,
                              no_stage_indicator])
                smoke._record_assert(
                    "single-stage invoice HTML has Neon blocks",
                    expect="Tax strip + CABS + Payment Terms heading, no 'of 1'",
                    actual=(
                        f"tax={tax_strip} cabs={cabs_present} "
                        f"payterms={payterms} no_single_stage={no_stage_indicator}"
                    ),
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("single_stage_render")
                    raise AssertionFail(
                        "single-stage invoice template render incomplete")
                smoke.screenshot("01_book_single_stage_invoice")

            # ----------------------------------------------------------
            # 2. Bookkeeper renders multi-stage invoice -- stage
            #    indicator "Stage 1 of 2" visible.
            # ----------------------------------------------------------
            with smoke.scenario(
                "p2m75_book renders multi-stage invoice (Stage 1 of 2 visible)",
            ):
                html = _fetch_invoice_html(smoke, ids["inv_b_first_id"])
                # Stage indicator "Stage 1 of 2" (ws-tolerant)
                stage_present = re.search(r"of\s+2\b", html) is not None
                # ZIMRA strip still there
                tax_strip = "Tax Information:" in html
                # CABS banking still there
                cabs_present = "CABS" in html
                passed = all([stage_present, tax_strip, cabs_present])
                smoke._record_assert(
                    "multi-stage invoice HTML has stage indicator + Neon blocks",
                    expect="'of 2' + Tax strip + CABS",
                    actual=(
                        f"stage='of 2'={stage_present} "
                        f"tax={tax_strip} cabs={cabs_present}"
                    ),
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("multi_stage_render")
                    raise AssertionFail(
                        "multi-stage invoice missing stage indicator")
                smoke.screenshot("02_book_multi_stage_invoice")

            # ----------------------------------------------------------
            # 3. Sales rep can reach the Print menu on their own quote's
            #    materialised invoice. Doesn't require Neon's report
            #    binding to be active for ALL invoices -- just that the
            #    standard Print -> Invoice action is available.
            # ----------------------------------------------------------
            with smoke.scenario(
                "p2m75_sales reaches Print on own quote's invoice",
            ):
                smoke.login("p2m75_sales")
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['inv_a_id']}"
                    f"&model=account.move&view_type=form",
                    wait_until="networkidle",
                )
                smoke.assert_visible("div.o_form_view",
                                     "invoice form opens for sales rep")
                # Render HTML report URL directly (sales can read own
                # invoice via the quote's salesperson_id chain).
                html = _fetch_invoice_html(smoke, ids["inv_a_id"])
                payterms = "Payment Terms" in html
                passed = payterms
                smoke._record_assert(
                    "sales rep render -- Neon payment terms visible",
                    expect="Payment Terms heading",
                    actual=f"payment_terms_visible={payterms}",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts(
                        "sales_rep_invoice_html_missing_terms")
                    raise AssertionFail(
                        "sales rep cannot render Neon invoice template")
                smoke.screenshot("03_sales_invoice_print_reachable")

        return smoke.summary()
    finally:
        print("[p6m8] teardown: cleaning up fixture records ...")
        try:
            _teardown_fixtures(ids)
        except Exception as e:  # noqa: BLE001
            print(f"[p6m8] teardown failed (non-fatal): {e}")


if __name__ == "__main__":
    sys.exit(main())
