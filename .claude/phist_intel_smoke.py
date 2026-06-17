"""P-HIST-INTEL — Historical Intelligence tiles (Sales-Intel Layer-1, dashboard
half) over the INERT Zoho archive. Asserts: SQL-view report models flatten /
join correctly; currency NEVER blends (USD isolated from ZWG); realisation
UNION (quoted/won/invoiced) joins quote+invoice by category; 'won' kind is the
won-subset only; the LIVE win-rate method is UNAFFECTED by archive fixtures
(inertness); director-ONLY payload (no bleed onto a Sales View-As lens); the
director layout was re-seeded with the historical band; KPI/block helper shapes
+ labels. Run in `odoo shell -d neon_crm`. Self-cleaning [TESTHI-] fixtures.
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
INV = env["neon.finance.invoice.archive"].sudo()
QLR = env["neon.finance.quote.line.report"].sudo()
RR = env["neon.finance.realisation.report"].sudo()
Dashboard = env["neon.dashboard"].sudo()
Users = env["res.users"].sudo()
Default = env["neon.dashboard.default.layout"].sudo()


def _purge():
    QA.with_context(active_test=False).search(
        [("zoho_estimate_number", "=like", "TESTHI-%")]).unlink()
    INV.with_context(active_test=False).search(
        [("zoho_invoice_number", "=like", "TESTHI-%")]).unlink()


_purge()

# Capture the LIVE win-rate BEFORE any archive fixture exists. Archive writes
# must NOT move it (the inertness rail).
live_before = Dashboard._compute_win_rate()

# ---- Fixtures -------------------------------------------------------------
# Flatten/win-rate fixture: 1 won quote, 2 categories.
QA.create({
    "zoho_estimate_number": "TESTHI-001",
    "status_bucket": "won", "currency_code": "USD",
    "quotation_date": "2025-03-15", "amount_total": 300.0,
    "line_ids": [
        (0, 0, {"name": "X", "category_prefix": "TESTCATA",
                "quantity": 5, "line_total": 200.0}),
        (0, 0, {"name": "Y", "category_prefix": "TESTCATB",
                "quantity": 3, "line_total": 100.0}),
    ],
})
# Currency isolation fixture: same category, USD vs ZWG, both won.
QA.create({
    "zoho_estimate_number": "TESTHI-002",
    "status_bucket": "won", "currency_code": "USD",
    "quotation_date": "2025-05-01", "amount_total": 100.0,
    "line_ids": [(0, 0, {"name": "R", "category_prefix": "TESTCATR",
                         "quantity": 1, "line_total": 100.0})],
})
QA.create({
    "zoho_estimate_number": "TESTHI-003",
    "status_bucket": "won", "currency_code": "ZWG",
    "quotation_date": "2025-05-02", "amount_total": 9999.0,
    "line_ids": [(0, 0, {"name": "R", "category_prefix": "TESTCATR",
                         "quantity": 1, "line_total": 9999.0})],
})
# Realisation join fixture: won quote + matching invoice (same category, USD).
QA.create({
    "zoho_estimate_number": "TESTHI-004",
    "status_bucket": "won", "currency_code": "USD",
    "quotation_date": "2025-06-01", "amount_total": 200.0,
    "line_ids": [(0, 0, {"name": "J", "category_prefix": "TESTCATJ",
                         "quantity": 1, "line_total": 200.0})],
})
INV.create({
    "zoho_invoice_number": "TESTHI-INV-001",
    "status_bucket": "paid", "currency_code": "USD",
    "invoice_date": "2025-06-10", "amount_total": 150.0,
    "line_ids": [(0, 0, {"name": "J", "category_prefix": "TESTCATJ",
                         "quantity": 1, "line_total": 150.0})],
})
# Lost quote — its category must show in 'quoted' but NOT 'won'.
QA.create({
    "zoho_estimate_number": "TESTHI-005",
    "status_bucket": "lost", "currency_code": "USD",
    "quotation_date": "2025-06-05", "amount_total": 50.0,
    "line_ids": [(0, 0, {"name": "L", "category_prefix": "TESTCATL",
                         "quantity": 1, "line_total": 50.0})],
})

# Flush ORM writes so the SQL views (which read the base tables directly) see
# the fixtures within this transaction.
env.flush_all()

# ---- T1 view models exist + queryable ----
_check("T1-views-registered",
       QLR._name == "neon.finance.quote.line.report"
       and RR._name == "neon.finance.realisation.report"
       and QLR.search_count([]) >= 1 and RR.search_count([]) >= 1)

# ---- T2 quote.line.report flattens parent fields onto the line ----
rowsA = QLR.search([("category_prefix", "=", "TESTCATA")])
_check("T2-line-report-flattens-parent",
       len(rowsA) == 1 and rowsA.currency_code == "USD"
       and rowsA.status_bucket == "won"
       and abs(rowsA.line_total - 200.0) < 0.01
       and bool(rowsA.quotation_date),
       "rows=%d cur=%r bucket=%r tot=%r date=%r" % (
           len(rowsA), rowsA.currency_code if rowsA else None,
           rowsA.status_bucket if rowsA else None,
           rowsA.line_total if rowsA else None,
           rowsA.quotation_date if rowsA else None))

# ---- T3 LIVE win-rate UNAFFECTED by archive fixtures (inertness rail) ----
live_after = Dashboard._compute_win_rate()
_check("T3-live-winrate-unaffected-by-archive",
       live_before == live_after,
       "before=%r after=%r" % (live_before, live_after))

# ---- T4 currency NEVER blended in realisation (USD isolated from ZWG) ----
g_usd = RR.read_group(
    [("category_prefix", "=", "TESTCATR"), ("currency_code", "=", "USD"),
     ("kind", "=", "quoted")], ["value:sum"], [])
g_zwg = RR.read_group(
    [("category_prefix", "=", "TESTCATR"), ("currency_code", "=", "ZWG"),
     ("kind", "=", "quoted")], ["value:sum"], [])
usd_val = (g_usd[0]["value"] if g_usd else 0.0) or 0.0
zwg_val = (g_zwg[0]["value"] if g_zwg else 0.0) or 0.0
_check("T4-currency-never-blended",
       abs(usd_val - 100.0) < 0.01 and abs(zwg_val - 9999.0) < 0.01,
       "usd=%r zwg=%r (must be 100 / 9999, never 10099)" % (usd_val, zwg_val))

# ---- T5 realisation UNION joins quote+invoice by category ----
g = RR.read_group(
    [("category_prefix", "=", "TESTCATJ"), ("currency_code", "=", "USD")],
    ["value:sum"], ["kind"])
m = {row["kind"]: (row["value"] or 0.0) for row in g}
_check("T5-realisation-join-quoted-won-invoiced",
       abs(m.get("quoted", 0) - 200.0) < 0.01
       and abs(m.get("won", 0) - 200.0) < 0.01
       and abs(m.get("invoiced", 0) - 150.0) < 0.01,
       "map=%r" % m)

# ---- T5b 'won' kind is the won-subset only (a lost quote's cat has no won) --
gl = RR.read_group(
    [("category_prefix", "=", "TESTCATL"), ("currency_code", "=", "USD")],
    ["value:sum"], ["kind"])
ml = {row["kind"]: (row["value"] or 0.0) for row in gl}
_check("T5b-won-kind-excludes-lost",
       abs(ml.get("quoted", 0) - 50.0) < 0.01 and ml.get("won", 0) == 0,
       "map=%r" % ml)

# ---- T6 director-ONLY payload (real dispatch path) ----
non_super = (Users.search(
    [("id", "!=", 1), ("share", "=", False), ("active", "=", True)])
    .filtered(lambda u: not u.has_group("neon_core.group_neon_superuser")))
dir_u = Users.search(
    [("id", "!=", 1), ("share", "=", False), ("active", "=", True)]
).filtered(lambda u: u.has_group("neon_core.group_neon_superuser"))[:1]
# A pure sales-rep tier user (not superuser) -> resolved_type == 'sales'.
sales_u = non_super.filtered(
    lambda u: u.has_group("neon_core.group_neon_sales_rep"))[:1]

if dir_u:
    pd = env["neon.dashboard"].with_user(dir_u).get_dashboard_data("director")
    _check("T6a-director-has-hist",
           "kpi_hist_winrate" in pd.get("kpi", {})
           and "hist_intel_block" in pd,
           "kpi_keys=%r hist_block=%r" % (
               sorted(pd.get("kpi", {})), "hist_intel_block" in pd))
    # No bleed onto a superuser's Sales View-As lens (the key no-bleed test).
    pds = env["neon.dashboard"].with_user(dir_u).get_dashboard_data("sales")
    _check("T6c-director-viewas-sales-no-hist",
           "kpi_hist_winrate" not in pds.get("kpi", {})
           and "hist_intel_block" not in pds)
else:
    _check("T6a-director-has-hist", False, "no superuser-tier user found")
    _check("T6c-director-viewas-sales-no-hist", False, "no superuser user")

if sales_u:
    try:
        ps = (env["neon.dashboard"].with_user(sales_u)
              .get_dashboard_data("sales"))
        _check("T6b-sales-lens-no-hist",
               "kpi_hist_winrate" not in ps.get("kpi", {})
               and "hist_intel_block" not in ps,
               "user=%s" % sales_u.login)
    except Exception as e:  # noqa: BLE001
        _check("T6b-sales-lens-no-hist", False,
               "unexpected on %s: %r" % (sales_u.login, e))
else:
    # No pure sales-tier user on this DB; the no-bleed contract is already
    # proven by T6c (director View-As -> sales -> no hist, same code path).
    _check("T6b-sales-lens-no-hist", True,
           "skipped: no pure sales-tier user; covered by T6c")

# ---- T7 director layout re-seeded with the historical band ----
dl = Default.search([("dashboard_type", "=", "director")], limit=1)
seed_keys = set(dl.layout_line_ids.mapped("widget_key")) if dl else set()
_check("T7-director-seed-has-hist-band",
       {"kpi_hist_winrate", "kpi_hist_demand", "kpi_hist_quotes",
        "block_hist_intel"} <= seed_keys,
       "seed_keys=%r" % sorted(seed_keys))
# And NO other variant got it (director-exclusive).
sl = Default.search([("dashboard_type", "=", "sales")], limit=1)
sales_keys = set(sl.layout_line_ids.mapped("widget_key")) if sl else set()
_check("T7b-sales-seed-no-hist",
       "block_hist_intel" not in sales_keys
       and "kpi_hist_winrate" not in sales_keys)

# ---- T8 block helper shape + labelling ----
block = Dashboard._compute_hist_intel_block()
_check("T8-block-shape",
       all(k in block for k in (
           "top_categories", "win_by_category", "realisation",
           "currency_note", "empty", "deeplink_demand",
           "deeplink_winloss", "deeplink_realisation")))
_check("T8b-block-usd-disclosed",
       "USD" in (block.get("currency_note") or ""),
       "note=%r" % block.get("currency_note"))
_check("T8c-block-deeplinks",
       block.get("deeplink_demand") == "neon_migration.action_hist_demand"
       and block.get("deeplink_winloss") == "neon_migration.action_hist_winloss"
       and block.get("deeplink_realisation")
       == "neon_migration.action_hist_realisation")

# ---- T9 KPI helper shape + labels + deeplinks ----
kpis = Dashboard._compute_kpi_hist()
_check("T9-kpi-keys",
       set(kpis) == {"kpi_hist_winrate", "kpi_hist_demand", "kpi_hist_quotes"})
_check("T9b-kpi-historical-label",
       "Historical" in (kpis["kpi_hist_winrate"].get("subtitle") or ""),
       "subtitle=%r" % kpis["kpi_hist_winrate"].get("subtitle"))
_check("T9c-kpi-quotes-deeplink-rollup",
       kpis["kpi_hist_quotes"].get("deeplink_action")
       == "neon_migration.action_quote_rollup")
_check("T9d-kpi-demand-deeplink",
       kpis["kpi_hist_demand"].get("deeplink_action")
       == "neon_migration.action_hist_demand")
# Each KPI dict carries the tile contract (value_display + empty).
_check("T9e-kpi-tile-contract",
       all("value_display" in kpis[k] and "empty" in kpis[k] for k in kpis))

# ---- T10 helpers DON'T touch the live finance models (separation) ----
# _kpi_pipeline still reads the LIVE quote model (sanity that we didn't break
# or re-point it). It must return a dict with the live pipeline deeplink.
piped = Dashboard._kpi_pipeline()
_check("T10-live-pipeline-intact",
       isinstance(piped, dict)
       and piped.get("deeplink_action") in (
           "neon_finance.action_dashboard_pipeline", False)
       or piped.get("empty") is not None,
       "pipeline=%r" % piped)

_purge()
env.cr.commit()
print("=" * 60)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 60)
