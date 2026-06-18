# -*- coding: utf-8 -*-
"""get_client_outstanding — READ-ONLY collections-side client intelligence.

SENSITIVE: outstanding balance + payment-behaviour heuristic. Gated to finance
(bookkeeper) + directors only — plain sales never get this tool advertised, and
dispatch() denies the call if they ask for it. Read-only; cannot mutate.

payment_behaviour is a HEURISTIC label (NOT a credit fact) — narrate it as such.
"""
from ..tool_registry import ai_tool


def _row(rec):
    return {
        "client": rec.client_name,
        "partner_id": rec.partner_id.id or None,
        "outstanding_usd": round(rec.outstanding_usd, 2),
        "collections_status": rec.outstanding_status or "",
        "payment_behaviour_heuristic": rec.payment_behaviour or "unknown",
        "segment": rec.segment,
    }


@ai_tool(
    name="get_client_outstanding",
    description=(
        "Read-only collections-side client intelligence: outstanding USD "
        "balance, collections status, and a payment-behaviour HEURISTIC "
        "(at_risk / slow_paying / owing / settled — not a credit fact). Use "
        "partner_name for one client, or omit it to list the largest "
        "outstanding balances. Finance/directors only."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "partner_name": {
                "type": "string",
                "description": "Case-insensitive client name match.",
            },
            "limit": {
                "type": "integer",
                "description": "Max rows when listing (default 10, capped 25).",
            },
        },
    },
    category="read",
    groups=[
        "neon_core.group_neon_bookkeeper",
        "neon_jobs.group_neon_jobs_manager",
    ],
)
def tool_get_client_outstanding(env, user, partner_name=None, limit=10, **_):
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
    recs = CI.search([("partner_id", "!=", False),
                      ("outstanding_usd", ">", 0)],
                     order="outstanding_usd desc", limit=limit)
    return {
        "ok": True,
        "mode": "rank",
        "count": len(recs),
        "clients": [_row(r) for r in recs],
    }
