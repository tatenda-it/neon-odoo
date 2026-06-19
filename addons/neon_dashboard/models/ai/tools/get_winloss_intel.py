# -*- coding: utf-8 -*-
"""get_winloss_intel — READ-ONLY win/loss + realisation intelligence (L2.3).

Reads the STORED neon.winloss.intel (long-format: client/rep/period/category)
and narrates win-rate AND the quoted→won→invoiced realisation flow. It does NOT
compute the authoritative numbers (the cron does) and CANNOT mutate
(category="read"; no executor). Not sensitive.

HONEST: win_rate = won/total (matches the client board); realisation value is
UNTAXED (reconciles to the live Realisation pivot); the won→invoiced LINK is
100% by construction (every won quote carries an invoice link) — the real
signal is the invoiced/won VALUE realisation. No historical lost-reason.
"""
from ..tool_registry import ai_tool

_DIMS = ("rep", "client", "period", "category")


def _row(r):
    return {
        "key": r.key_label,
        "quotes": r.quotes_count, "won": r.won_count, "lost": r.lost_count,
        "win_rate_pct": round(r.win_rate * 100, 1),
        "decided_pct": round(r.decided_win_rate * 100, 1),
        "quoted_usd": round(r.quoted_value_usd or 0.0),
        "won_usd": round(r.won_value_usd or 0.0),
        "invoiced_usd": round(r.invoiced_value_usd or 0.0),
        "realisation_pct": round(r.realisation_rate * 100, 1),
    }


@ai_tool(
    name="get_winloss_intel",
    description=(
        "Read-only win/loss + realisation over the quote archive. dimension = "
        "rep / client / period / category gives win-rate (won/total) per key. "
        "With partner_name, look up one client's win-rate + realisation. "
        "Realisation = the quoted→won→invoiced value flow (USD untaxed, "
        "reconciles to the Realisation pivot); win_rate matches the client "
        "board. category cut is win-rate counts only (no value)."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "dimension": {"type": "string", "enum": list(_DIMS),
                          "description": "Cut to rank (default rep)."},
            "partner_name": {"type": "string",
                             "description": "Look up one client instead."},
            "limit": {"type": "integer",
                      "description": "Max rows (default 12, cap 25)."},
        },
    },
    category="read",
    groups=[
        "neon_jobs.group_neon_jobs_user",
        "neon_core.group_neon_bookkeeper",
        "neon_jobs.group_neon_jobs_manager",
    ],
)
def tool_get_winloss_intel(env, user, dimension="rep", partner_name=None,
                           limit=12, **_):
    W = env.get("neon.winloss.intel")
    if W is None:
        return {"ok": False, "error": "win/loss intelligence not installed"}
    limit = max(1, min(int(limit or 12), 25))

    if partner_name:
        rec = W.search([("dimension", "=", "client"),
                        ("key_label", "ilike", partner_name)], limit=1)
        if not rec:
            return {"ok": False,
                    "error": "no win/loss row for %r" % partner_name}
        return {"ok": True, "mode": "client_lookup", "client": _row(rec)}

    dim = dimension if dimension in _DIMS else "rep"
    order = ("year, month" if dim == "period" else "win_rate desc")
    dom = [("dimension", "=", dim)]
    if dim == "client":
        dom.append(("quotes_count", ">=", 3))   # min-quotes floor
    recs = W.search(dom, order=order, limit=limit)
    return {
        "ok": True, "mode": "rank", "dimension": dim,
        "note": ("win_rate=won/total; realisation=invoiced/won value (untaxed)"
                 + ("; client cut needs >=3 quotes" if dim == "client" else "")),
        "rows": [_row(r) for r in recs],
    }
