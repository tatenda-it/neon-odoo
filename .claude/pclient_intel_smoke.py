"""P-CLIENT-INTEL — L2.1 client/account intelligence (computed, read-only).

Compute correctness vs the archives (quotes/won/win_rate/invoiced/jobs/
active_years/recency), USD-only money guard (ZWG counted but not summed),
unmatched (no-partner) bucketing, the rule-based segment ladder, the payment
heuristic, ACL (read-only model + sensitive-field hiding from sales, visible to
bookkeeper), recompute idempotency, AND the chat-tool read-only contract
(category=read, NO write executor, dispatch never mutates, sensitive tool
denied to sales). [TESTCI] fixtures, self-cleaning. Run in odoo shell.
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


from datetime import date, timedelta  # noqa: E402

env = env(context=dict(env.context, tracking_disable=True))

CG = {"__name__": "client_intel_compute_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/compute_client_intel.py")
     .read(), CG)
compute_rows = CG["compute_client_intel_rows"]

P = env["res.partner"].sudo()
Q = env["neon.finance.quote.archive"].sudo()
I = env["neon.finance.invoice.archive"].sudo()
J = env["neon.job.history"].sudo()
C = env["neon.collections.item"].sudo()
CI = env["neon.client.intel"].sudo()
Users = env["res.users"].sudo()

TODAY = date.today()


def _purge():
    Q.search([("zoho_estimate_number", "=like", "TESTCI%")]).unlink()
    I.search([("zoho_invoice_number", "=like", "TESTCI%")]).unlink()
    J.with_context(active_test=False).search(
        [("title", "=like", "TESTCI%")]).unlink()
    C.with_context(active_test=False).search(
        [("source", "=", "TESTCI")]).unlink()
    CI.search([("client_name", "=like", "TESTCI%")]).unlink()
    Users.with_context(active_test=False).search(
        [("login", "in", ("ci_salesrep", "ci_book", "ci_jobsuser"))]).unlink()
    P.with_context(active_test=False).search(
        [("name", "=like", "TESTCI %")]).unlink()


_purge()


def mkq(num, partner, total, bucket, ccy="USD", qdate=None):
    Q.create({"zoho_estimate_number": num, "partner_id": partner and partner.id,
              "amount_total": total, "status_bucket": bucket,
              "currency_code": ccy,
              "quotation_date": qdate or "2026-05-01"})


def mki(num, partner, total, ccy="USD"):
    I.create({"zoho_invoice_number": num, "partner_id": partner and partner.id,
              "amount_total": total, "status_bucket": "paid",
              "currency_code": ccy, "invoice_date": "2026-05-10"})


def mkj(title, partner, dstart, etype="Corporate"):
    J.create({"title": title, "partner_id": partner and partner.id,
              "date_start": dstart, "is_job": True, "event_type": etype,
              "source": "famcal_scrape"})


# Partner A — high_value_repeat (3 active years, won 12k, recent)
A = P.create({"name": "TESTCI Alpha Corp", "is_company": True})
for k in range(4):
    mkq("TESTCI-A-W%d" % k, A, 3000.0, "won")
mkq("TESTCI-A-L", A, 1000.0, "lost")
mki("TESTCI-A-I1", A, 6000.0)
mki("TESTCI-A-I2", A, 6000.0)
mkj("TESTCI Alpha Job24", A, "2024-03-01", "Corporate")
mkj("TESTCI Alpha Job25", A, "2025-03-01", "Corporate")
mkj("TESTCI Alpha Job26", A, "2026-06-01", "Launch")

# Partner B — quote_heavy_low_convert (6 quotes, 1 won, recent) + at_risk coll
B = P.create({"name": "TESTCI Beta Ltd", "is_company": True})
mkq("TESTCI-B-W", B, 500.0, "won")
for k in range(5):
    mkq("TESTCI-B-L%d" % k, B, 100.0, "lost")
mkj("TESTCI Beta Job", B, (TODAY - timedelta(days=20)).isoformat(), "Wedding")
C.create({"client_name": "TESTCI Beta Ltd", "partner_id": B.id,
          "amount_usd": 300.0, "status": "unresponsive", "source": "TESTCI"})

# Partner C — dormant (last activity ~3 years ago)
Cc = P.create({"name": "TESTCI Gamma", "is_company": True})
mkq("TESTCI-C-W", Cc, 800.0, "won", qdate="2021-02-01")
mkj("TESTCI Gamma Job", Cc, "2021-01-15", "Gala")

# Partner D — new (first activity within a year, 1 active year)
D = P.create({"name": "TESTCI Delta", "is_company": True})
mkq("TESTCI-D-W", D, 400.0, "won",
    qdate=(TODAY - timedelta(days=30)).isoformat())
mkj("TESTCI Delta Job", D, (TODAY - timedelta(days=25)).isoformat(), "Launch")

# Partner E — USD-guard (1 USD + 1 ZWG won; ZWG counted not summed)
E = P.create({"name": "TESTCI Epsilon", "is_company": True})
mkq("TESTCI-E-USD", E, 1000.0, "won", "USD")
mkq("TESTCI-E-ZWG", E, 50000.0, "won", "ZWG")

# Unmatched — no partner link
mkq("TESTCI-U-1", None, 700.0, "open")
mkq("TESTCI-U-2", None, 300.0, "lost")
mki("TESTCI-U-I", None, 250.0)
mkj("TESTCI Unmatched Job", None, "2026-04-01", "Other")
env.flush_all()

rows, stats = compute_rows(env)
by = {r["client_name"]: r for r in rows}
ra, rb, rc, rd, re_ = (by.get("TESTCI Alpha Corp"), by.get("TESTCI Beta Ltd"),
                       by.get("TESTCI Gamma"), by.get("TESTCI Delta"),
                       by.get("TESTCI Epsilon"))

_check("T1-alpha-quotes",
       ra and ra["quotes_count"] == 5 and abs(ra["quotes_value"] - 13000) < 0.1,
       "ra=%s" % ra)
_check("T1b-alpha-won",
       ra["won_count"] == 4 and abs(ra["won_value"] - 12000) < 0.1
       and abs(ra["win_rate"] - 0.8) < 0.001)
_check("T1c-alpha-invoiced",
       ra["invoices_count"] == 2 and abs(ra["invoiced_value"] - 12000) < 0.1)
_check("T1d-alpha-jobs-years",
       ra["jobs_count"] == 3 and ra["active_years"] == 3
       and "Launch" in ra["event_types"] and "Corporate" in ra["event_types"])
_check("T1e-alpha-segment-recency",
       ra["segment"] == "high_value_repeat" and ra["recency_days"] < 400)
_check("T1f-alpha-payment-settled",  # invoiced, no collections
       ra["payment_behaviour"] == "settled")

_check("T2-beta-quote-heavy",
       rb and rb["quotes_count"] == 6 and rb["won_count"] == 1
       and rb["segment"] == "quote_heavy_low_convert")
_check("T2b-beta-at-risk",  # collections unresponsive -> heuristic
       abs(rb["outstanding_usd"] - 300) < 0.1
       and rb["payment_behaviour"] == "at_risk"
       and rb["outstanding_status"] == "unresponsive")

_check("T3-gamma-dormant",
       rc and rc["segment"] == "dormant" and rc["recency_days"] > 540)
_check("T4-delta-new", rd and rd["segment"] == "new"
       and rd["active_years"] == 1)

_check("T5-usd-guard",   # ZWG counted in counts, excluded from value sums
       re_ and re_["quotes_count"] == 2 and re_["won_count"] == 2
       and abs(re_["quotes_value"] - 1000) < 0.1
       and abs(re_["won_value"] - 1000) < 0.1)

unmatched = by.get("(unmatched — no partner link)")
_check("T6-unmatched-bucket",
       unmatched is not None and unmatched["partner_id"] is False
       and stats["unmatched_quotes"] >= 2 and stats["unmatched_jobs"] >= 1)

# ---- recompute idempotency (full rebuild via the model method) ----
CI.cron_recompute()
env.flush_all()
n1 = CI.search_count([])
CI.cron_recompute()
env.flush_all()
n2 = CI.search_count([])
_check("T7-recompute-idempotent", n1 == n2 and n1 > 0, "n1=%s n2=%s" % (n1, n2))
alpha_ci = CI.search([("client_name", "=", "TESTCI Alpha Corp")], limit=1)
_check("T7b-recompute-persists",
       alpha_ci and abs(alpha_ci.won_value - 12000) < 0.1
       and alpha_ci.segment == "high_value_repeat"
       and bool(alpha_ci.last_computed))

# ---- ACL: model read-only + sensitive field hiding ----
srep = env.ref("neon_core.group_neon_sales_rep")
bg = env.ref("neon_core.group_neon_bookkeeper")
sales = Users.create({"name": "TESTCI Sales", "login": "ci_salesrep",
                      "password": "test123", "groups_id": [(4, srep.id)]})
book = Users.create({"name": "TESTCI Book", "login": "ci_book",
                     "password": "test123", "groups_id": [(4, bg.id)]})

# read-only: a sales user cannot create
try:
    env["neon.client.intel"].with_user(sales).create(
        {"client_name": "TESTCI hack"})
    _check("T8-model-read-only", False, "sales created an intel row!")
except Exception:  # noqa: BLE001
    _check("T8-model-read-only", True)

# sensitive field hidden from sales, visible to bookkeeper
arow = CI.search([("client_name", "=", "TESTCI Beta Ltd")], limit=1)
try:
    sval = arow.with_user(sales).read(["client_name", "outstanding_usd"])[0]
    sales_hidden = "outstanding_usd" not in sval
except Exception:  # noqa: BLE001
    sales_hidden = True
_check("T9-sensitive-hidden-from-sales", sales_hidden)
bval = arow.with_user(book).read(["outstanding_usd"])[0]
_check("T9b-sensitive-visible-to-book", "outstanding_usd" in bval
       and bval["outstanding_usd"] is not False)
# commercial field readable by sales
cval = arow.with_user(sales).read(["won_value"])[0]
_check("T9c-commercial-visible-to-sales", "won_value" in cval)

# ---- chat tools: READ-ONLY contract ----
from odoo.addons.neon_ai_core.models.ai import tool_registry as TR  # noqa: E402

ti = TR.get_tool("get_client_intel")
to = TR.get_tool("get_client_outstanding")
_check("T10-tools-are-read",
       ti and ti.category == "read" and to and to.category == "read")
_check("T10b-no-write-executor",   # no propose/confirm executor wired
       TR.get_executor("get_client_intel") is None
       and TR.get_executor("get_client_outstanding") is None)
# every registered tool whose name mentions 'client' is read-category
client_tools = [t for t in TR.list_tools() if "client" in t.name]
_check("T10c-all-client-tools-read",
       len(client_tools) >= 2
       and all(t.category == "read" for t in client_tools))

# dispatch does NOT mutate (count stable across a read-tool call)
before = CI.search_count([])
res_intel = TR.dispatch("get_client_intel", env, book,
                        {"partner_name": "TESTCI Alpha"})
after = CI.search_count([])
_check("T11-dispatch-read-no-mutation",
       before == after and res_intel.get("ok")
       and res_intel.get("client", {}).get("won_value") == 12000.0)

# sensitive tool DENIED to a sales user (group gate), allowed to bookkeeper
jobs_user_grp = env.ref("neon_jobs.group_neon_jobs_user")
jobsuser = Users.create({"name": "TESTCI JobsUser", "login": "ci_jobsuser",
                         "password": "test123",
                         "groups_id": [(4, jobs_user_grp.id)]})
deny = TR.dispatch("get_client_outstanding", env, jobsuser, {})
_check("T12-sensitive-tool-denied-to-sales",
       not deny.get("ok") and "access_denied" in (deny.get("error") or ""))
allow = TR.dispatch("get_client_outstanding", env, book, {})
_check("T12b-sensitive-tool-allowed-to-book", allow.get("ok"))
_check("T12c-commercial-tool-allowed-to-salestier",
       TR.dispatch("get_client_intel", env, jobsuser,
                   {"partner_name": "TESTCI Alpha"}).get("ok"))

# ---- dashboard RPC: access guard + sensitive-block gating ----
dd_book = env["neon.client.intel"].with_user(book).get_dashboard_data()
_check("T13-dashboard-finance-has-outstanding",
       dd_book.get("is_finance") is True and "outstanding" in dd_book
       and isinstance(dd_book.get("top_won"), list))
dd_sales = env["neon.client.intel"].with_user(sales).get_dashboard_data()
_check("T13b-dashboard-sales-no-outstanding",
       dd_sales.get("is_finance") is False
       and dd_sales.get("outstanding") == []
       and dd_sales.get("variant") == "sales")
try:
    env["neon.client.intel"].with_user(jobsuser).get_dashboard_data()
    _check("T13c-dashboard-denied-non-core", False, "jobsuser got data")
except Exception:  # noqa: BLE001
    _check("T13c-dashboard-denied-non-core", True)

_purge()
CI.cron_recompute()   # rebuild clean (fixtures gone)
env.cr.commit()
print("=" * 60)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 60)
