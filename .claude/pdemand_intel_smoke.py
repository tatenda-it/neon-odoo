"""P-DEMAND-INTEL — L2.2 demand & seasonality (computed by month, read-only).

Compute correctness vs the job+quote spine (per year/month jobs/quotes/won),
USD-only money guard (ZWG counted not summed), recurring named-event detection
(title normalisation merges 'X 2024'/'X 2025', single-year NOT recurring,
too-short title skipped), descriptive-only recurrence (no forecast field), ACL
(read-only model, all-commercial read), dashboard RPC (access guard + payload),
and the copilot tool read-only contract. [TESTD] fixtures, self-cleaning.
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

CG = {"__name__": "demand_compute_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/compute_demand_intel.py")
     .read(), CG)
compute = CG["compute_demand_rows"]
norm = CG["_norm_title"]

J = env["neon.job.history"].sudo()
Q = env["neon.finance.quote.archive"].sudo()
DI = env["neon.demand.intel"].sudo()
DR = env["neon.demand.recurring"].sudo()
Users = env["res.users"].sudo()


def _purge():
    J.with_context(active_test=False).search([("source", "=", "TESTD")]).unlink()
    Q.search([("zoho_estimate_number", "=like", "TESTD%")]).unlink()
    Users.with_context(active_test=False).search(
        [("login", "in", ("td_sales", "td_book", "td_jobs"))]).unlink()


_purge()

# ---- title normalisation (unit) ----
_check("T1-norm-strips-year",
       norm("TESTD Annual Gala 2024") == norm("TESTD Annual Gala 2025")
       == "testd annual gala")
_check("T1b-norm-distinct-stay-distinct",
       norm("Juliasdale Wedding") != norm("James Bond Event"))


def mkj(title, dstart):
    J.create({"title": title, "date_start": dstart, "is_job": True,
              "source": "TESTD"})


def mkq(num, total, bucket, ccy, qdate):
    Q.create({"zoho_estimate_number": num, "amount_total": total,
              "status_bucket": bucket, "currency_code": ccy,
              "quotation_date": qdate})


mkj("TESTD Annual Gala 2024", "2024-05-10")
mkj("TESTD Annual Gala 2025", "2025-05-12")   # recurring with the 2024 one
mkj("TESTD One Off Bash", "2025-06-01")         # single year -> not recurring
mkj("Q.", "2024-07-01")                          # normalises to 'q' -> skipped
mkq("TESTD-Q1", 1000.0, "won", "USD", "2025-05-03")
mkq("TESTD-Q2", 500.0, "lost", "USD", "2025-05-04")
mkq("TESTD-Q3", 9999.0, "won", "ZWG", "2025-05-05")   # ZWG: counted, not summed
mkq("TESTD-Q4", 200.0, "historical", "USD", "2024-05-20")
env.flush_all()

drows, rrows, stats = compute(env)
cell = {(r["year"], r["month"]): r for r in drows}
c245 = cell.get((2024, 5))
c255 = cell.get((2025, 5))
c256 = cell.get((2025, 6))
c247 = cell.get((2024, 7))

_check("T2-cell-2024-05",
       c245 and c245["jobs_count"] == 1 and c245["quotes_count"] == 1
       and abs(c245["quotes_value_usd"] - 200) < 0.1)
_check("T3-cell-2025-05-counts",
       c255 and c255["jobs_count"] == 1 and c255["quotes_count"] == 3
       and c255["won_count"] == 2)
_check("T3b-usd-guard",   # ZWG in count + won_count, NOT in USD value sums
       abs(c255["quotes_value_usd"] - 1500) < 0.1
       and abs(c255["won_value_usd"] - 1000) < 0.1
       and abs(c255["nonusd_quote_value"] - 9999) < 0.1)
_check("T4-job-only-month", c256 and c256["jobs_count"] == 1
       and c256["quotes_count"] == 0)
_check("T4b-short-title-still-counts",   # 'Q.' job counted in the month grain
       c247 and c247["jobs_count"] == 1 and stats["title_skipped"] >= 1)

rec = {r["normalised_title"]: r for r in rrows}
_check("T5-recurring-detected",
       "testd annual gala" in rec
       and rec["testd annual gala"]["distinct_years"] == 2
       and rec["testd annual gala"]["total_occurrences"] == 2
       and rec["testd annual gala"]["year_list"] == "2024, 2025")
_check("T5b-single-year-not-recurring",
       "testd one off bash" not in rec)
_check("T6-descriptive-not-forecast",   # no prediction fields on the model
       not any(f in DR._fields for f in ("expected_next", "forecast",
                                         "predicted_year", "next_expected")))

# ---- recompute idempotency (full rebuild via model) ----
DI.cron_recompute()
env.flush_all()
n1, r1 = DI.search_count([]), DR.search_count([])
DI.cron_recompute()
env.flush_all()
n2, r2 = DI.search_count([]), DR.search_count([])
_check("T7-recompute-idempotent", n1 == n2 and r1 == r2 and n1 > 0,
       "n1=%s n2=%s r1=%s r2=%s" % (n1, n2, r1, r2))
gala = DR.search([("normalised_title", "=", "testd annual gala")], limit=1)
_check("T7b-recompute-persists",
       gala and gala.distinct_years == 2 and bool(gala.last_computed))

# ---- ACL: read-only model, all-commercial read ----
srep = env.ref("neon_core.group_neon_sales_rep")
bg = env.ref("neon_core.group_neon_bookkeeper")
jobs_user_grp = env.ref("neon_jobs.group_neon_jobs_user")
sales = Users.create({"name": "TESTD Sales", "login": "td_sales",
                      "password": "test123", "groups_id": [(4, srep.id)]})
book = Users.create({"name": "TESTD Book", "login": "td_book",
                     "password": "test123", "groups_id": [(4, bg.id)]})
jobsu = Users.create({"name": "TESTD Jobs", "login": "td_jobs",
                      "password": "test123",
                      "groups_id": [(4, jobs_user_grp.id)]})
try:
    env["neon.demand.intel"].with_user(sales).create({"year": 2099, "month": 1})
    _check("T8-model-read-only", False, "sales created a demand row!")
except Exception:  # noqa: BLE001
    _check("T8-model-read-only", True)
sread = env["neon.demand.intel"].with_user(sales).search_count([])
_check("T8b-sales-can-read", sread > 0)

# ---- dashboard RPC: access guard + payload ----
dd = env["neon.demand.intel"].with_user(sales).get_dashboard_data()
_check("T9-dashboard-payload",
       isinstance(dd.get("seasonality"), list) and len(dd["seasonality"]) == 12
       and isinstance(dd.get("series"), list)
       and isinstance(dd.get("yoy"), list)
       and isinstance(dd.get("recurring"), list)
       and dd.get("variant") == "sales")
try:
    env["neon.demand.intel"].with_user(jobsu).get_dashboard_data()
    _check("T9b-dashboard-denied-non-core", False, "jobs-user got data")
except Exception:  # noqa: BLE001
    _check("T9b-dashboard-denied-non-core", True)

# ---- copilot tool: read-only contract ----
from odoo.addons.neon_ai_core.models.ai import tool_registry as TR  # noqa: E402
td = TR.get_tool("get_demand_intel")
_check("T10-tool-is-read", td and td.category == "read")
_check("T10b-no-executor", TR.get_executor("get_demand_intel") is None)
before = DI.search_count([])
res = TR.dispatch("get_demand_intel", env, book, {})
after = DI.search_count([])
_check("T11-dispatch-read-no-mutation",
       before == after and res.get("ok")
       and isinstance(res.get("per_year"), list))
res_rec = TR.dispatch("get_demand_intel", env, book, {"recurring": True})
_check("T11b-tool-recurring",
       res_rec.get("ok") and res_rec.get("mode") == "recurring"
       and any("annual gala" in (e.get("event") or "").lower()
               for e in res_rec.get("events", [])))

_purge()
DI.cron_recompute()   # rebuild clean (fixtures gone)
env.cr.commit()
print("=" * 60)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 60)
