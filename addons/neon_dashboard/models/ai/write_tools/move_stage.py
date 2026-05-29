# -*- coding: utf-8 -*-
"""move_stage — propose moving a crm.lead to a target stage."""
from ..tool_registry import ai_tool, register_executor


_SALES_GROUPS = [
    "neon_jobs.group_neon_jobs_user",
    "neon_jobs.group_neon_jobs_manager",
]


def _stage_label(stage):
    """crm.stage.name is a JSONB translation field. Pull the plain
    string for display + matching."""
    if not stage:
        return ""
    name = stage.name or ""
    if isinstance(name, dict):
        # Translation dict -- prefer en_US, then any value.
        return name.get("en_US") or next(iter(name.values()), "")
    return str(name)


def _resolve_lead(env, identifier):
    """Resolve a lead identifier (id-as-string or fuzzy name match).
    Returns (recordset, message). If multiple match by name, returns
    the recordset for the caller to disambiguate."""
    identifier = (identifier or "").strip()
    if not identifier:
        return (env["crm.lead"].browse(), "Lead identifier is required.")
    if identifier.isdigit():
        rec = env["crm.lead"].browse(int(identifier))
        if rec.exists():
            return (rec, "")
    matches = env["crm.lead"].search(
        [("name", "ilike", identifier),
         ("active", "=", True)], limit=10)
    if not matches:
        return (matches, "No lead matching {!r}.".format(identifier))
    return (matches, "")


def _resolve_stage(env, target_stage):
    """Fuzzy-match a stage name. Returns (recordset, message). If no
    match: returns empty recordset + a message listing all valid
    stages so the caller can surface to the user."""
    target_stage = (target_stage or "").strip()
    all_stages = env["crm.stage"].search([], order="sequence, id")
    if not target_stage:
        return (env["crm.stage"].browse(),
                "Target stage is required. Valid stages: {}".format(
                    ", ".join(_stage_label(s) for s in all_stages)))
    needle = target_stage.lower()
    exact = [s for s in all_stages
             if _stage_label(s).lower() == needle]
    if exact:
        return (exact[0], "")
    partial = [s for s in all_stages
               if needle in _stage_label(s).lower()]
    if len(partial) == 1:
        return (partial[0], "")
    if len(partial) > 1:
        labels = ", ".join(_stage_label(s) for s in partial)
        return (env["crm.stage"].browse(),
                "Ambiguous stage {!r}. Did you mean one of: {}?".format(
                    target_stage, labels))
    labels = ", ".join(_stage_label(s) for s in all_stages)
    return (env["crm.stage"].browse(),
            "No stage matches {!r}. Valid stages: {}".format(
                target_stage, labels))


@ai_tool(
    name="move_stage",
    description=(
        "PROPOSE moving a CRM lead / opportunity to a different "
        "pipeline stage. Returns a confirmation proposal -- the "
        "stage is NOT changed until the user confirms. Use when the "
        "user says 'move X to Y', 'advance the X deal', or similar. "
        "If the lead name is ambiguous, list candidates rather than "
        "guessing."),
    params_schema={
        "type": "object",
        "properties": {
            "lead_identifier": {
                "type": "string",
                "description": (
                    "Lead name or numeric id. Exact-id wins; "
                    "otherwise fuzzy-match by name."),
            },
            "target_stage": {
                "type": "string",
                "description": (
                    "Stage name. Fuzzy-matched against crm.stage "
                    "(case-insensitive substring). If multiple match, "
                    "the tool returns the candidates."),
            },
        },
        "required": ["lead_identifier", "target_stage"],
    },
    category="write",
    requires_confirmation=True,
    groups=_SALES_GROUPS,
)
def propose_move_stage(env, user, lead_identifier=None,
                       target_stage=None, **_):
    leads, lead_msg = _resolve_lead(env, lead_identifier)
    if lead_msg:
        return {"ok": False, "error": lead_msg}
    if len(leads) > 1:
        candidates = [
            {"id": l.id, "name": l.name,
             "stage": _stage_label(l.stage_id)}
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
    stage, stage_msg = _resolve_stage(env, target_stage)
    if stage_msg:
        return {"ok": False, "error": stage_msg}

    before_stage_name = _stage_label(lead.stage_id)
    after_stage_name = _stage_label(stage)
    if lead.stage_id.id == stage.id:
        return {
            "ok": False,
            "error": (
                "{n} is already in stage '{s}'."
            ).format(n=lead.name, s=after_stage_name),
        }

    human_summary = (
        "Move lead '{n}' from '{a}' to '{b}'"
    ).format(n=lead.name, a=before_stage_name or "(none)",
             b=after_stage_name)

    return {
        "ok": True,
        "is_proposal": True,
        "action_type": "move_stage",
        "target_model": "crm.lead",
        "target_id": lead.id,
        "params": {
            "lead_id": lead.id,
            "stage_id": stage.id,
            "lead_name": lead.name,
            "before_stage_name": before_stage_name,
            "after_stage_name": after_stage_name,
        },
        "human_summary": human_summary,
        "before_state": {"stage": before_stage_name},
        "after_state": {"stage": after_stage_name},
    }


def execute_move_stage(env, user, params):
    lead = env["crm.lead"].browse(int(params["lead_id"]))
    if not lead.exists():
        raise ValueError("Lead {} no longer exists.".format(
            params["lead_id"]))
    lead.write({"stage_id": int(params["stage_id"])})
    return {
        "created_target_id": 0,
        "target_model": "crm.lead",
        "target_id": lead.id,
        "target_name": lead.name,
    }


register_executor("move_stage", execute_move_stage)
