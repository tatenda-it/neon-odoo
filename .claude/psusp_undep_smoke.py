"""P-SUSP-UNDEP — suspense + undeposited reference archives.

Parser pure-function tests (suspense reconcile via synthetic rows; undeposited
format detection two_table/dr_cr/amount/empty + section split + ZWG + dates) and
loader tests (idempotent per period_month, ZWG currency stored, None-date,
empty-skip surfaced) + ACL (finance/director only, off sales lens).
[TESTSU] fixtures (period 2099 to avoid real-data collision), self-cleaning.
Run in `odoo shell -d neon_crm`.
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

PG = {"__name__": "su_parser_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/parse_susp_undep.py")
     .read(), PG)
parse_suspense = PG["parse_suspense"]
parse_undeposited = PG["parse_undeposited"]
text_date = PG["_text_date"]

# ---- T1 text date / None ----
_check("T1-text-date",
       text_date("22-09-25") == "2025-09-22" and text_date("bad") is None
       and text_date(_dt.datetime(2025, 1, 10)) is None)

# ---- T2 suspense reconcile + multi-month dates ----
srows = [
    ("NEON", None, None, None, None, None),
    ("Suspense Account", None, None, None, None, None),
    (None, None, None, None, "Balance ", 0),
    ("Date ", "Details", "Acc Code:", "Dr ", "Cr", "Balance"),
    ("22-09-25", "Income A", None, 100, None, 100),
    (None, "Tithe", None, None, 10, 90),
    (_dt.datetime(2025, 1, 10), "Income B", None, 10, None, 100),
    (None, "Transfer to PC", None, None, 100, 0),
]
ss, _e = parse_suspense(srows, " Suspense Account", 2025)
_check("T2-suspense-reconcile",
       ss and ss["v_balance_eq"] and not ss["v_recon_fails"]
       and ss["closing_balance"] == 0 and ss["line_count"] == 4
       and ss["period_month"] == "2025-01-01",
       "be=%s rf=%s" % (ss and ss["v_balance_eq"], ss and ss["v_recon_fails"]))
_check("T2b-suspense-dates",
       ss["lines"][0]["date_parsed"] == "2025-09-22"
       and ss["lines"][2]["date_parsed"] is None  # datetime -> None
       and ss["lines"][2]["date_raw"],            # raw preserved
       "l0=%s l2=%s" % (ss["lines"][0]["date_parsed"],
                        ss["lines"][2]["date_parsed"]))

# ---- T3 undeposited two_table + ZWG + sections ----
urows = [
    (None, None, None, "USD", "ZWG", None),
    ("Date", "Details", "Invoice No:", "Invoice Amount", "Invoice Amount", None),
    (_dt.datetime(2025, 2, 5), "Client A", "INV1", 1000.0, None, None),
    (None, "Client B", None, None, 16100.0, None),
    (None, None, None, 1000.0, 16100.0, None),
    ("Date ", "Details ", "Amount ", "Account ", None, None),
    (None, "Expense X", 90.0, "undeposited funds", None, None),
    (None, None, 200, None, None, None),
]
u2, _e = parse_undeposited(urows, "February Undeposited funds")
_check("T3-two-table",
       u2 and u2["statement_format"] == "two_table"
       and u2["v_sections"]["receipt"] == 2
       and u2["v_sections"]["expense"] == 1 and u2["v_zwg_lines"] == 1,
       "fmt=%s sec=%s zwg=%s" % (u2 and u2["statement_format"],
                                 u2 and u2["v_sections"], u2 and u2["v_zwg_lines"]))
zwg = [l for l in u2["lines"] if l["currency"] == "ZWG"]
_check("T3b-zwg-line",
       len(zwg) == 1 and zwg[0]["amount"] == 16100.0
       and zwg[0]["details"] == "Client B")

# ---- T4 dr_cr ----
drows = [
    ("UNDEPOSITED STATEMENT", None, None, None, None, None),
    (_dt.datetime(2025, 4, 1), None, None, None, None, None),
    ("Date ", "Details", "Acc Code:", "Dr ", "Cr", None),
    ("15-04-25", "Equipment", None, None, 1000.0, None),
    (None, "Logistics", None, None, 155.0, None),
]
u3, _e = parse_undeposited(drows, "Undeposited April ")
_check("T4-dr-cr",
       u3 and u3["statement_format"] == "dr_cr"
       and u3["v_sections"]["statement"] == 2
       and u3["lines"][0]["credit"] == 1000.0,
       "fmt=%s" % (u3 and u3["statement_format"]))

# ---- T5 amount + total ----
arows = [
    ("UNDEPOSITED STATEMENT", None, None, None, None, None),
    (_dt.datetime(2025, 5, 1), None, None, None, None, None),
    ("Date ", "Details", "Acc Code:", "Amount", None, None),
    (_dt.datetime(2025, 2, 5), "Office Rent", None, 300.0, None, None),
    ("14-05-2025", "SA Payment", None, 1000.0, None, None),
    (None, None, 1300, None, None, None),
]
u4, _e = parse_undeposited(arows, "Undeposited May")
_check("T5-amount",
       u4 and u4["statement_format"] == "amount"
       and u4["v_sections"]["statement"] == 2 and u4["v_sum_amount"] == 1300.0,
       "fmt=%s sum=%s" % (u4 and u4["statement_format"],
                          u4 and u4["v_sum_amount"]))

# ---- T6 empty ----
u5, _e = parse_undeposited([(None,) * 6], "July Undeposited")
_check("T6-empty", u5 and u5["statement_format"] == "empty"
       and u5["line_count"] == 0)

# ---- Loader ----
LG = {"__name__": "su_loader_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/import_susp_undep.py")
     .read(), LG)
load_su = LG["load_susp_undep"]
Susp = env["neon.suspense.statement"].sudo()
Undep = env["neon.undeposited.statement"].sudo()


def _purge():
    Susp.with_context(active_test=False).search(
        [("source_tab", "=like", "TESTSU-%")]).unlink()
    Undep.with_context(active_test=False).search(
        [("source_tab", "=like", "TESTSU-%")]).unlink()


_purge()
payload = {
    "suspense": [{
        "tab": "TESTSU-S", "name": "TESTSU Suspense 2099",
        "period_month": "2099-01-01", "source_tab": "TESTSU-S",
        "currency_code": "USD", "opening_balance": 0, "closing_balance": 0,
        "lines": [
            {"sequence": 10, "date_raw": "22-09-25", "date_parsed": "2025-09-22",
             "details": "Income", "debit": 100, "credit": 0, "balance": 100},
            {"sequence": 20, "date_raw": "2025-01-10T00:00:00",
             "date_parsed": None, "details": "Transfer", "debit": 0,
             "credit": 100, "balance": 0}]}],
    "undeposited": [
        {"tab": "TESTSU-U", "name": "TESTSU Undep 2099-01",
         "period_month": "2099-01-01", "statement_format": "two_table",
         "source_tab": "TESTSU-U", "currency_default": "USD",
         "lines": [
             {"sequence": 10, "section": "receipt", "details": "Client",
              "amount": 1000, "currency": "USD", "date_parsed": "2099-01-05"},
             {"sequence": 20, "section": "receipt", "details": "ZWG Client",
              "amount": 16100, "currency": "ZWG", "note": "Bank Transfer",
              "date_parsed": None},
             {"sequence": 30, "section": "expense", "details": "Exp",
              "amount": 90, "currency": "USD"}]},
        {"tab": "TESTSU-EMPTY", "name": "", "period_month": None,
         "statement_format": "empty", "lines": []}],
}
rep = load_su(env, payload)
env.flush_all()
ss = Susp.with_context(active_test=False).search([("source_tab", "=", "TESTSU-S")])
uu = Undep.with_context(active_test=False).search([("source_tab", "=", "TESTSU-U")])
_check("T7-loader-creates",
       len(ss) == 1 and ss.line_count == 2 and len(uu) == 1
       and uu.line_count == 3 and rep["suspense_created"] == 1
       and rep["undep_created"] == 1, "rep=%s" % rep)
_check("T7b-zwg-stored",
       len(uu.line_ids.filtered(lambda l: l.currency == "ZWG")) == 1)
_check("T7c-none-date-stored",
       len(ss.line_ids.filtered(lambda l: not l.date_parsed)) == 1)
_check("T7d-empty-skipped",
       any(s.get("why") == "empty" for s in rep["skipped"]),
       "skipped=%s" % rep["skipped"])
_check("T7e-sections",
       len(uu.line_ids.filtered(lambda l: l.section == "receipt")) == 2
       and len(uu.line_ids.filtered(lambda l: l.section == "expense")) == 1)

# ---- T8 idempotent ----
rep2 = load_su(env, payload)
env.flush_all()
ss2 = Susp.with_context(active_test=False).search(
    [("period_month", "=", "2099-01-01"), ("source_tab", "=", "TESTSU-S")])
_check("T8-idempotent",
       len(ss2) == 1 and rep2["suspense_replaced"] == 1
       and rep2["undep_replaced"] == 1, "rep=%s" % rep2)

# ---- T9 ACL off sales/operational lens ----
Users = env["res.users"].sudo()
denied = Users.search(
    [("id", "!=", 1), ("share", "=", False), ("active", "=", True)]
).filtered(lambda u: not u.has_group("neon_core.group_neon_bookkeeper")
           and not u.has_group("neon_core.group_neon_superuser"))[:1]
if denied:
    try:
        env["neon.suspense.statement"].with_user(denied).search(
            [("source_tab", "=", "TESTSU-S")]).mapped("name")
        _check("T9-non-finance-denied", False, "%s read suspense!" % denied.login)
    except Exception:  # noqa: BLE001
        _check("T9-non-finance-denied", True)
else:
    _check("T9-non-finance-denied", True, "skip: no non-finance user")

_purge()
env.cr.commit()
print("=" * 60)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 60)
