# -*- coding: utf-8 -*-
"""get_jobs_this_week — upcoming event jobs in the next 7 days."""
from datetime import date, timedelta

from ..tool_registry import ai_tool


@ai_tool(
    name="get_jobs_this_week",
    description=(
        "Return event jobs scheduled in the next 7 days (today "
        "through today+7). Each row carries crew confirmation "
        "status and readiness state."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "state_filter": {
                "type": "string",
                "description": (
                    "Optional state filter (e.g. 'planning', "
                    "'ready_for_dispatch', 'in_progress')."
                ),
            },
        },
    },
    category="read",
    groups=[
        "neon_jobs.group_neon_jobs_crew_leader",
        "neon_jobs.group_neon_jobs_manager",
    ],
)
def tool_get_jobs_this_week(env, user, state_filter=None, **_):
    EventJob = env["commercial.event.job"]
    today = date.today()
    end = today + timedelta(days=7)
    domain = [
        ("event_date", ">=", today),
        ("event_date", "<=", end),
        ("state", "not in", ("cancelled", "released")),
    ]
    if state_filter:
        domain.append(("state", "=", state_filter))
    jobs = EventJob.search(domain, order="event_date asc, id asc")
    rows = []
    for j in jobs:
        rows.append({
            "event_job_id": j.id,
            "ref": j.name or "",
            "partner_name": (j.partner_id.name
                              if j.partner_id else ""),
            "venue_name": (j.venue_id.name if j.venue_id else ""),
            "event_date": j.event_date.isoformat(),
            "days_until": (j.event_date - today).days,
            "state": j.state,
            "state_label": dict(
                j._fields["state"].selection
            ).get(j.state, j.state),
            "crew_required": int(getattr(j, "crew_total_count", 0)
                                  or 0),
            "crew_confirmed": int(getattr(j, "crew_confirmed_count", 0)
                                    or 0),
            "readiness_state": getattr(j, "readiness_state", ""),
            "readiness_score": float(
                getattr(j, "readiness_score", 0.0) or 0.0),
        })
    return {
        "ok": True,
        "count": len(rows),
        "window_start": today.isoformat(),
        "window_end": end.isoformat(),
        "rows": rows,
    }
