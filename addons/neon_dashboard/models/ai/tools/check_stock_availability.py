# -*- coding: utf-8 -*-
"""check_stock_availability — units free in a date window."""
from datetime import date, datetime

from ..tool_registry import ai_tool


@ai_tool(
    name="check_stock_availability",
    description=(
        "Check how many units of a given equipment category are "
        "available between two dates. Reports total stock, units "
        "currently held by other event_jobs in the window, and "
        "remaining available."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "equipment_category": {
                "type": "string",
                "description": (
                    "Category name (e.g. 'Sound', 'Lighting', "
                    "'Visual'). Case-insensitive contains match."
                ),
            },
            "start_date": {
                "type": "string",
                "description": "YYYY-MM-DD start of the window.",
            },
            "end_date": {
                "type": "string",
                "description": "YYYY-MM-DD end of the window.",
            },
        },
        "required": ["equipment_category", "start_date", "end_date"],
    },
    category="read",
    groups=[
        "neon_jobs.group_neon_jobs_user",
        "neon_jobs.group_neon_jobs_crew_leader",
        "neon_jobs.group_neon_jobs_manager",
    ],
)
def tool_check_stock_availability(env, user, equipment_category=None,
                                   start_date=None, end_date=None,
                                   **_):
    if not (equipment_category and start_date and end_date):
        return {
            "ok": False,
            "error": ("equipment_category, start_date, end_date "
                      "are all required"),
        }
    try:
        start = date.fromisoformat(str(start_date))
        end = date.fromisoformat(str(end_date))
    except ValueError as exc:
        return {"ok": False, "error": f"Bad date format: {exc}"}

    Cat = env["neon.equipment.category"]
    Unit = env["neon.equipment.unit"]
    EqLine = env["commercial.event.job.equipment.line"]

    cat = Cat.search(
        [("name", "=ilike", f"%{equipment_category}%")], limit=1)
    if not cat:
        return {
            "ok": False,
            "error": (
                f"No equipment category matches "
                f"{equipment_category!r}."
            ),
        }

    # Total units in the category whose state is "available-ish".
    total_units = Unit.search_count([
        ("equipment_category_id", "=", cat.id),
        ("state", "not in", ("decommissioned", "damaged",
                             "maintenance")),
    ])

    # Find event_job equipment lines for this category whose event
    # window overlaps the requested window.
    conflicting_lines = EqLine.search([
        ("category_id", "=", cat.id),
        ("state", "not in", ("cancelled",)),
        ("event_job_id.event_date", "<=", end),
    ])
    conflicts = []
    held = 0
    for line in conflicting_lines:
        ej = line.event_job_id
        ej_date = ej.event_date if ej else None
        if not ej_date or ej_date < start:
            continue
        qty = int(line.quantity_planned or 0)
        held += qty
        conflicts.append({
            "event_job_id": ej.id,
            "event_job_name": ej.name or "",
            "event_date": ej_date.isoformat(),
            "qty_held": qty,
        })
    available = max(0, total_units - held)
    return {
        "ok": True,
        "category": cat.name,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "total_units": total_units,
        "held_units": held,
        "available_count": available,
        "conflicting_jobs": conflicts,
    }
