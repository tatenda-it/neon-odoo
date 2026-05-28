# -*- coding: utf-8 -*-
"""get_zig_rate — current ZiG <-> USD conversion + 24h change."""
from datetime import date, timedelta

from ..tool_registry import ai_tool


@ai_tool(
    name="get_zig_rate",
    description=(
        "Return the current ZiG <-> USD conversion rate (latest "
        "neon.finance.conversion.rate row), when it was last "
        "updated, and the 24-hour change percentage if a prior "
        "row exists."
    ),
    params_schema={"type": "object", "properties": {}},
    category="read",
    groups=[
        "neon_core.group_neon_bookkeeper",
        "neon_jobs.group_neon_jobs_manager",
    ],
)
def tool_get_zig_rate(env, user, **_):
    Rate = env["neon.finance.conversion.rate"]
    today = date.today()
    current = Rate.search(
        [("effective_date", "<=", today)],
        order="effective_date desc, id desc", limit=1)
    if not current:
        return {
            "ok": True,
            "current_rate": 0.0,
            "last_updated_at": "",
            "change_24h_pct": 0.0,
            "source": "",
            "note": "No conversion rate rows configured yet.",
        }
    # ⚠️ DECISION (M12.1.1, marker inline): rate field is exposed
    # as ``zig_per_usd`` (USD -> ZWG multiplier) per P6.M1 schema
    # — see neon_finance_conversion_rate.py:6-10. We return that
    # as the headline rate; consumers interpret as "1 USD = N ZiG".
    rate_value = float(getattr(current, "zig_per_usd", 0.0) or 0.0)

    # Prior row for 24h change. Use the most recent row strictly
    # before current's effective_date.
    prior = Rate.search(
        [("effective_date", "<", current.effective_date)],
        order="effective_date desc, id desc", limit=1)
    change_pct = 0.0
    if prior:
        prior_value = float(getattr(prior, "zig_per_usd", 0.0) or 0.0)
        if prior_value:
            change_pct = ((rate_value - prior_value) / prior_value
                           * 100.0)

    return {
        "ok": True,
        "current_rate": rate_value,
        "last_updated_at": current.effective_date.isoformat(),
        "change_24h_pct": round(change_pct, 2),
        "source": getattr(current, "source_note", "") or "",
        "currency_pair": "USD->ZWG",
    }
