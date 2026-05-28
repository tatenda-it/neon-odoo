# -*- coding: utf-8 -*-
"""get_open_quotes — list the active user's open quotes."""
from datetime import date

from ..tool_registry import ai_tool


_OPEN_STATES = ("draft", "pending_approval", "approved", "sent")


@ai_tool(
    name="get_open_quotes",
    description=(
        "Return quotes owned by the current user that are still "
        "in play (not terminal). Use this when the user asks "
        "about their open quotes, pipeline value, or quote aging."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "state_filter": {
                "type": "string",
                "description": (
                    "Optional Odoo state value: draft, "
                    "pending_approval, approved, sent. Omit for "
                    "all open quotes."
                ),
            },
            "value_min": {
                "type": "number",
                "description": "Minimum amount_total to include.",
            },
            "days_old_min": {
                "type": "integer",
                "description": (
                    "Only return quotes whose create_date is at "
                    "least this many days ago."
                ),
            },
        },
    },
    category="read",
)
def tool_get_open_quotes(env, user, state_filter=None,
                        value_min=None, days_old_min=None, **_):
    Quote = env["neon.finance.quote"]
    domain = [
        ("salesperson_id", "=", user.id),
        ("state", "in", list(_OPEN_STATES)),
    ]
    if state_filter and state_filter in _OPEN_STATES:
        domain = [d for d in domain if d[0] != "state"]
        domain.append(("state", "=", state_filter))
    if value_min:
        domain.append(("amount_total", ">=", float(value_min)))

    quotes = Quote.search(domain, order="create_date desc", limit=50)
    today = date.today()
    rows = []
    for q in quotes:
        days_old = ((today - q.create_date.date()).days
                    if q.create_date else 0)
        if days_old_min and days_old < int(days_old_min):
            continue
        rows.append({
            "id": q.id,
            "name": q.name or "",
            "partner_id": q.partner_id.id if q.partner_id else False,
            "partner_name": q.partner_id.name if q.partner_id else "",
            "amount_total": float(q.amount_total or 0.0),
            "currency": q.currency_id.name if q.currency_id else "USD",
            "days_old": days_old,
            "state": q.state,
            "state_label": dict(q._fields["state"].selection).get(
                q.state, q.state),
        })
    return {
        "ok": True,
        "count": len(rows),
        "rows": rows,
    }
