# -*- coding: utf-8 -*-
"""get_dashboard_summary — current dashboard KPI values."""
from ..tool_registry import ai_tool


@ai_tool(
    name="get_dashboard_summary",
    description=(
        "Return current dashboard KPI values for context-aware "
        "follow-up questions (cash, AR overdue, jobs today, "
        "jobs week, pipeline, leads, forecast)."
    ),
    params_schema={
        "type": "object",
        "properties": {},
    },
    category="read",
)
def tool_get_dashboard_summary(env, user, **_):
    Dashboard = env["neon.dashboard"]
    # Dashboard methods are @api.model on the virtual model; we
    # call them via sudo() so the env user doesn't need direct
    # access. They internally read aggregated metrics that the
    # current sales user wouldn't see at row level.
    D = Dashboard.sudo()
    out = {}
    # Each KPI method returns a dict {value, ...meta}. We surface
    # just the headline number + display.
    for key in (
        "_kpi_cash_on_hand",
        "_kpi_ar_overdue",
        "_kpi_jobs_today",
        "_kpi_jobs_week",
        "_kpi_pipeline",
        "_kpi_new_leads",
        "_kpi_forecast",
    ):
        try:
            data = getattr(D, key)()
        except Exception as exc:  # noqa: BLE001
            data = {"error": str(exc)}
        out[key.lstrip("_")] = data
    return {
        "ok": True,
        "kpi": out,
        "user": user.name,
    }
