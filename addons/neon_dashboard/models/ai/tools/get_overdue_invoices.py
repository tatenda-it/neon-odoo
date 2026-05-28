# -*- coding: utf-8 -*-
"""get_overdue_invoices — posted invoices past their due date."""
from datetime import date

from ..tool_registry import ai_tool


@ai_tool(
    name="get_overdue_invoices",
    description=(
        "Return customer invoices that are posted and unpaid or "
        "partially paid, whose due date has passed. Useful for "
        "bookkeeper AR follow-ups."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "days_overdue_min": {
                "type": "integer",
                "description": (
                    "Only include invoices whose due date was at "
                    "least this many days ago. Default 0."
                ),
            },
            "currency_filter": {
                "type": "string",
                "description": (
                    "Optional 'USD' or 'ZWG' (matches res.currency "
                    "name)."
                ),
            },
        },
    },
    category="read",
    groups=[
        "neon_core.group_neon_bookkeeper",
        "neon_jobs.group_neon_jobs_manager",
    ],
)
def tool_get_overdue_invoices(env, user, days_overdue_min=None,
                               currency_filter=None, **_):
    AccountMove = env["account.move"]
    today = date.today()
    domain = [
        ("move_type", "=", "out_invoice"),
        ("state", "=", "posted"),
        ("payment_state", "in", ("not_paid", "partial")),
        ("invoice_date_due", "!=", False),
        ("invoice_date_due", "<", today),
    ]
    invoices = AccountMove.search(
        domain, order="invoice_date_due", limit=100)
    rows = []
    for inv in invoices:
        days_overdue = (today - inv.invoice_date_due).days
        if days_overdue_min and days_overdue < int(days_overdue_min):
            continue
        currency_name = (inv.currency_id.name
                         if inv.currency_id else "USD")
        if currency_filter and currency_name != currency_filter:
            continue
        rows.append({
            "invoice_id": inv.id,
            "invoice_ref": inv.name or "",
            "partner_name": (inv.partner_id.name
                              if inv.partner_id else ""),
            "amount": float(inv.amount_residual or
                             inv.amount_total or 0.0),
            "amount_total": float(inv.amount_total or 0.0),
            "currency": currency_name,
            "days_overdue": days_overdue,
            "due_date": inv.invoice_date_due.isoformat(),
            "payment_term": (inv.invoice_payment_term_id.name
                              if inv.invoice_payment_term_id else ""),
        })
    return {"ok": True, "count": len(rows), "rows": rows}
