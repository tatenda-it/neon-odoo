# -*- coding: utf-8 -*-
"""log_lead — propose a crm.lead create. Confirmation-gated."""
from ..tool_registry import ai_tool, register_executor


_SALES_GROUPS = [
    "neon_jobs.group_neon_jobs_user",
    "neon_jobs.group_neon_jobs_manager",
]


@ai_tool(
    name="log_lead",
    description=(
        "PROPOSE creating a new sales lead in the CRM. This tool does "
        "NOT create the lead -- it returns a structured proposal and "
        "the user must confirm via the confirmation card. Use this "
        "when the user says 'log a lead', 'create a lead', 'add a new "
        "deal', or similar. Always name the lead clearly (include "
        "company + product so it is searchable later)."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Lead title -- include company + product, "
                    "e.g. 'Acme Corp -- LED wall'."),
            },
            "partner_name": {
                "type": "string",
                "description": (
                    "Customer / company name. If it matches an "
                    "existing res.partner exactly, the proposal links "
                    "to that partner; otherwise stays as free text."),
            },
            "contact_name": {
                "type": "string",
                "description": "Primary contact person at the customer.",
            },
            "description": {
                "type": "string",
                "description": (
                    "Free-text notes / brief from the user about what "
                    "the lead wants. Persisted as the lead description."),
            },
            "expected_revenue": {
                "type": "number",
                "description": (
                    "Estimated deal value in the given currency. "
                    "Negative values are rejected at propose time."),
            },
            "currency": {
                "type": "string",
                "description": (
                    "Currency code (USD or ZiG). Defaults to USD."),
            },
        },
        "required": ["name"],
    },
    category="write",
    requires_confirmation=True,
    groups=_SALES_GROUPS,
)
def propose_log_lead(env, user, name=None, partner_name=None,
                     contact_name=None, description=None,
                     expected_revenue=None, currency=None, **_):
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "Lead name is required."}
    if expected_revenue is not None:
        try:
            expected_revenue = float(expected_revenue)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error": "expected_revenue must be a number.",
            }
        if expected_revenue < 0:
            return {
                "ok": False,
                "error": "expected_revenue cannot be negative.",
            }

    partner_id = None
    resolved_partner_name = (partner_name or "").strip() or None
    if resolved_partner_name:
        partner = env["res.partner"].search(
            [("name", "=", resolved_partner_name),
             ("is_company", "=", True)], limit=1)
        if not partner:
            partner = env["res.partner"].search(
                [("name", "=", resolved_partner_name)], limit=1)
        if partner:
            partner_id = partner.id
            resolved_partner_name = partner.name

    currency_code = (currency or "USD").upper()
    currency_rec = env["res.currency"].search(
        [("name", "=", currency_code)], limit=1)
    currency_id = currency_rec.id if currency_rec else None

    after_state = {
        "name": name,
        "user_id": user.id,
        "user_name": user.name,
    }
    if partner_id:
        after_state["partner_id"] = partner_id
    if resolved_partner_name:
        after_state["partner_name"] = resolved_partner_name
    if contact_name:
        after_state["contact_name"] = contact_name
    if description:
        after_state["description"] = description
    if expected_revenue is not None:
        after_state["expected_revenue"] = float(expected_revenue)
    if currency_id:
        after_state["currency_id"] = currency_id
        after_state["currency"] = currency_code

    summary_bits = ["Create lead '{n}'".format(n=name)]
    if resolved_partner_name:
        summary_bits.append("for {p}".format(p=resolved_partner_name))
    if expected_revenue is not None:
        summary_bits.append(
            "({c} {v:,.0f})".format(
                c=currency_code, v=float(expected_revenue)))
    summary_bits.append("assigned to {u}".format(u=user.name))
    human_summary = " ".join(summary_bits)

    return {
        "ok": True,
        "is_proposal": True,
        "action_type": "log_lead",
        "target_model": "crm.lead",
        "target_id": None,
        "params": {
            "name": name,
            "partner_id": partner_id,
            "partner_name": resolved_partner_name,
            "contact_name": contact_name or None,
            "description": description or None,
            "expected_revenue": (float(expected_revenue)
                                  if expected_revenue is not None
                                  else None),
            "currency_id": currency_id,
        },
        "human_summary": human_summary,
        "before_state": None,
        "after_state": after_state,
    }


def execute_log_lead(env, user, params):
    """Create the crm.lead under the calling user's identity.
    Caller already validated user_can_call + ACL on crm.lead create."""
    vals = {
        "name": params["name"],
        "user_id": user.id,
        "type": "lead",
    }
    if params.get("partner_id"):
        vals["partner_id"] = int(params["partner_id"])
    elif params.get("partner_name"):
        vals["partner_name"] = params["partner_name"]
    if params.get("contact_name"):
        vals["contact_name"] = params["contact_name"]
    if params.get("description"):
        vals["description"] = params["description"]
    if params.get("expected_revenue") is not None:
        vals["expected_revenue"] = float(params["expected_revenue"])
    if params.get("currency_id"):
        vals["company_currency"] = int(params["currency_id"])

    lead = env["crm.lead"].create(vals)
    return {
        "created_target_id": lead.id,
        "target_model": "crm.lead",
        "target_name": lead.name,
    }


register_executor("log_lead", execute_log_lead)
