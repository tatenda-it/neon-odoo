# -*- coding: utf-8 -*-
"""get_client_intel — READ-ONLY client/account intelligence (L2.1).

Reads the STORED neon.client.intel rollups and narrates/ranks/compares. It does
NOT compute the authoritative numbers (the cron does) and CANNOT mutate anything
(category="read"; no executor registered). Commercial fields only — the
sensitive collections fields live in get_client_outstanding (finance-gated).
"""
from ..tool_registry import ai_tool

# ranking floor so a 1/1 = 100% win rate can't top the win-rate board
_MIN_QUOTES_WINRATE = 3

_RANKABLE = {
    "won_value": "won_value desc",
    "quotes_value": "quotes_value desc",
    "win_rate": "win_rate desc",
    "jobs_count": "jobs_count desc",
    "recency_days": "recency_days desc",   # most dormant first
}


def _row(rec):
    return {
        "client": rec.client_name,
        "partner_id": rec.partner_id.id or None,
        "segment": rec.segment,
        "quotes_count": rec.quotes_count,
        "quotes_value": round(rec.quotes_value, 2),
        "won_count": rec.won_count,
        "won_value": round(rec.won_value, 2),
        "win_rate_pct": round(rec.win_rate * 100, 1),
        "invoices_count": rec.invoices_count,
        "invoiced_value": round(rec.invoiced_value, 2),
        "jobs_count": rec.jobs_count,
        "active_years": rec.active_years,
        "recency_days": rec.recency_days,
        "event_types": rec.event_types or "",
    }


@ai_tool(
    name="get_client_intel",
    description=(
        "Read-only client/account intelligence rollups (quotes, wins, win "
        "rate, jobs, recency, segment). Use partner_name to look up one "
        "client; or top_by to rank clients (won_value / quotes_value / "
        "win_rate / jobs_count / recency_days); or segment to filter "
        "(high_value_repeat / steady / quote_heavy_low_convert / new / "
        "dormant / one_off). Currency is USD. Numbers come from the stored "
        "nightly rollup; this tool only reads them."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "partner_name": {
                "type": "string",
                "description": "Case-insensitive client name match.",
            },
            "top_by": {
                "type": "string",
                "enum": list(_RANKABLE.keys()),
                "description": "Rank clients by this metric (desc).",
            },
            "segment": {
                "type": "string",
                "description": "Filter to a segment.",
            },
            "limit": {
                "type": "integer",
                "description": "Max rows (default 10, capped 25).",
            },
        },
    },
    category="read",
    groups=[
        "neon_jobs.group_neon_jobs_user",
        "neon_core.group_neon_bookkeeper",
        "neon_jobs.group_neon_jobs_manager",
    ],
)
def tool_get_client_intel(env, user, partner_name=None, top_by=None,
                          segment=None, limit=10, **_):
    CI = env.get("neon.client.intel")
    if CI is None:
        return {"ok": False, "error": "client intelligence not installed"}
    limit = max(1, min(int(limit or 10), 25))

    if partner_name:
        rec = CI.search([("client_name", "ilike", partner_name),
                         ("partner_id", "!=", False)], limit=1)
        if not rec:
            return {"ok": False,
                    "error": "no client rollup for %r" % partner_name}
        return {"ok": True, "mode": "lookup", "client": _row(rec)}

    domain = [("partner_id", "!=", False)]
    if segment:
        domain.append(("segment", "=", segment))
    order = _RANKABLE.get(top_by or "won_value", "won_value desc")
    if top_by == "win_rate":
        domain.append(("quotes_count", ">=", _MIN_QUOTES_WINRATE))
    recs = CI.search(domain, order=order, limit=limit)
    return {
        "ok": True,
        "mode": "rank",
        "ranked_by": top_by or "won_value",
        "segment": segment or "all",
        "count": len(recs),
        "clients": [_row(r) for r in recs],
        "note": ("win_rate ranking requires >= %d quotes" % _MIN_QUOTES_WINRATE
                 ) if top_by == "win_rate" else "",
    }
