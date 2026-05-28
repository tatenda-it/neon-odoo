# -*- coding: utf-8 -*-
"""get_readiness_gates — readiness blocking analysis per upcoming job."""
from datetime import date, timedelta

from ..tool_registry import ai_tool


# Phase 4 readiness dimensions per neon_jobs/models/commercial_event_job.py
# _READINESS_DIMENSIONS table — six weighted axes. We surface the ones
# below thresholds as "blocking gates" for the lead-tech view.
_DIM_FIELDS = (
    ("finance", "readiness_dimension_finance"),
    ("equipment", "readiness_dimension_equipment"),
    ("crew", "readiness_dimension_crew"),
    ("schedule_venue", "readiness_dimension_schedule_venue"),
    ("checklist", "readiness_dimension_checklist"),
    ("risk", "readiness_dimension_risk"),
)
_BLOCK_THRESHOLD = 0.7   # below 70% surfaces as a blocking gate


@ai_tool(
    name="get_readiness_gates",
    description=(
        "Return upcoming event jobs in the next N days whose "
        "readiness dimensions are below threshold, listing each "
        "failing gate by name plus crew gap and pending "
        "equipment counts. Use this to triage what needs "
        "attention before jobs ship."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "description": (
                    "Days from today to scan. Default 7."
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
def tool_get_readiness_gates(env, user, days_ahead=None, **_):
    EventJob = env["commercial.event.job"]
    today = date.today()
    horizon = today + timedelta(days=int(days_ahead or 7))
    jobs = EventJob.search([
        ("event_date", ">=", today),
        ("event_date", "<=", horizon),
        ("state", "not in", ("cancelled", "released", "completed")),
    ], order="event_date asc")

    rows = []
    for j in jobs:
        blocking = []
        for label, fname in _DIM_FIELDS:
            value = float(getattr(j, fname, 0.0) or 0.0)
            # Dimensions are stored as percentages (0-100) per
            # neon_jobs._compute_readiness_score. Convert to 0-1.
            if value > 1.5:
                value = value / 100.0
            if value < _BLOCK_THRESHOLD:
                blocking.append({
                    "name": label,
                    "score_pct": round(value * 100.0, 1),
                })
        crew_total = int(getattr(j, "crew_total_count", 0) or 0)
        crew_confirmed = int(getattr(j, "crew_confirmed_count", 0)
                              or 0)
        crew_gap = max(0, crew_total - crew_confirmed)
        # Equipment pending = lines not in 'fulfilled' state.
        pending_count = 0
        try:
            for line in j.equipment_line_ids:
                if (line.state or "") not in ("fulfilled", "cancelled"):
                    pending_count += 1
        except Exception:  # noqa: BLE001
            pending_count = 0
        if not blocking and crew_gap == 0 and pending_count == 0:
            # Job is clean — skip from result so list stays focused
            # on the problem set.
            continue
        rows.append({
            "event_job_id": j.id,
            "ref": j.name or "",
            "partner_name": (j.partner_id.name
                              if j.partner_id else ""),
            "event_date": j.event_date.isoformat(),
            "days_until": (j.event_date - today).days,
            "blocking_gates": blocking,
            "crew_gap": crew_gap,
            "equipment_pending": pending_count,
            "readiness_state": getattr(j, "readiness_state", ""),
        })
    return {
        "ok": True,
        "count": len(rows),
        "days_ahead": int(days_ahead or 7),
        "rows": rows,
    }
