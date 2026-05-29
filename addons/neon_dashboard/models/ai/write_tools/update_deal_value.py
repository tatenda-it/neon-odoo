# -*- coding: utf-8 -*-
"""update_deal_value — propose changing a crm.lead.expected_revenue."""
from ..tool_registry import ai_tool, register_executor
from .move_stage import _resolve_lead  # reuse the resolver


_SALES_GROUPS = [
    "neon_jobs.group_neon_jobs_user",
    "neon_jobs.group_neon_jobs_manager",
]


@ai_tool(
    name="update_deal_value",
    description=(
        "PROPOSE updating a CRM lead's expected_revenue (deal value). "
        "The value is NOT changed until the user confirms. Use when "
        "the user says 'set the X deal to $Y', 'update the value of "
        "X to Y', or similar. Negative values are rejected."),
    params_schema={
        "type": "object",
        "properties": {
            "lead_identifier": {
                "type": "string",
                "description": (
                    "Lead name or numeric id (same resolver as "
                    "move_stage)."),
            },
            "new_value": {
                "type": "number",
                "description": (
                    "New expected_revenue. Must be >= 0. Currency "
                    "stays the lead's existing currency unless "
                    "explicitly overridden."),
            },
            "currency": {
                "type": "string",
                "description": (
                    "Optional currency code override (USD or ZiG). "
                    "If omitted, keep the lead's existing currency."),
            },
        },
        "required": ["lead_identifier", "new_value"],
    },
    category="write",
    requires_confirmation=True,
    groups=_SALES_GROUPS,
)
def propose_update_deal_value(env, user, lead_identifier=None,
                              new_value=None, currency=None, **_):
    leads, lead_msg = _resolve_lead(env, lead_identifier)
    if lead_msg:
        return {"ok": False, "error": lead_msg}
    if len(leads) > 1:
        candidates = [
            {"id": l.id, "name": l.name,
             "expected_revenue": float(l.expected_revenue or 0)}
            for l in leads[:10]
        ]
        return {
            "ok": False,
            "error": (
                "Multiple leads match {!r}. Please be more specific."
            ).format(lead_identifier),
            "candidates": candidates,
        }
    lead = leads
    try:
        new_value = float(new_value)
    except (TypeError, ValueError):
        return {"ok": False, "error": "new_value must be a number."}
    if new_value < 0:
        return {
            "ok": False,
            "error": "new_value cannot be negative.",
        }

    before_value = float(lead.expected_revenue or 0)
    existing_currency = (lead.company_currency.name
                          if lead.company_currency else "USD")
    target_currency_code = (currency or existing_currency or "USD").upper()
    target_currency_id = None
    if target_currency_code != existing_currency:
        rec = env["res.currency"].search(
            [("name", "=", target_currency_code)], limit=1)
        if rec:
            target_currency_id = rec.id

    human_summary = (
        "Update '{n}' deal value: {c} {b:,.0f} -> {c} {a:,.0f}"
    ).format(n=lead.name, c=target_currency_code,
             b=before_value, a=new_value)

    return {
        "ok": True,
        "is_proposal": True,
        "action_type": "update_deal_value",
        "target_model": "crm.lead",
        "target_id": lead.id,
        "params": {
            "lead_id": lead.id,
            "new_value": new_value,
            "currency_id": target_currency_id,
            "lead_name": lead.name,
        },
        "human_summary": human_summary,
        "before_state": {
            "expected_revenue": before_value,
            "currency": existing_currency,
        },
        "after_state": {
            "expected_revenue": new_value,
            "currency": target_currency_code,
        },
    }


def execute_update_deal_value(env, user, params):
    lead = env["crm.lead"].browse(int(params["lead_id"]))
    if not lead.exists():
        raise ValueError("Lead {} no longer exists.".format(
            params["lead_id"]))
    vals = {"expected_revenue": float(params["new_value"])}
    if params.get("currency_id"):
        vals["company_currency"] = int(params["currency_id"])
    lead.write(vals)
    return {
        "created_target_id": 0,
        "target_model": "crm.lead",
        "target_id": lead.id,
        "target_name": lead.name,
    }


register_executor("update_deal_value", execute_update_deal_value)
