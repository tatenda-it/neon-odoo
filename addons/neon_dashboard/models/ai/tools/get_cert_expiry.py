# -*- coding: utf-8 -*-
"""get_cert_expiry — staff certifications expiring soon."""
from datetime import date, timedelta

from ..tool_registry import ai_tool


@ai_tool(
    name="get_cert_expiry",
    description=(
        "Return active certifications whose date_expires is "
        "within the next N days. Used for compliance + crew "
        "planning."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "description": (
                    "Days from today to look ahead. Default 30."
                ),
            },
        },
    },
    category="read",
)
def tool_get_cert_expiry(env, user, days_ahead=None, **_):
    Cert = env["neon.training.certification"]
    today = date.today()
    horizon_days = int(days_ahead or 30)
    horizon = today + timedelta(days=horizon_days)

    certs = Cert.search([
        ("state", "=", "active"),
        ("date_expires", "!=", False),
        ("date_expires", "<=", horizon),
    ], order="date_expires")

    rows = []
    for c in certs:
        days_remaining = (c.date_expires - today).days
        type_name = (c.type_id.name if c.type_id else "")
        user_name = (c.user_id.name if c.user_id else "")
        rows.append({
            "id": c.id,
            "user_id": c.user_id.id if c.user_id else False,
            "user_name": user_name,
            "cert_name": type_name,
            "expires_on": c.date_expires.isoformat(),
            "days_remaining": days_remaining,
            "is_overdue": days_remaining < 0,
        })
    return {
        "ok": True,
        "days_ahead": horizon_days,
        "count": len(rows),
        "rows": rows,
    }
