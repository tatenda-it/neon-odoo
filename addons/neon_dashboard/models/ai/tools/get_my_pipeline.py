# -*- coding: utf-8 -*-
"""get_my_pipeline — crm.lead summary for the active user."""
from ..tool_registry import ai_tool


@ai_tool(
    name="get_my_pipeline",
    description=(
        "Return CRM leads owned by the current sales user, "
        "grouped by stage. Use for 'where is my pipeline' or "
        "'what stage is X in'."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "stage_filter": {
                "type": "string",
                "description": (
                    "Optional stage name (case-insensitive "
                    "contains) to scope the result."
                ),
            },
        },
    },
    category="read",
    # ⚠️ DECISION (M12.1.1, marker inline): use the
    # neon_core.group_neon_sales_rep cross-module tier rather than
    # the broader neon_jobs.group_neon_jobs_user, because the
    # bookkeeper tier implies group_neon_jobs_user (cascades up the
    # neon_core meta-group chain). Sales-only tools must gate on
    # the more specific neon_core.group_neon_sales_rep.
    groups=[
        "neon_core.group_neon_sales_rep",
        "neon_jobs.group_neon_jobs_manager",
    ],
)
def tool_get_my_pipeline(env, user, stage_filter=None, **_):
    Lead = env["crm.lead"]
    domain = [
        ("user_id", "=", user.id),
        ("active", "=", True),
        ("probability", "<", 100),  # exclude closed-won/closed-lost
        ("probability", ">", 0),
    ]
    if stage_filter:
        domain.append(("stage_id.name", "ilike", stage_filter))
    leads = Lead.search(domain, order="expected_revenue desc", limit=200)

    by_stage = {}
    for lead in leads:
        stage = lead.stage_id.name if lead.stage_id else "(none)"
        bucket = by_stage.setdefault(stage, {
            "stage": stage,
            "count": 0,
            "expected_revenue_total": 0.0,
            "leads": [],
        })
        bucket["count"] += 1
        bucket["expected_revenue_total"] += float(lead.expected_revenue or 0)
        bucket["leads"].append({
            "id": lead.id,
            "name": lead.name,
            "partner_name": (lead.partner_id.name
                             if lead.partner_id else ""),
            "expected_revenue": float(lead.expected_revenue or 0),
            "probability": float(lead.probability or 0),
        })

    stages = sorted(
        by_stage.values(),
        key=lambda b: -b["expected_revenue_total"],
    )
    return {
        "ok": True,
        "stage_filter": stage_filter or "",
        "total_count": len(leads),
        "stages": stages,
    }
