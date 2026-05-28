# -*- coding: utf-8 -*-
"""get_crew_availability — internal users free in a date window."""
from datetime import date, timedelta

from ..tool_registry import ai_tool


@ai_tool(
    name="get_crew_availability",
    description=(
        "Return internal crew users who have any conflicting job "
        "assignments in a date window, along with their role. The "
        "absence of a user from this list means they are free."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "description": "YYYY-MM-DD window start.",
            },
            "end_date": {
                "type": "string",
                "description": "YYYY-MM-DD window end.",
            },
            "role_filter": {
                "type": "string",
                "description": (
                    "Optional role filter: lead_tech, tech, "
                    "runner, driver, other."
                ),
            },
        },
        "required": ["start_date", "end_date"],
    },
    category="read",
)
def tool_get_crew_availability(env, user, start_date=None,
                                end_date=None, role_filter=None,
                                **_):
    if not (start_date and end_date):
        return {"ok": False, "error": "start_date + end_date required"}
    try:
        start = date.fromisoformat(str(start_date))
        end = date.fromisoformat(str(end_date))
    except ValueError as exc:
        return {"ok": False, "error": f"Bad date format: {exc}"}

    Crew = env["commercial.job.crew"]
    EventJob = env["commercial.event.job"]
    Users = env["res.users"]

    # All event_jobs whose date falls inside the requested window.
    jobs = EventJob.search([
        ("event_date", ">=", start),
        ("event_date", "<=", end),
        ("state", "not in", ("cancelled", "released")),
    ])
    job_ids = jobs.ids
    crew_domain = [
        ("job_id.event_date", ">=", start),
        ("job_id.event_date", "<=", end),
        ("user_id", "!=", False),
        ("state", "!=", "declined"),
    ]
    if role_filter:
        crew_domain.append(("role", "=", role_filter))

    assignments = Crew.search(crew_domain)
    by_user = {}
    for a in assignments:
        uid = a.user_id.id
        info = by_user.setdefault(uid, {
            "user_id": uid,
            "name": a.user_id.name,
            "role": a.role,
            "conflicting_jobs": [],
        })
        info["conflicting_jobs"].append({
            "job_id": a.job_id.id,
            "job_name": a.job_id.name or "",
            "event_date": (a.job_id.event_date.isoformat()
                           if a.job_id.event_date else ""),
            "state": a.state,
        })

    # Optionally include the free users too (those with crew role
    # but no conflict in the window) so the AI can phrase "X, Y, Z
    # are free". Use the existing crew table to scope to people who
    # ARE crew (set of user_ids who appear at all in commercial.
    # job.crew, not just in the window).
    all_crew_user_ids = set(Crew.search([("user_id", "!=", False)]).
                            mapped("user_id").ids)
    busy_ids = set(by_user.keys())
    free_ids = list(all_crew_user_ids - busy_ids)[:50]
    free = []
    if free_ids:
        for u in Users.browse(free_ids):
            if not u.active:
                continue
            free.append({"user_id": u.id, "name": u.name})

    return {
        "ok": True,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "role_filter": role_filter or "",
        "busy": list(by_user.values()),
        "free": free,
        "busy_count": len(by_user),
        "free_count": len(free),
    }
