"""P-WINLOSS-INTEL — L2.3 win/loss + realisation (computed, read-only).

Win-rate compute by client/rep/period/category (won/total, matches L2.1);
realisation value flow quoted→won→invoiced (UNTAXED, reconciles to L1); USD-only
guard (ZWG counted, value disclosed not blended); invoice-side realisation
merges into the same segment keys; category cut = counts only; honest notes
(real lost; won→invoiced link 100% by construction; no lost-reason field). ACL
read-only + all-commercial read; dashboard RPC; copilot tool read-only contract.
[TESTW] fixtures, self-cleaning.
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

CG = {"__name__": "winloss_compute_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/compute_winloss_intel.py")
     .read(), CG)
compute = CG["compute_winloss_rows"]
norm_cat = CG["_norm_cat"]

P = env["res.partner"].sudo()
Q = env["neon.finance.quote.archive"].sudo()
QL = env["neon.finance.quote.archive.line"].sudo()
IA = env["neon.finance.invoice.archive"].sudo()
W = env["neon.winloss.intel"].sudo()
Users = env["res.users"].sudo()


def _purge():
    Q.search([("zoho_estimate_number", "=like", "TESTW%")]).unlink()
    IA.search([("zoho_invoice_number", "=like", "TESTW%")]).unlink()
    # users BEFORE their partners (a partner linked to an active user is
    # un-deletable -> RedirectWarning).
    Users.with_context(active_test=False).search(
        [("login", "in", ("twl_sales", "twl_book", "twl_jobs"))]).unlink()
    P.with_context(active_test=False).search(
        [("name", "=like", "TESTW %")]).unlink()


_purge()
_check("T0-norm-cat", norm_cat("  Power   Equipment ") == "POWER EQUIPMENT"
       and norm_cat("power equipment") == "POWER EQUIPMENT")

A = P.create({"name": "TESTW Alpha", "is_company": True})
B = P.create({"name": "TESTW Beta", "is_company": True})


def mkq(num, partner, bucket, ccy, unt, qdate, rep="TESTW Rep", invlink=None):
    return Q.create({
        "zoho_estimate_number": num, "partner_id": partner.id,
        "status_bucket": bucket, "currency_code": ccy,
        "amount_untaxed": unt, "amount_total": round(unt * 1.15, 2),
        "quotation_date": qdate, "salesperson_name": rep,
        "zoho_invoice_number": invlink or False})


def mkline(q, cat, total):
    QL.create({"archive_id": q.id, "name": "TESTW item", "category_prefix": cat,
               "line_total": total})


def mki(num, partner, ccy, unt, idate, rep="TESTW Rep"):
    IA.create({"zoho_invoice_number": num, "partner_id": partner.id,
               "currency_code": ccy, "amount_untaxed": unt,
               "amount_total": round(unt * 1.15, 2), "invoice_date": idate,
               "status_bucket": "paid", "salesperson_name": rep})


q1 = mkq("TESTW-Q1", A, "won", "USD", 1000.0, "2025-05-10", invlink="TESTW-INV1")
q2 = mkq("TESTW-Q2", A, "lost", "USD", 500.0, "2025-05-11")
q3 = mkq("TESTW-Q3", A, "open", "USD", 200.0, "2025-05-12")
q4 = mkq("TESTW-Q4", B, "won", "USD", 2000.0, "2025-06-01")
q5 = mkq("TESTW-Q5", B, "won", "ZWG", 9999.0, "2025-06-02")   # ZWG: not summed
mkline(q1, "TESTW CATX", 1000.0)
mkline(q2, "TESTW CATX", 500.0)
mkline(q3, "testw catx", 200.0)                                # case -> merges
mki("TESTW-INV1", A, "USD", 1100.0, "2025-07-05")             # realised > won
env.flush_all()

rows, stats = compute(env)


def find(dim, key):
    for r in rows:
        if r["dimension"] == dim and r["key_label"] == key:
            return r
    return None


ca, cb = find("client", "TESTW Alpha"), find("client", "TESTW Beta")
_check("T1-client-alpha-winloss",
       ca and ca["quotes_count"] == 3 and ca["won_count"] == 1
       and ca["lost_count"] == 1 and ca["open_count"] == 1
       and abs(ca["win_rate"] - 1 / 3) < 0.001
       and abs(ca["decided_win_rate"] - 0.5) < 0.001)
_check("T1b-client-alpha-realisation",   # quoted/won untaxed + invoiced + rate
       abs(ca["quoted_value_usd"] - 1700) < 0.1
       and abs(ca["won_value_usd"] - 1000) < 0.1
       and ca["invoiced_count"] == 1
       and abs(ca["invoiced_value_usd"] - 1100) < 0.1
       and abs(ca["realisation_rate"] - 1.1) < 0.001)
_check("T2-usd-guard",   # B: ZWG won counted, value excluded -> disclosed
       cb and cb["quotes_count"] == 2 and cb["won_count"] == 2
       and abs(cb["quoted_value_usd"] - 2000) < 0.1
       and abs(cb["won_value_usd"] - 2000) < 0.1
       and abs(cb["nonusd_quote_value"] - 9999) < 0.1)

rep = find("rep", "TESTW Rep")
_check("T3-rep-merge-quote-and-invoice",
       rep and rep["quotes_count"] == 5 and rep["won_count"] == 3
       and abs(rep["won_value_usd"] - 3000) < 0.1
       and rep["invoiced_count"] == 1
       and abs(rep["invoiced_value_usd"] - 1100) < 0.1)

p5, p6, p7 = find("period", "2025-05"), find("period", "2025-06"), \
    find("period", "2025-07")
_check("T4-period-quotes-by-quotedate",
       p5 and p5["quotes_count"] == 3 and p5["won_count"] == 1
       and p6 and p6["quotes_count"] == 2 and p6["won_count"] == 2)
_check("T4b-period-invoiced-by-invoicedate",   # invoice realised in 2025-07
       p7 and p7["invoiced_count"] == 1
       and abs(p7["invoiced_value_usd"] - 1100) < 0.1
       and p7["quotes_count"] == 0)

cat = find("category", "TESTW CATX")
_check("T5-category-counts-only",
       cat and cat["quotes_count"] == 3 and cat["won_count"] == 1
       and abs(cat["win_rate"] - 1 / 3) < 0.001
       and cat["quoted_value_usd"] == 0.0    # value NOT summed for category
       and cat["invoiced_value_usd"] == 0.0)

_check("T6-overall-reconcile",
       abs(stats["quoted_value_usd"] - 3700) < 0.1
       and abs(stats["won_value_usd"] - 3000) < 0.1
       and abs(stats["invoiced_value_usd"] - 1100) < 0.1
       and stats["won"] == 3 and stats["lost"] == 1)
_check("T6b-link-100pct-disclosed",   # every won quote with a link
       stats["won_with_link"] == 1)   # only q1 had a link in fixtures
_check("T7-no-lost-reason-field",   # honest: no fabricated lost-reason
       not any(f in W._fields for f in
               ("lost_reason", "loss_reason", "lost_reason_id")))

# ---- recompute idempotency ----
W.cron_recompute()
env.flush_all()
n1 = W.search_count([])
W.cron_recompute()
env.flush_all()
n2 = W.search_count([])
_check("T8-recompute-idempotent", n1 == n2 and n1 > 0, "n1=%s n2=%s" % (n1, n2))
ar = W.search([("dimension", "=", "client"),
               ("key_label", "=", "TESTW Alpha")], limit=1)
_check("T8b-persists",
       ar and ar.won_count == 1 and abs(ar.invoiced_value_usd - 1100) < 0.1
       and bool(ar.last_computed))

# ---- ACL: read-only, all-commercial read ----
srep = env.ref("neon_core.group_neon_sales_rep")
bg = env.ref("neon_core.group_neon_bookkeeper")
jobs_user_grp = env.ref("neon_jobs.group_neon_jobs_user")
sales = Users.create({"name": "TESTW Sales", "login": "twl_sales",
                      "password": "test123", "groups_id": [(4, srep.id)]})
book = Users.create({"name": "TESTW Book", "login": "twl_book",
                     "password": "test123", "groups_id": [(4, bg.id)]})
jobsu = Users.create({"name": "TESTW Jobs", "login": "twl_jobs",
                      "password": "test123",
                      "groups_id": [(4, jobs_user_grp.id)]})
try:
    env["neon.winloss.intel"].with_user(sales).create({"dimension": "rep"})
    _check("T9-model-read-only", False, "sales created a winloss row!")
except Exception:  # noqa: BLE001
    _check("T9-model-read-only", True)
_check("T9b-sales-can-read",
       env["neon.winloss.intel"].with_user(sales).search_count([]) > 0)

# ---- dashboard RPC ----
dd = env["neon.winloss.intel"].with_user(sales).get_dashboard_data()
_check("T10-dashboard-payload",
       dd.get("variant") == "sales"
       and isinstance(dd.get("by_rep"), list)
       and isinstance(dd.get("by_category"), list)
       and isinstance(dd.get("by_period"), list)
       and isinstance(dd.get("top_client_winrate"), list)
       and "realisation_pct" in dd.get("overall", {})
       and "win_value_rate_pct" in dd.get("overall", {}))
try:
    env["neon.winloss.intel"].with_user(jobsu).get_dashboard_data()
    _check("T10b-dashboard-denied-non-core", False, "jobs-user got data")
except Exception:  # noqa: BLE001
    _check("T10b-dashboard-denied-non-core", True)

# ---- copilot tool: read-only contract + count ----
from odoo.addons.neon_ai_core.models.ai import tool_registry as TR  # noqa: E402
tw = TR.get_tool("get_winloss_intel")
_check("T11-tool-is-read", tw and tw.category == "read")
_check("T11b-no-executor", TR.get_executor("get_winloss_intel") is None)
_check("T11c-tool-count",   # +1 read vs L2.2 -> 18 reads / 22 total
       len(TR.tool_names(category="read")) == 18 and len(TR.list_tools()) == 22,
       "reads=%d total=%d" % (len(TR.tool_names(category="read")),
                              len(TR.list_tools())))
before = W.search_count([])
res = TR.dispatch("get_winloss_intel", env, book, {"dimension": "rep"})
after = W.search_count([])
_check("T12-dispatch-read-no-mutation",
       before == after and res.get("ok") and isinstance(res.get("rows"), list))
res_c = TR.dispatch("get_winloss_intel", env, book,
                    {"partner_name": "TESTW Alpha"})
_check("T12b-client-lookup",
       res_c.get("ok") and res_c.get("client", {}).get("won") == 1
       and res_c["client"].get("invoiced_usd") == 1100)

_purge()
W.cron_recompute()   # rebuild clean (fixtures gone)
env.cr.commit()
print("=" * 60)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 60)
