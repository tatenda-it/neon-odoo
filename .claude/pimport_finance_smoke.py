"""P-IMPORT-FINANCE — Zoho invoice + expense reference import (neon_migration).
Exercises the REAL service (neon.zoho.importer.run_finance) against the REAL
models with [TEST-ZF] fixtures. Asserts: dry-run zero-writes, APPLY creates,
idempotent re-run, status buckets, partner LINK-only (missing→skip, never
create), expense billable + no-vendor, won-link populate on quote.archive (won
bucket NOT regressed), currency char, and INERTNESS (account.move customer
invoices + live neon.finance.quote count + QUO seq all unchanged). Run in
`odoo shell -d neon_crm`. Self-cleaning.
"""
_passed = _total = 0
results = {}


def _check(n, ok, d=""):
    global _passed, _total
    _total += 1
    if ok:
        _passed += 1
    results[n] = ok
    print("%s:" % n, "PASS" if ok else "FAIL", d if not ok else "")


env = env(context=dict(env.context, tracking_disable=True,
                       mail_create_nosubscribe=True,
                       mail_notify_force_send=False))
P = env["res.partner"].sudo()
INV = env["neon.finance.invoice.archive"].sudo()
EXP = env["neon.finance.expense.archive"].sudo()
QA = env["neon.finance.quote.archive"].sudo()
IMP = env["neon.zoho.importer"].sudo()
Seq = env["ir.sequence"].sudo()
Q = env["neon.finance.quote"].sudo()
AM = env["account.move"].sudo()
_INV_DOMAIN = [("move_type", "in", ("out_invoice", "out_refund"))]


def _purge():
    INV.with_context(active_test=False).search(
        [("zoho_invoice_number", "=like", "TESTZFINV-%")]).unlink()
    EXP.with_context(active_test=False).search(
        [("zoho_expense_id", "=like", "TESTZFEXP-%")]).unlink()
    QA.with_context(active_test=False).search(
        [("zoho_estimate_number", "=like", "TESTZF-EST%")]).unlink()
    P.with_context(active_test=False).search(
        [("zoho_source_id", "=like", "TESTZF-%")]).unlink()


_purge()

# ---- baseline (inertness) ----
AM_BEFORE = AM.search_count(_INV_DOMAIN)
Q_BEFORE = Q.search_count([])
_su = Seq.search([("code", "=", "neon.finance.quote.usd")], limit=1)
SEQ_BEFORE = _su.number_next_actual if _su else -1

# ---- fixtures: a directly-linkable partner, a SURVIVOR partner (for the
#      collapsed-twin fallback), + a won-bucket quote.archive (empty inv#) ----
p1 = P.create({"name": "[TEST-ZF] Client One", "zoho_source_id": "TESTZF-CUST1",
               "company_type": "company"})
p_surv = P.create({"name": "[TEST-ZF] Survivor Co", "zoho_source_id": "TESTZF-SURV",
                   "email": "zf-surv@test", "company_type": "company"})
qa1 = QA.create({"zoho_estimate_number": "TESTZF-EST1", "status_bucket": "won",
                 "zoho_status": "invoiced", "currency_code": "USD",
                 "amount_total": 115.5})

# customers export feeding the tier-2 fallback: a COLLAPSED twin shares the
# survivor's name+email but carries its own (non-retained) source_id.
CUSTOMERS = [
    {"zoho_source_id": "TESTZF-COLLAPSED", "name": "[TEST-ZF] Survivor Co",
     "email": "zf-surv@test"},
]

INVOICES = [
    {"zoho_invoice_number": "TESTZFINV-001", "zoho_customer_source_id": "TESTZF-CUST1",
     "zoho_estimate_number": "TESTZF-EST1", "invoice_date": "2025-05-01",
     "status": "paid", "currency_code": "USD", "salesperson_name": "lisar",
     "event_summary": "Gala", "amount_untaxed": 100.0, "amount_tax": 15.5,
     "amount_total": 115.5,
     "lines": [{"name": "RGB LED CAN", "description": "x", "unit": "qty",
                "quantity": 4, "unit_rate": 25.0, "line_total": 100.0,
                "zoho_item_id": "I1", "category_prefix": "LIGHTING"}]},
    {"zoho_invoice_number": "TESTZFINV-002", "zoho_customer_source_id": "TESTZF-CUST1",
     "status": "sent", "currency_code": "ZWG", "amount_total": 50.0, "lines": []},
    {"zoho_invoice_number": "TESTZFINV-003", "zoho_customer_source_id": "TESTZF-CUST1",
     "status": "void", "currency_code": "USD", "amount_total": 0.0, "lines": []},
    {"zoho_invoice_number": "TESTZFINV-004", "zoho_customer_source_id": "TESTZF-MISSING",
     "status": "paid", "currency_code": "USD", "amount_total": 10.0, "lines": []},
    {"zoho_invoice_number": "TESTZFINV-005", "zoho_customer_source_id": "TESTZF-COLLAPSED",
     "status": "paid", "currency_code": "USD", "amount_total": 30.0, "lines": []},
]
EXPENSES = [
    {"zoho_expense_id": "TESTZFEXP-001", "expense_date": "2025-05-02",
     "account_name": "Fuel", "description": "diesel", "status": "unbilled",
     "is_billable": True, "zoho_customer_source_id": "TESTZF-CUST1",
     "currency_code": "USD", "amount": 40.0, "tax": 6.2,
     "lines": [{"description": "diesel", "account_name": "Fuel", "amount": 40.0}]},
    {"zoho_expense_id": "TESTZFEXP-002", "expense_date": "2025-05-03",
     "account_name": "Casual Labour", "is_billable": True,
     "zoho_customer_source_id": "TESTZF-MISSING", "currency_code": "USD",
     "amount": 80.0},
    {"zoho_expense_id": "TESTZFEXP-003", "expense_date": "2025-05-04",
     "account_name": "Office", "is_billable": False, "currency_code": "USD",
     "amount": 20.0},
]

# ============================================================ T1 dry-run zero writes
i_before, e_before = INV.search_count([]), EXP.search_count([])
rep = IMP.run_finance(INVOICES, EXPENSES, apply=False, customers=CUSTOMERS)
_check("T1-dryrun-zero-writes",
       INV.search_count([]) == i_before and EXP.search_count([]) == e_before
       and not qa1.zoho_invoice_number,
       "writes leaked in dry-run")
_check("T1b-dryrun-counts",
       rep["invoices"]["created"] == 5            # ALL imported — nothing skipped
       and rep["invoices"]["fallback_linked"] == 1          # 005 -> survivor
       and rep["invoices"]["unmatched_imported_unlinked"] == 1  # 004 unlinked, not dropped
       and rep["expenses"]["created"] == 3
       and rep["won_links_populated"] == 1,
       "inv=%s exp=%s won=%s" % (rep["invoices"], rep["expenses"],
                                 rep["won_links_populated"]))

# ============================================================ T2 APPLY
rep2 = IMP.run_finance(INVOICES, EXPENSES, apply=True, customers=CUSTOMERS)
env.cr.commit()
_check("T2-apply-creates",
       INV.search_count([("zoho_invoice_number", "=like", "TESTZFINV-%")]) == 5
       and EXP.search_count([("zoho_expense_id", "=like", "TESTZFEXP-%")]) == 3,
       "inv=%d exp=%d" % (
           INV.search_count([("zoho_invoice_number", "=like", "TESTZFINV-%")]),
           EXP.search_count([("zoho_expense_id", "=like", "TESTZFEXP-%")])))

# ============================================================ T3 idempotent
rep3 = IMP.run_finance(INVOICES, EXPENSES, apply=True, customers=CUSTOMERS)
env.cr.commit()
_check("T3-idempotent",
       rep3["invoices"]["created"] == 0 and rep3["invoices"]["skipped_existing"] == 5
       and rep3["expenses"]["created"] == 0 and rep3["expenses"]["skipped_existing"] == 3
       and rep3["won_links_populated"] == 0,   # won-link re-run = zero (already set)
       "inv=%s exp=%s won=%s" % (rep3["invoices"], rep3["expenses"],
                                 rep3["won_links_populated"]))

# ============================================================ T4 status buckets
i1 = INV.search([("zoho_invoice_number", "=", "TESTZFINV-001")], limit=1)
i2 = INV.search([("zoho_invoice_number", "=", "TESTZFINV-002")], limit=1)
i3 = INV.search([("zoho_invoice_number", "=", "TESTZFINV-003")], limit=1)
i4 = INV.search([("zoho_invoice_number", "=", "TESTZFINV-004")], limit=1)
i5 = INV.search([("zoho_invoice_number", "=", "TESTZFINV-005")], limit=1)
_check("T4-status-buckets",
       i1.status_bucket == "paid" and i2.status_bucket == "unpaid"
       and i3.status_bucket == "void"
       and bool(i4) and bool(i5),   # 004 + 005 imported (NEVER skipped)
       "%s/%s/%s i4=%s i5=%s" % (i1.status_bucket, i2.status_bucket,
                                 i3.status_bucket, bool(i4), bool(i5)))

# ============================================================ T5 partner resolve (3 tiers)
_check("T5-direct-link-by-id",
       i1.partner_id == p1 and i2.partner_id == p1,
       "i1=%s i2=%s" % (i1.partner_id, i2.partner_id))
_check("T5b-fallback-links-collapsed-twin-to-survivor",
       bool(i5) and i5.partner_id == p_surv
       and rep2["invoices"]["fallback_linked"] == 1,
       "i5 partner=%s fb=%s" % (i5.partner_id if i5 else None,
                                rep2["invoices"]["fallback_linked"]))
_check("T5c-unresolved-imported-UNLINKED-not-dropped",
       bool(i4) and not i4.partner_id
       and rep2["invoices"]["unmatched_imported_unlinked"] == 1
       and "TESTZFINV-004" in rep2["unmatched_customers"]
       and P.search_count([("zoho_source_id", "=", "TESTZF-MISSING")]) == 0,
       "missing partner created or not reported")

# ============================================================ T6 expense shape
e1 = EXP.search([("zoho_expense_id", "=", "TESTZFEXP-001")], limit=1)
e2 = EXP.search([("zoho_expense_id", "=", "TESTZFEXP-002")], limit=1)
_check("T6-expense-billable-linked+no-vendor-field",
       e1.is_billable and e1.partner_id == p1 and e1.account_name == "Fuel"
       and len(e1.line_ids) == 1 and abs(e1.amount - 40.0) < 0.01
       and "vendor" not in EXP._fields and "vendor_id" not in EXP._fields,
       "e1=%s vendor_field=%s" % (
           e1.read()[0] if e1 else None,
           [f for f in EXP._fields if "vendor" in f]))
_check("T6b-billable-customer-not-found-kept-unlinked",
       bool(e2) and not e2.partner_id and e2.is_billable
       and rep2["expenses"]["billable_customer_not_found"] == 1,
       "e2 partner=%s report=%s" % (
           e2.partner_id if e2 else None,
           rep2["expenses"]["billable_customer_not_found"]))

# ============================================================ T7 WON-LINK populate
qa1.invalidate_recordset()
_check("T7-won-link-populated-bucket-not-regressed",
       qa1.zoho_invoice_number == "TESTZFINV-001"
       and qa1.status_bucket == "won",      # populate set ONLY the number
       "inv#=%s bucket=%s" % (qa1.zoho_invoice_number, qa1.status_bucket))

# ============================================================ T8 INERTNESS
_su2 = Seq.search([("code", "=", "neon.finance.quote.usd")], limit=1)
_check("T8-account-move-untouched",
       AM.search_count(_INV_DOMAIN) == AM_BEFORE,
       "cust invoices moved %d -> %d (finance import must create NO account.move)"
       % (AM_BEFORE, AM.search_count(_INV_DOMAIN)))
_check("T8b-live-quote+seq-untouched",
       Q.search_count([]) == Q_BEFORE
       and (_su2.number_next_actual if _su2 else -1) == SEQ_BEFORE,
       "quote %d->%d seq %s->%s" % (Q_BEFORE, Q.search_count([]), SEQ_BEFORE,
                                    _su2.number_next_actual if _su2 else -1))

# ============================================================ T9 currency char
_check("T9-currency-char-incl-ZWG",
       i2.currency_code == "ZWG" and i1.currency_code == "USD"
       and abs(i1.amount_tax - 15.5) < 0.01,
       "%s/%s tax=%s" % (i2.currency_code, i1.currency_code, i1.amount_tax))

# ============================================================ T10 archive-safe re-run
# MEDIUM fix: a superuser archives an imported reference invoice, then the import
# re-runs. The idempotency search (active_test=False) must still find it and SKIP,
# not fall through to create -> unique-constraint IntegrityError.
i1.invalidate_recordset()
i1.active = False
env.cr.commit()
try:
    rep4 = IMP.run_finance(INVOICES, EXPENSES, apply=True, customers=CUSTOMERS)
    env.cr.commit()
    _check("T10-archived-row-rerun-skips-not-errors",
           rep4["invoices"]["created"] == 0
           and rep4["invoices"]["skipped_existing"] == 5,
           "created=%d skipped=%d" % (rep4["invoices"]["created"],
                                      rep4["invoices"]["skipped_existing"]))
except Exception as _e:  # noqa: BLE001
    _check("T10-archived-row-rerun-skips-not-errors", False,
           "re-run after archive raised: %r" % _e)

# ---- teardown ----
_purge()
env.cr.commit()
print("=" * 64)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 64)
