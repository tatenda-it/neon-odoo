"""BUILD 3 import smoke -- self-contained (inline CABS-format CSV samples).
Runs in odoo shell, ROLLS BACK. Exercises the parser end-to-end: currency
routing, BOTH date formats (DD/MM/YYYY + DD MMM YY), signed amounts, comma-
thousands, negatives, opening/closing balance rows. No external fixtures.
"""
import base64

results = []


def chk(n, c, d=""):
    results.append((n, bool(c)))
    print(("  ok  " if c else "FAIL  ") + "%-46s %s" % (n, d))


USD_CSV = (
    "Account Statement,,,,,,\n"
    "Account Number:,1153245035,Old Account Number:,,,,\n"
    "Account Name:,NEON EVENTS ELEMENTS PVT LTD,,,,,\n"
    "Currency,USD,,,,,\n"
    "Post date,Reference,Narrative,Value Date,Debit,Credit,Closing Balance\n"
    ",,,,,,\n"
    ",Balance at Period Start,,,,,0\n"
    "06/02/2025,FT250371V7YY,RTGS TRANSFER,06/02/2025,0.00,2087.25,2087.25\n"
    "06/02/2025,CHG25037LNTH,,06/02/2025,20.00,0.00,2067.25\n"
    ",Balance at Period End,,,,,2067.25\n"
)
ZWG_CSV = (
    "Account Statement,,,,,,\n"
    "Account Number:,1153244969,,,,,\n"
    "Currency,ZWG,,,,,\n"
    "Post date,Reference,Narrative,Value Date,Debit,Credit,Closing Balance\n"
    ",,,,,,\n"
    ",Balance at Period Start,,,,,0\n"
    "19 FEB 25,CHG25050RGJX,Service Fees,19 FEB 25,131.95,,-131.95\n"
    '19 FEB 25,FT250502VD3K,RTGS Transfer,19 FEB 25,,"16,100.00","15,968.05"\n'
    ",Balance at Period End,,,,,15968.05\n"
)


def _imp(csv_text, fname):
    w = env["neon.bank.statement.import.wizard"].create(
        {"statement_file": base64.b64encode(csv_text.encode()), "filename": fname})
    st = env["account.bank.statement"].browse(w.action_import()["res_id"])
    return st, st.line_ids.sorted("date")


usd, ul = _imp(USD_CSV, "usd.csv")
chk("USD routed to CABS (USD) journal", "USD" in usd.journal_id.name)
chk("USD opening 0 / closing 2067.25", usd.balance_start == 0.0 and abs(usd.balance_end_real - 2067.25) < 0.01,
    "start=%s end=%s" % (usd.balance_start, usd.balance_end_real))
chk("USD 06/02/2025 -> 2025-02-06 (DD/MM, not 2 Jun)", all(str(l.date) == "2025-02-06" for l in ul))
chk("USD credit inflow +2087.25", any(abs(l.amount - 2087.25) < 0.01 for l in ul))
chk("USD debit outflow -20.00", any(abs(l.amount + 20.0) < 0.01 for l in ul))
chk("USD 2 transaction lines (balance rows excluded)", len(ul) == 2, "lines=%d" % len(ul))

zwg, zl = _imp(ZWG_CSV, "zwg.csv")
chk("ZWG routed to CABS (ZWG) journal", zwg.journal_id.currency_id.name == "ZWG")
chk("ZWG 19 FEB 25 -> 2025-02-19 (DD MMM YY)", all(str(l.date) == "2025-02-19" for l in zl))
chk("ZWG comma-thousands 16,100.00 parsed", any(abs(l.amount - 16100.0) < 0.01 for l in zl))
chk("ZWG negative outflow -131.95", any(abs(l.amount + 131.95) < 0.01 for l in zl))

env.cr.rollback()
passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
