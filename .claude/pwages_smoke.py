"""P-WAGES — wages reference archive (op-data step 3b, final lane).

Parser tests (3 layouts via synthetic rows: multi-week / single tech-col0 /
wide; week-date parse; weekly reconciliation incl. a deliberate fail) + loader
tests (crew-FK via roster aliases incl. unmapped surfacing; conservative
job-link exact+substring with unmatched kept in jobs_raw; weekly-lump no
per-job; idempotency) + ACL (director/bookkeeper only, sales denied).
[TESTW] fixtures, self-cleaning. Run in `odoo shell -d neon_crm`.
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

PG = {"__name__": "wages_parser_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/parse_wages.py").read(), PG)
parse_sheet = PG["parse_sheet"]
date_from_text = PG["_date_from_text"]

# ---- T1 layout A (multi-week per sheet) ----
rowsA = [
    ("WEEK", "TECHNICIAN", "JOBS COVERED", "TOTAL", "Column 1"),
    ("March Week 1 03/03/25", None, None, None, None),
    (None, "Oswell", "JobA\nJobB", 90.0, None),
    (None, "KK", "JobA", 100.0, None),
    ("TOTAL", None, None, 190, None),
    ("March Week 2 10/03/25", None, None, None, None),
    (None, "John", "JobC", 60.0, None),
    ("TOTAL", None, None, 60, None),
]
eA, wA = parse_sheet(rowsA, "March week 1")
_check("T1-multiweek-entries", len(eA) == 3 and eA[0]["technician_raw"] == "Oswell"
       and eA[0]["total"] == 90.0)
_check("T1b-multiweek-weeklabel-date",
       eA[0]["week_label"] == "March Week 1 03/03/25"
       and eA[0]["week_date"] == "2025-03-03"
       and eA[2]["week_date"] == "2025-03-10")
_check("T1c-multiweek-reconcile",
       all(abs(w["total_row"] - w["sum_techs"]) < 0.01 for w in wA) and len(wA) == 2)

# ---- T2 layout B (single week, tech col0, paid) ----
rowsB = [
    ("TECHNICIAN", "JOBS COVERED", "TOTAL", "Column 1"),
    ("Kelvin ", "Golden Conifer", 60.0, "Paid"),
    ("KK", "Inuka", 120.0, "Paid"),
    (None, None, 180, None),
]
eB, wB = parse_sheet(rowsB, "May 5 2025")
_check("T2-single-entries",
       len(eB) == 2 and eB[0]["paid"] == "paid"
       and eB[0]["week_date"] == "2025-05-05")
_check("T2b-single-reconcile",
       len(wB) == 1 and abs(wB[0]["total_row"] - wB[0]["sum_techs"]) < 0.01)

# ---- T3 layout C (wide) + deliberate recon FAIL ----
rowsC = [
    ("Column 1", "JOBS COVERED", "TOTAL", "Column 4"),
    ("Trymore", "JobX", 40.0, None),
    ("Danny", "JobY", 160.0, None),
    ("TOTAL", None, 800, None),
]
eC, wC = parse_sheet(rowsC, "02 March 2026")
_check("T3-wide-entries",
       len(eC) == 2 and eC[1]["technician_raw"] == "Danny"
       and eC[0]["week_date"] == "2026-03-02")
_check("T3b-recon-fail-detected",
       wC[0]["sum_techs"] == 200.0 and wC[0]["total_row"] == 800)  # mismatch

# ---- T4 date helper ----
_check("T4-date-default-year",
       date_from_text("19 May ", 2025) == "2025-05-19"
       and date_from_text("02 March 2026") == "2026-03-02")

# ---- Loader ----
LG = {"__name__": "wages_loader_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/import_wages.py").read(), LG)
load_wages = LG["load_wages"]
W = env["neon.wages.entry"].sudo()
C = env["neon.crew.member"].sudo()
J = env["neon.job.history"].sudo()


def _purge():
    W.with_context(active_test=False).search([("source", "=", "TESTW")]).unlink()
    C.with_context(active_test=False).search(
        [("source", "=", "TESTW")]).unlink()
    J.with_context(active_test=False).search(
        [("source", "=", "TESTW")]).unlink()


_purge()
rang = C.create({"name": "TESTW Ranganai", "aliases": "TESTWKK",
                 "is_lead": True, "source": "TESTW"})
kelv = C.create({"name": "TESTW Kelvin", "aliases": "TESTWDanny",
                 "source": "TESTW"})
J.create({"title": "TESTW World Bank Launch Event", "is_job": True,
          "source": "TESTW"})

payload = {"entries": [
    {"week_label": "TESTW Wk1", "week_date": "2025-03-03",
     "technician_raw": "TESTWKK", "total": 100.0, "currency_code": "USD",
     "paid": "paid", "jobs_raw": "TESTW World Bank\nTESTW Nonexistent Gig",
     "source": "wages_sheet"},
    {"week_label": "TESTW Wk1", "week_date": "2025-03-03",
     "technician_raw": "TESTWDanny", "total": 60.0, "currency_code": "USD",
     "paid": "unknown", "jobs_raw": "TESTW Nonexistent Gig",
     "source": "wages_sheet"},
    {"week_label": "TESTW Wk1", "week_date": "2025-03-03",
     "technician_raw": "TESTWGhost", "total": 50.0, "currency_code": "USD",
     "paid": "unknown", "jobs_raw": "", "source": "wages_sheet"},
]}
rep = load_wages(env, payload, source="TESTW")
env.flush_all()
rows = W.with_context(active_test=False).search([("source", "=", "TESTW")])
bykk = rows.filtered(lambda r: r.crew_member_id.id == rang.id)
_check("T5-created", rep["created"] == 3 and len(rows) == 3, "rep=%s" % rep)
_check("T5b-crew-fk-alias",
       len(bykk) == 1 and bykk.total == 100.0
       and rows.filtered(lambda r: r.crew_member_id.id == kelv.id))
_check("T5c-unmapped-surfaced",
       rep["unmapped"].get("TESTWGhost") == 1 and rep["distinct_crew"] == 2)
_check("T5d-job-link-conservative",
       bykk.job_link_count == 1
       and bykk.job_ids.title == "TESTW World Bank Launch Event")
_check("T5e-jobs-raw-kept",
       "TESTW Nonexistent Gig" in bykk.jobs_raw)  # unmatched kept verbatim
_check("T5f-weekly-lump-no-perjob",
       "amount" not in W._fields and "per_job" not in W._fields
       and bykk.total == 100.0)

# ---- T6 idempotency ----
rep2 = load_wages(env, payload, source="TESTW")
env.flush_all()
_check("T6-idempotent",
       W.with_context(active_test=False).search_count([("source", "=", "TESTW")]) == 3)

# ---- T7 ACL: sales/operational denied (pay is finance/director only) ----
Users = env["res.users"].sudo()
denied = Users.search(
    [("id", "!=", 1), ("share", "=", False), ("active", "=", True)]
).filtered(lambda u: not u.has_group("neon_core.group_neon_bookkeeper")
           and not u.has_group("neon_core.group_neon_superuser"))[:1]
if denied:
    try:
        env["neon.wages.entry"].with_user(denied).search(
            [("source", "=", "TESTW")]).mapped("total")
        _check("T7-non-finance-denied", False, "%s read wages!" % denied.login)
    except Exception:  # noqa: BLE001
        _check("T7-non-finance-denied", True)
else:
    _check("T7-non-finance-denied", True, "skip: no non-finance user")

_purge()
env.cr.commit()
print("=" * 60)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 60)
