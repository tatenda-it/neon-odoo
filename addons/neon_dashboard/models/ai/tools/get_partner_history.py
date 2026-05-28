# -*- coding: utf-8 -*-
"""get_partner_history — past quotes + event_jobs for a partner."""
from ..tool_registry import ai_tool


@ai_tool(
    name="get_partner_history",
    description=(
        "Return up to 5 recent quotes and 5 recent event_jobs "
        "for a partner, plus their active master contract if "
        "any. Look up by partner_id (preferred) or partner_name "
        "substring."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "partner_id": {
                "type": "integer",
                "description": "res.partner ID (preferred).",
            },
            "partner_name": {
                "type": "string",
                "description": (
                    "Case-insensitive partner name match. Used "
                    "only when partner_id is not provided."
                ),
            },
        },
    },
    category="read",
    groups=[
        "neon_jobs.group_neon_jobs_user",
        "neon_core.group_neon_bookkeeper",
        "neon_jobs.group_neon_jobs_manager",
    ],
)
def tool_get_partner_history(env, user, partner_id=None,
                              partner_name=None, **_):
    Partner = env["res.partner"]
    Quote = env["neon.finance.quote"]
    EventJob = env["commercial.event.job"]
    Master = env["commercial.job.master"]

    partner = None
    if partner_id:
        partner = Partner.browse(int(partner_id)).exists()
    if not partner and partner_name:
        partner = Partner.search(
            [("name", "ilike", partner_name),
             ("is_company", "=", True)],
            limit=1,
        )
    if not partner:
        return {
            "ok": False,
            "error": (
                "No partner found for partner_id="
                f"{partner_id!r} / partner_name={partner_name!r}"
            ),
        }

    quotes = Quote.search(
        [("partner_id", "=", partner.id)],
        order="create_date desc", limit=5)
    quote_rows = [{
        "id": q.id, "name": q.name,
        "state": q.state,
        "amount_total": float(q.amount_total or 0),
        "currency": q.currency_id.name if q.currency_id else "USD",
        "margin_pct": float(q.margin_pct or 0),
        "create_date": (q.create_date.isoformat()
                         if q.create_date else ""),
    } for q in quotes]

    jobs = EventJob.search(
        [("partner_id", "=", partner.id)],
        order="event_date desc", limit=5)
    job_rows = [{
        "id": j.id, "name": j.name,
        "event_date": (j.event_date.isoformat()
                       if j.event_date else ""),
        "state": j.state,
        "venue": j.venue_id.name if j.venue_id else "",
    } for j in jobs]

    masters = Master.search(
        [("partner_id", "=", partner.id), ("state", "=", "active")],
        limit=1,
    )
    master_row = None
    if masters:
        m = masters[0]
        master_row = {
            "id": m.id, "name": m.name,
            "state": m.state,
        }

    return {
        "ok": True,
        "partner": {
            "id": partner.id, "name": partner.name,
            "city": partner.city or "",
            "country": (partner.country_id.name
                        if partner.country_id else ""),
        },
        "quotes": quote_rows,
        "event_jobs": job_rows,
        "master_contract": master_row,
    }
