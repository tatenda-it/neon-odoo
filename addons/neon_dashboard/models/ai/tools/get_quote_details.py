# -*- coding: utf-8 -*-
"""get_quote_details — full breakdown for a single quote."""
from ..tool_registry import ai_tool


@ai_tool(
    name="get_quote_details",
    description=(
        "Return a full breakdown of a single quote: lines, "
        "totals, margin, payment terms, expiry."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "quote_id": {
                "type": "integer",
                "description": "ID of the neon.finance.quote.",
            },
        },
        "required": ["quote_id"],
    },
    category="read",
)
def tool_get_quote_details(env, user, quote_id=None, **_):
    if not quote_id:
        return {"ok": False, "error": "quote_id is required"}
    Quote = env["neon.finance.quote"]
    q = Quote.browse(int(quote_id)).exists()
    if not q:
        return {"ok": False, "error": f"Quote {quote_id} not found"}
    lines = []
    for line in q.line_ids:
        lines.append({
            "id": line.id,
            "name": line.name or "",
            "line_type": line.line_type,
            "quantity": float(line.quantity or 0),
            "unit_rate": float(line.unit_rate or 0),
            "duration_days": int(line.duration_days or 0),
            "subtotal": float(line.line_subtotal or 0),
            "pricing_status": line.pricing_status,
        })
    return {
        "ok": True,
        "quote": {
            "id": q.id,
            "name": q.name,
            "partner_name": q.partner_id.name if q.partner_id else "",
            "partner_id": q.partner_id.id if q.partner_id else False,
            "state": q.state,
            "state_label": dict(q._fields["state"].selection).get(
                q.state, q.state),
            "currency": q.currency_id.name if q.currency_id else "USD",
            "amount_untaxed": float(q.amount_untaxed or 0.0),
            "amount_tax": float(q.amount_tax or 0.0),
            "amount_total": float(q.amount_total or 0.0),
            "margin_total": float(q.margin_total or 0.0),
            "margin_pct": float(q.margin_pct or 0.0),
            "payment_term": (q.payment_term_id.name
                             if q.payment_term_id else ""),
            "expires_at": (q.expires_at.isoformat()
                           if q.expires_at else ""),
            "salesperson": (q.salesperson_id.name
                            if q.salesperson_id else ""),
            "lines": lines,
        },
    }
