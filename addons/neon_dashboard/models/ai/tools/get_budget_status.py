# -*- coding: utf-8 -*-
"""get_budget_status — quoted vs actual cost per event job."""
from ..tool_registry import ai_tool


@ai_tool(
    name="get_budget_status",
    description=(
        "Return event jobs whose budget consumption shows risk. "
        "For each job: quoted budget (from linked quote), actual "
        "cost (cost lines), pct consumed, and a status label "
        "(on_track | warning | breach | severe)."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "job_id_filter": {
                "type": "integer",
                "description": (
                    "Optional commercial.event.job ID to limit "
                    "the result to a single job."
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
def tool_get_budget_status(env, user, job_id_filter=None, **_):
    EventJob = env["commercial.event.job"]
    Quote = env["neon.finance.quote"]
    if job_id_filter:
        jobs = EventJob.browse(int(job_id_filter)).exists()
    else:
        jobs = EventJob.search(
            [("state", "not in", ("cancelled", "released"))],
            order="event_date desc", limit=50)

    rows = []
    for j in jobs:
        # ⚠️ DECISION (M12.1.1, marker inline): quoted budget
        # derives from the LIVE quote attached to this event_job
        # (most recent non-terminal). cost_total_usd is the stored
        # compute on event_job from neon_finance.commercial_event_job
        # extension (cost_line_ids aggregation).
        live_quote = Quote.search(
            [("event_job_id", "=", j.id),
             ("state", "in", ("approved", "sent", "accepted"))],
            order="create_date desc", limit=1)
        quoted_budget = (float(live_quote.amount_total)
                          if live_quote else 0.0)
        actual_cost = float(getattr(j, "cost_total_usd", 0.0) or 0.0)
        pct = ((actual_cost / quoted_budget * 100.0)
                if quoted_budget else 0.0)
        if pct >= 120:
            status = "severe"
        elif pct >= 100:
            status = "breach"
        elif pct >= 80:
            status = "warning"
        else:
            status = "on_track"
        rows.append({
            "job_id": j.id,
            "job_ref": j.name or "",
            "partner_name": (j.partner_id.name
                              if j.partner_id else ""),
            "event_date": (j.event_date.isoformat()
                            if j.event_date else ""),
            "quoted_budget": quoted_budget,
            "actual_cost": actual_cost,
            "pct_consumed": round(pct, 1),
            "status": status,
            "currency": (live_quote.currency_id.name
                          if live_quote and live_quote.currency_id
                          else "USD"),
        })
    # Sort so jobs of higher risk surface first.
    status_rank = {"severe": 0, "breach": 1,
                   "warning": 2, "on_track": 3}
    rows.sort(key=lambda r: (status_rank.get(r["status"], 9),
                              -r["pct_consumed"]))
    return {
        "ok": True,
        "count": len(rows),
        "rows": rows,
    }
