# -*- coding: utf-8 -*-
"""post_chatter_note — propose posting a chatter note on a record."""
import re

from odoo.exceptions import AccessError

from ..tool_registry import ai_tool, register_executor


_ALL_DASHBOARD_GROUPS = [
    "neon_jobs.group_neon_jobs_user",
    "neon_jobs.group_neon_jobs_manager",
    "neon_jobs.group_neon_jobs_crew_leader",
    "neon_core.group_neon_bookkeeper",
]


# Allow-list of models the tool can post to. Each entry: model name +
# the user-friendly noun the LLM uses to refer to the record.
_TARGET_MODELS = [
    ("crm.lead", "lead"),
    ("commercial.job", "job"),
    ("commercial.event.job", "event"),
    ("res.partner", "partner"),
    ("neon.finance.quote", "quote"),
]


def _resolve_target(env, user, target_ref):
    """Parse 'noun identifier' (e.g. 'lead Acme Corp', 'job JOB-000009',
    'partner Rainbow Towers'). Returns (record, message). Enforces the
    calling user's read ACL on the resolved record so the tool cannot
    be used to fish for records the user can't see."""
    target_ref = (target_ref or "").strip()
    if not target_ref:
        return (None, "target_ref is required.")
    noun_match = re.match(r"^([a-zA-Z]+)\s+(.+)$", target_ref)
    candidates = list(_TARGET_MODELS)
    if noun_match:
        noun = noun_match.group(1).lower()
        identifier = noun_match.group(2).strip()
        # Filter the allow-list to the matched noun if possible.
        narrowed = [(m, n) for (m, n) in candidates if n == noun]
        if narrowed:
            candidates = narrowed
    else:
        identifier = target_ref

    for model_name, _noun in candidates:
        Model = env[model_name].sudo()
        rec = None
        if identifier.isdigit():
            rec = Model.browse(int(identifier))
            if not rec.exists():
                rec = None
        if not rec:
            field = "name"
            if model_name == "commercial.job":
                field = "job_code"
            try:
                hits = Model.search(
                    [(field, "=", identifier)], limit=2)
                if not hits:
                    hits = Model.search(
                        [(field, "ilike", identifier)], limit=2)
            except (KeyError, ValueError):
                hits = Model.browse()
            if len(hits) == 1:
                rec = hits
            elif len(hits) > 1:
                names = ", ".join(h.display_name for h in hits[:5])
                return (None, (
                    "Multiple {m}s match {r!r}: {n}. Please be more "
                    "specific."
                ).format(m=_noun, r=identifier, n=names))
        if rec:
            # ACL re-check under the CALLING user (not sudo). If the
            # user can't read this record, refuse to post.
            try:
                rec.with_user(user).check_access_rights("read")
                rec.with_user(user).check_access_rule("read")
            except AccessError:
                return (None, (
                    "You don't have access to {m} {r}. Pick a record "
                    "you can see."
                ).format(m=_noun, r=identifier))
            return (rec, "")
    return (None, "No matching record found for {!r}.".format(target_ref))


@ai_tool(
    name="post_chatter_note",
    description=(
        "PROPOSE posting an internal chatter note on a CRM lead, "
        "commercial job, event job, partner, or quote. The note is "
        "NOT posted until the user confirms. Use when the user says "
        "'post a note on X', 'add a comment to X', 'leave an update "
        "on X'. Always include both the target record and the note "
        "text."),
    params_schema={
        "type": "object",
        "properties": {
            "target_ref": {
                "type": "string",
                "description": (
                    "Record reference, e.g. 'lead Acme Corp', "
                    "'job JOB-000009', 'partner Rainbow Towers', "
                    "'event Wedding 2026-06-12', 'quote Q/0001'. "
                    "The leading noun narrows the search to that "
                    "model; without a noun, the tool searches across "
                    "the allow-list."),
            },
            "note_text": {
                "type": "string",
                "description": "The body of the chatter note.",
            },
        },
        "required": ["target_ref", "note_text"],
    },
    category="write",
    requires_confirmation=True,
    groups=_ALL_DASHBOARD_GROUPS,
)
def propose_post_chatter_note(env, user, target_ref=None,
                              note_text=None, **_):
    note_text = (note_text or "").strip()
    if not note_text:
        return {"ok": False, "error": "note_text is required."}
    rec, msg = _resolve_target(env, user, target_ref)
    if msg:
        return {"ok": False, "error": msg}

    preview = note_text if len(note_text) <= 140 else (
        note_text[:137] + "...")
    human_summary = (
        "Post note on {m} '{n}': {p}"
    ).format(m=rec._name.split(".")[-1], n=rec.display_name, p=preview)

    return {
        "ok": True,
        "is_proposal": True,
        "action_type": "post_chatter_note",
        "target_model": rec._name,
        "target_id": rec.id,
        "params": {
            "target_model": rec._name,
            "target_id": rec.id,
            "target_name": rec.display_name,
            "note_text": note_text,
        },
        "human_summary": human_summary,
        "before_state": None,
        "after_state": {
            "target": rec.display_name,
            "note_preview": preview,
        },
    }


def execute_post_chatter_note(env, user, params):
    Model = env[params["target_model"]]
    rec = Model.browse(int(params["target_id"]))
    if not rec.exists():
        raise ValueError("Record {}:{} no longer exists.".format(
            params["target_model"], params["target_id"]))
    # Re-check ACL at execute time -- permissions may have changed
    # since propose.
    rec.with_user(user).check_access_rights("read")
    rec.with_user(user).check_access_rule("read")
    rec.message_post(
        body=params["note_text"], message_type="comment")
    return {
        "created_target_id": 0,
        "target_model": params["target_model"],
        "target_id": rec.id,
        "target_name": rec.display_name,
    }


register_executor("post_chatter_note", execute_post_chatter_note)
