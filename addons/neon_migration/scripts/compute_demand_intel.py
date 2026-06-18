# -*- coding: utf-8 -*-
"""Demand & seasonality — the L2.2 aggregation (PURE READ).

Aggregates the job + quote spine BY TIME (year, month) — NOT by event-type:
STEP-0 confirmed the data has no usable event-type taxonomy (job.history
event_type is uniformly 'event'; quotes carry none), so a type dimension would
be a single useless bucket. Instead this is the data-backed seasonality core
plus DESCRIPTIVE recurring-named-event detection.

This module computes ONLY — it reads and returns dicts; it NEVER writes. The
model's cron_recompute() persists; the gate dry-run probe calls the same
function and prints. Mirrors the L2.1 parse/loader split.

Sources (verified field names):
  neon.job.history (is_job)    date_start, title            -> jobs by month
  neon.finance.quote.archive   quotation_date, amount_total,
                               currency_code, status_bucket -> quote volume/value

CONVENTIONS:
  * MONEY = USD only (quotes_value_usd / won_value_usd sum currency_code=='USD');
    non-USD value disclosed separately (nonusd_quote_value), NEVER blended.
  * 0 undated jobs/quotes in the data (confirmed) — undated would be tallied to
    stats and skipped from the month grain, never given a fabricated month.
  * RECURRING = a normalised job TITLE appearing in >= RECURRING_MIN_YEARS
    distinct years. DESCRIPTIVE only ("recurred in 2024/2025"), NOT a forecast.
"""
import re
from datetime import date

USD = "USD"
RECURRING_MIN_YEARS = 2     # title in >=2 distinct years => recurring (descriptive)
MIN_TITLE_LEN = 5           # skip too-generic normalised titles (avoid false merges)


def _norm_title(t):
    """lowercase, strip 4-digit year tokens, drop punctuation, collapse — so a
    yearly event ('ZITF 2024' / 'ZITF 2025') merges, but distinct names don't."""
    t = (t or "").lower()
    t = re.sub(r"\b(19|20)\d\d\b", " ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _as_date(d):
    if not d:
        return None
    return d.date() if hasattr(d, "date") else d


def compute_demand_rows(env, today=None):
    """Return (demand_rows, recurring_rows, stats). PURE READ — no writes.
    demand_rows: one dict per (year, month). recurring_rows: one per recurring
    normalised title."""
    today = today or date.today()
    J = env["neon.job.history"].sudo()
    Q = env["neon.finance.quote.archive"].sudo()

    demand = {}

    def cell(y, m):
        return demand.setdefault((y, m), {
            "jobs_count": 0, "quotes_count": 0, "quotes_value_usd": 0.0,
            "won_count": 0, "won_value_usd": 0.0, "nonusd_quote_value": 0.0})

    stats = {"jobs": 0, "quotes": 0, "undated_jobs": 0, "undated_quotes": 0,
             "nonusd_quote_value": 0.0, "nonusd_quotes": 0,
             "job_years": set(), "quote_years": set(), "title_skipped": 0}
    titles = {}

    for j in J.search([("is_job", "=", True)]):
        stats["jobs"] += 1
        d = _as_date(j.date_start)
        if not d:
            stats["undated_jobs"] += 1
            continue
        cell(d.year, d.month)["jobs_count"] += 1
        stats["job_years"].add(d.year)
        nt = _norm_title(j.title)
        if len(nt) < MIN_TITLE_LEN:
            stats["title_skipped"] += 1
            continue
        e = titles.setdefault(nt, {"raw": set(), "years": set(),
                                   "count": 0, "dates": []})
        e["raw"].add((j.title or "").strip())
        e["years"].add(d.year)
        e["count"] += 1
        e["dates"].append(d)

    for q in Q.search([]):
        stats["quotes"] += 1
        d = q.quotation_date
        if not d:
            stats["undated_quotes"] += 1
            continue
        c = cell(d.year, d.month)
        c["quotes_count"] += 1
        stats["quote_years"].add(d.year)
        amt = float(q.amount_total or 0.0)
        usd = (q.currency_code or USD).upper() == USD
        if usd:
            c["quotes_value_usd"] += amt
        else:
            c["nonusd_quote_value"] += amt
            stats["nonusd_quote_value"] += amt
            stats["nonusd_quotes"] += 1
        if q.status_bucket == "won":
            c["won_count"] += 1
            if usd:
                c["won_value_usd"] += amt

    demand_rows = []
    for (y, m), c in demand.items():
        demand_rows.append({
            "year": y, "month": m,
            "jobs_count": c["jobs_count"],
            "quotes_count": c["quotes_count"],
            "quotes_value_usd": round(c["quotes_value_usd"], 2),
            "won_count": c["won_count"],
            "won_value_usd": round(c["won_value_usd"], 2),
            "nonusd_quote_value": round(c["nonusd_quote_value"], 2),
        })

    recurring_rows = []
    for nt, e in titles.items():
        if len(e["years"]) >= RECURRING_MIN_YEARS:
            ds = sorted(e["dates"])
            recurring_rows.append({
                "normalised_title": nt,
                "sample_raw_title": sorted(e["raw"])[0][:160],
                "distinct_years": len(e["years"]),
                "year_list": ", ".join(str(y) for y in sorted(e["years"])),
                "total_occurrences": e["count"],
                "first_seen": ds[0],
                "last_seen": ds[-1],
            })

    stats["job_years"] = sorted(stats["job_years"])
    stats["quote_years"] = sorted(stats["quote_years"])
    stats["recurring_titles"] = len(recurring_rows)
    stats["distinct_titles"] = len(titles)
    return demand_rows, recurring_rows, stats
