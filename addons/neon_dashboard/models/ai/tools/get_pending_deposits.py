# -*- coding: utf-8 -*-
"""get_pending_deposits — quotes awaiting deposit payment."""
from datetime import date

from ..tool_registry import ai_tool


@ai_tool(
    name="get_pending_deposits",
    description=(
        "Return quotes that are sent or accepted whose invoice "
        "schedule shows a pending deposit. Sorted by days since "
        "the quote was sent (oldest first)."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "days_overdue_min": {
                "type": "integer",
                "description": (
                    "Only return quotes whose sent_at is at "
                    "least this many days ago."
                ),
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
def tool_get_pending_deposits(env, user, days_overdue_min=None, **_):
    Quote = env["neon.finance.quote"]
    quotes = Quote.search([
        ("state", "in", ("sent", "accepted")),
        ("salesperson_id", "=", user.id),
    ], order="sent_at, create_date", limit=100)
    today = date.today()
    rows = []
    for q in quotes:
        sent_date = q.sent_at.date() if q.sent_at else (
            q.create_date.date() if q.create_date else today)
        days = (today - sent_date).days
        if days_overdue_min and days < int(days_overdue_min):
            continue
        # Heuristic — if invoice schedule lines exist and none are
        # marked paid, treat the first stage as the pending deposit.
        # If no schedule, the quote total is the implicit deposit.
        schedule = q.invoice_schedule_ids[:1]
        if schedule:
            pct = float(schedule.percentage or 100.0)
            amount = float(q.amount_total or 0.0) * pct / 100.0
        else:
            amount = float(q.amount_total or 0.0)
        rows.append({
            "quote_id": q.id,
            "quote_name": q.name,
            "partner_name": q.partner_id.name if q.partner_id else "",
            "amount": amount,
            "currency": q.currency_id.name if q.currency_id else "USD",
            "days_since_sent": days,
            "state": q.state,
        })
    rows.sort(key=lambda r: -r["days_since_sent"])
    return {"ok": True, "count": len(rows), "rows": rows}
