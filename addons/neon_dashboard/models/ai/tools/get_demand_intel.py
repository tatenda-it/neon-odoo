# -*- coding: utf-8 -*-
"""get_demand_intel — READ-ONLY demand & seasonality (L2.2).

Reads the STORED neon.demand.intel (by month) + neon.demand.recurring
(descriptive recurring named events) and narrates seasonality / YoY / cadence.
It does NOT compute the authoritative numbers (the cron does) and CANNOT mutate
(category="read"; no executor). Not sensitive — no debtor/payment data here.
Recurrence is DESCRIPTIVE, never a forecast.
"""
from ..tool_registry import ai_tool

_M = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@ai_tool(
    name="get_demand_intel",
    description=(
        "Read-only demand & seasonality over jobs + quotes, by month. With "
        "recurring=true, list recurring NAMED events (titles seen in 2+ years "
        "— descriptive cadence, not a forecast). With a year, return that "
        "year's monthly jobs/quotes. Otherwise return per-year totals + the "
        "peak demand months. Money is USD (non-USD disclosed separately)."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "year": {"type": "integer",
                     "description": "Return this year's 12 months."},
            "recurring": {"type": "boolean",
                          "description": "List recurring named events instead."},
        },
    },
    category="read",
    groups=[
        "neon_jobs.group_neon_jobs_user",
        "neon_core.group_neon_bookkeeper",
        "neon_jobs.group_neon_jobs_manager",
    ],
)
def tool_get_demand_intel(env, user, year=None, recurring=False, **_):
    D = env.get("neon.demand.intel")
    if D is None:
        return {"ok": False, "error": "demand intelligence not installed"}

    if recurring:
        R = env.get("neon.demand.recurring")
        recs = R.search([], order="distinct_years desc, total_occurrences desc",
                        limit=20) if R is not None else []
        return {
            "ok": True, "mode": "recurring",
            "note": "descriptive cadence only — not a forecast",
            "events": [{
                "event": r.sample_raw_title, "years": r.year_list,
                "distinct_years": r.distinct_years,
                "occurrences": r.total_occurrences,
            } for r in recs],
        }

    if year:
        rows = D.search([("year", "=", int(year))], order="month")
        return {
            "ok": True, "mode": "year", "year": int(year),
            "months": [{
                "month": _M[r.month] if 0 < r.month < 13 else r.month,
                "jobs": r.jobs_count, "quotes": r.quotes_count,
                "quotes_value_usd": round(r.quotes_value_usd or 0.0),
            } for r in rows],
        }

    # default: per-year totals + peak months across all years
    rows = D.search([])
    yoy = {}
    season = {m: 0 for m in range(1, 13)}
    for r in rows:
        y = yoy.setdefault(r.year, {"year": r.year, "jobs": 0, "quotes": 0,
                                    "quotes_value_usd": 0.0})
        y["jobs"] += r.jobs_count
        y["quotes"] += r.quotes_count
        y["quotes_value_usd"] += r.quotes_value_usd or 0.0
        season[r.month] += r.jobs_count
    peak = sorted(season.items(), key=lambda kv: -kv[1])[:3]
    return {
        "ok": True, "mode": "summary",
        "per_year": [{**v, "quotes_value_usd": round(v["quotes_value_usd"])}
                     for v in sorted(yoy.values(), key=lambda x: x["year"])],
        "peak_months_by_jobs": [{"month": _M[m], "jobs": c} for m, c in peak],
        "nonusd_disclosed": round(
            sum(r.nonusd_quote_value or 0.0 for r in rows)),
    }
