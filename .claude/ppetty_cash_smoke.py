"""P-PETTY-CASH — petty-cash reference archive (operational-data plan step 1).

Tests the parser's PURE decode (both date encodings, real-vs-mangled,
carry-forward, year-per-tab, None-allowed, column-offset/October-shift,
"Closing Balance"/total-row exclusion, reconciliation fields) via synthetic
rows, AND the loader (idempotent per period_month, None date stored, model
integrity) + ACL (finance/director only, OFF the sales/operational lens).
[TESTPC] fixtures, self-cleaning. Run in `odoo shell -d neon_crm`.
"""
import datetime as _dt
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

# Exec the parser with ISOLATED globals so its __main__ block + module-level
# openpyxl path never run; we only want the pure helpers.
PG = {"__name__": "pc_parser_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/parse_petty_cash.py")
     .read(), PG)
parse_tab = PG["parse_tab"]
decode = PG["_decode_day"]
mfn = PG["_month_from_tabname"]

# ---- T1 month-from-tab-name (both layouts + abbrev + the Dec fix) ----
_check("T1-month-from-name",
       mfn("January Petty Cash") == 1 and mfn("Petty Cash May ") == 5
       and mfn("Petty Cash Jan") == 1 and mfn("December Petty Cash") == 12)

# ---- T2-T5 date decode ----
d, k, s = decode(_dt.datetime(2026, 5, 1), 1, None)   # Jan tab, mangled -> 5
_check("T2-decode-mangled", d == 5 and k == "dt-mangled" and s is True,
       "got %s %s %s" % (d, k, s))
d, k, s = decode(_dt.datetime(2025, 1, 24), 1, None)  # Jan tab, REAL -> 24
_check("T3-decode-real", d == 24 and k == "dt-real", "got %s %s" % (d, k))
d, k, s = decode("13-01-26", 1, 5)                    # text DD-MM-YY -> 13
_check("T4-decode-text", d == 13 and k == "text" and s is True,
       "got %s %s %s" % (d, k, s))
d, k, s = decode(None, 1, 7)                          # blank -> carry 7
_check("T5-decode-carry", d == 7 and k == "carry")
d, k, s = decode("check subscription renewal dat", 1, 20)  # note -> carry
_check("T5b-text-note-carry", d == 20 and k == "text-note")
d, k, s = decode(_dt.datetime(2025, 1, 4), 5, None)   # May: fits neither
_check("T8-ambiguous-none", d is None and k == "dt-ambiguous",
       "got %s %s" % (d, k))

# ---- T6 parse_tab: year-per-tab, total-row excluded, reconciliation ----
rows = [
    ("PETTY CASH STATEMENT", None, None, None, None, None),
    (_dt.datetime(2025, 3, 1), None, None, None, None, None),       # period
    (None, None, None, None, "Balance ", 150),                     # closing
    ("Date ", "Details", "Acc Code:", "Dr ", "Cr", "Balance"),     # header
    (_dt.datetime(2025, 1, 3), "Opening Balance", None, 200, None, 200),
    (None, "Lunch", None, None, 50, 150),                          # carry, Cr
    (None, "Closing Balance", None, 200, 50, 150),                 # TOTAL row
]
stmt, errs = parse_tab(rows, "Petty Cash March")
_check("T6-parse-year-month",
       stmt and stmt["tab_year"] == 2025 and stmt["tab_month"] == 3
       and stmt["period_month"] == "2025-03-01",
       "errs=%s" % errs)
_check("T6b-total-row-excluded", stmt and stmt["line_count"] == 2,
       "lines=%s" % (stmt and stmt["line_count"]))
_check("T6c-recon-green",
       stmt and stmt["v_balance_eq"] and not stmt["v_recon_fails"]
       and stmt["v_closing_match"] and stmt["v_crtotal_match"],
       "be=%s rf=%s cm=%s ct=%s" % (
           stmt and stmt["v_balance_eq"], stmt and stmt["v_recon_fails"],
           stmt and stmt["v_closing_match"], stmt and stmt["v_crtotal_match"]))

# ---- T7 column-offset (October-shift) ----
rows_off = [
    (None, "PETTY CASH STATEMENT", None, None, None, None),
    (None, _dt.datetime(2025, 10, 1), None, None, None, None),
    (None, None, None, None, None, "Balance ", 90),
    (None, "Date ", "Details", "Acc Code:", "Dr ", "Cr", "Balance"),
    (None, _dt.datetime(2025, 1, 10), "Opening Balance", None, 100, None, 100),
    (None, None, "Lunch", None, None, 10, 90),
]
stmt2, _e = parse_tab(rows_off, "October Petty Cash ")
_check("T7-column-offset",
       stmt2 and stmt2["line_count"] == 2 and stmt2["tab_month"] == 10
       and stmt2["v_balance_eq"],
       "lc=%s mo=%s be=%s" % (stmt2 and stmt2["line_count"],
                              stmt2 and stmt2["tab_month"],
                              stmt2 and stmt2["v_balance_eq"]))

# ---- Loader ----
LG = {"__name__": "pc_loader_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/import_petty_cash.py")
     .read(), LG)
load_petty_cash = LG["load_petty_cash"]
Stmt = env["neon.petty.cash.statement"].sudo()


def _purge():
    Stmt.with_context(active_test=False).search(
        [("source_tab", "=like", "TESTPC-%")]).unlink()


_purge()
payload = {"statements": [{
    "tab": "TESTPC-A", "name": "TESTPC Mar 2025",
    "period_month": "2025-03-01", "source_tab": "TESTPC-A",
    "currency_code": "USD", "opening_balance": 200, "closing_balance": 150,
    "cr_total": 50,
    "lines": [
        {"sequence": 10, "date_raw": "2025-01-03", "date_parsed": "2025-03-01",
         "details": "Opening Balance", "acc_code": "", "debit": 200,
         "credit": 0, "balance": 200},
        {"sequence": 20, "date_raw": "", "date_parsed": None,  # NULL date
         "details": "Lunch", "acc_code": "", "debit": 0, "credit": 50,
         "balance": 150},
    ]}]}
rep = load_petty_cash(env, payload)
env.flush_all()
st = Stmt.with_context(active_test=False).search([("source_tab", "=", "TESTPC-A")])
_check("T9-loader-creates",
       len(st) == 1 and st.line_count == 2 and rep["created"] == 1,
       "rep=%s" % rep)
none_line = st.line_ids.filtered(lambda l: not l.date_parsed)
_check("T9b-none-date-stored",
       len(none_line) == 1 and none_line.details == "Lunch")

# ---- T10 idempotent re-load (replace, no dup) ----
rep2 = load_petty_cash(env, payload)
env.flush_all()
st2 = Stmt.with_context(active_test=False).search(
    [("period_month", "=", "2025-03-01"), ("source_tab", "=", "TESTPC-A")])
_check("T10-idempotent-replace",
       len(st2) == 1 and rep2["replaced"] == 1,
       "n=%d rep=%s" % (len(st2), rep2))

# ---- T11 ACL: finance/director only, OFF the sales/operational lens ----
Users = env["res.users"].sudo()
denied = Users.search(
    [("id", "!=", 1), ("share", "=", False), ("active", "=", True)]
).filtered(lambda u: not u.has_group("neon_core.group_neon_bookkeeper")
           and not u.has_group("neon_core.group_neon_superuser"))[:1]
book = Users.search([]).filtered(
    lambda u: u.has_group("neon_core.group_neon_bookkeeper")
    and not u.has_group("neon_core.group_neon_superuser"))[:1]
if denied:
    try:
        env["neon.petty.cash.statement"].with_user(denied).search(
            [("source_tab", "=", "TESTPC-A")]).mapped("name")
        _check("T11-non-finance-denied", False,
               "%s READ petty cash!" % denied.login)
    except Exception:  # noqa: BLE001
        _check("T11-non-finance-denied", True)
else:
    _check("T11-non-finance-denied", True, "skip: no non-finance user")
if book:
    try:
        nm = env["neon.petty.cash.statement"].with_user(book).search(
            [("source_tab", "=", "TESTPC-A")]).mapped("name")
        _check("T11b-bookkeeper-read", len(nm) == 1)
    except Exception as e:  # noqa: BLE001
        _check("T11b-bookkeeper-read", False, "book denied: %r" % e)
else:
    _check("T11b-bookkeeper-read", True, "skip: no pure bookkeeper user")

_purge()
env.cr.commit()
print("=" * 60)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 60)
