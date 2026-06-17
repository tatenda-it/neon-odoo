"""P-ROLLUP — salesperson_display computed field + rollup grouping on the inert
neon.finance.quote.archive. Asserts: display = Odoo name (current rep) / Zoho
label (former rep) / 'Unassigned'; the stored field lets a pivot SPLIT former
reps instead of collapsing them into one empty group; currency filter; recompute
on id-set. Run in `odoo shell -d neon_crm`. Self-cleaning [TEST-RU] fixtures.
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


env = env(context=dict(env.context, tracking_disable=True))
QA = env["neon.finance.quote.archive"].sudo()
Users = env["res.users"].sudo()


def _purge():
    QA.with_context(active_test=False).search(
        [("zoho_estimate_number", "=like", "TESTRU-%")]).unlink()


def _gcount(g):
    return g.get("salesperson_display_count") or g.get("__count") or 0


_purge()

rep_user = (Users.search([("login", "=", "p2m75_sales")], limit=1)
            or Users.search([("share", "=", False), ("active", "=", True)], limit=1))

q_cur = QA.create({"zoho_estimate_number": "TESTRU-001", "status_bucket": "won",
                   "currency_code": "USD", "amount_total": 100.0,
                   "salesperson_id": rep_user.id})
q_f1 = QA.create({"zoho_estimate_number": "TESTRU-002", "status_bucket": "historical",
                  "currency_code": "USD", "amount_total": 200.0,
                  "salesperson_name": "Hamu Mutasa"})
q_f2 = QA.create({"zoho_estimate_number": "TESTRU-003", "status_bucket": "lost",
                  "currency_code": "USD", "amount_total": 50.0,
                  "salesperson_name": "Hamu Mutasa"})
q_none = QA.create({"zoho_estimate_number": "TESTRU-004", "status_bucket": "open",
                    "currency_code": "ZWG", "amount_total": 30.0})
for r in (q_cur, q_f1, q_f2, q_none):
    r.invalidate_recordset()

# ---- T1-T3 computed value ----
_check("T1-current-rep-display-is-user-name",
       q_cur.salesperson_display == rep_user.name,
       "got %r (user %r)" % (q_cur.salesperson_display, rep_user.name))
_check("T2-former-rep-display-is-zoho-label",
       q_f1.salesperson_display == "Hamu Mutasa",
       "got %r" % q_f1.salesperson_display)
_check("T3-neither-display-Unassigned",
       q_none.salesperson_display == "Unassigned",
       "got %r" % q_none.salesperson_display)

# ---- T4 stored + grouping SPLITS former reps (not one empty 'None' row) ----
fld = QA._fields["salesperson_display"]
_check("T4-field-stored-indexed", bool(fld.store) and bool(fld.column_type),
       "store=%s col=%s" % (fld.store, fld.column_type))
groups = QA.read_group([("zoho_estimate_number", "=like", "TESTRU-%")],
                       ["amount_total:sum"], ["salesperson_display"])
gmap = {g["salesperson_display"]: g for g in groups}
_check("T4b-grouping-splits-reps-no-None-dump",
       "Hamu Mutasa" in gmap and rep_user.name in gmap and "Unassigned" in gmap
       and False not in gmap and None not in gmap
       and _gcount(gmap["Hamu Mutasa"]) == 2,   # both former-rep quotes grouped
       "groups=%s hamu_count=%s" % (
           sorted(str(k) for k in gmap),
           _gcount(gmap["Hamu Mutasa"]) if "Hamu Mutasa" in gmap else None))

# ---- T5 currency filter (never sum across currencies) ----
usd = QA.search_count([("zoho_estimate_number", "=like", "TESTRU-%"),
                       ("currency_code", "=", "USD")])
allc = QA.search_count([("zoho_estimate_number", "=like", "TESTRU-%")])
_check("T5-currency-filter-isolates-USD", usd == 3 and allc == 4,
       "usd=%d all=%d" % (usd, allc))

# ---- T6 recompute on id-set (id takes precedence over label) ----
q_f1.salesperson_id = rep_user.id
q_f1.invalidate_recordset()
_check("T6-recompute-id-precedence",
       q_f1.salesperson_display == rep_user.name,
       "got %r" % q_f1.salesperson_display)

_purge()
env.cr.commit()
print("=" * 60)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 60)
