# -*- coding: utf-8 -*-
"""Phase 12.2 — AI Copilot write audit + pending-action model.

`neon.finance.ai.chat.write.log` is the audit trail for the two-phase
write flow:

    propose -> (await user click) -> confirm/cancel -> execute -> log

Every phase transition writes to the SAME row (single audit lineage per
proposal, status field advances through the lifecycle).

⚠️ DECISION (M12.2, D28): the LLM never mutates data directly. A WRITE
tool returns a structured proposal; this model persists it; the UI
renders a confirmation card; only on explicit user confirm does the
backend execute the write inside a savepoint.

⚠️ DECISION (M12.2, D29): confirmation_token is uuid4, single-use,
TTL 10 minutes, bound to (session_id, user_id, action_type, params hash).
A second submit with the same token returns the already-recorded
result; it never re-executes.

⚠️ DECISION (M12.2, D31): perm_unlink=0 for every group (audit rule).
Corrections happen via a new proposal, never deletion.
"""
import hashlib
import json
import logging
import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools import OrderedSet  # noqa: F401  -- keep import shape


_logger = logging.getLogger(__name__)


_TTL_MINUTES = 10
_MAX_PENDING_PER_USER = 3


_STATUS_CHOICES = [
    ("proposed", "Proposed"),
    ("confirmed", "Confirmed"),
    ("cancelled", "Cancelled"),
    ("executed", "Executed"),
    ("error", "Error"),
    ("expired", "Expired"),
]


def _params_hash(action_type, params):
    """Stable hash of (action_type, normalised params) for D29's binding
    check. JSON-serialise with sorted keys + default=str so the hash is
    deterministic across recordsets / dates / Decimals."""
    payload = json.dumps(
        {"a": action_type, "p": params or {}},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class NeonFinanceAiChatWriteLog(models.Model):
    _name = "neon.finance.ai.chat.write.log"
    _description = "AI Copilot Write Audit"
    _order = "create_date desc, id desc"

    session_id = fields.Many2one(
        "neon.finance.ai.chat.session",
        required=True, index=True, ondelete="cascade",
    )
    message_id = fields.Many2one(
        "neon.finance.ai.chat.message",
        ondelete="set null", index=True,
        help="Confirm-or-cancel chat.message row this audit row "
        "renders against. Null until the orchestrator persists the "
        "proposal turn.",
    )
    user_id = fields.Many2one(
        "res.users", required=True, index=True, ondelete="restrict",
        help="User who initiated the proposal. Executes under this "
        "identity (NOT sudo) so ACL checks fire at execute time.",
    )
    confirmed_by = fields.Many2one(
        "res.users", index=True, ondelete="restrict",
        help="User who pressed Confirm. Usually identical to user_id "
        "but recorded separately so a future delegated-confirm flow "
        "can be audited.",
    )

    action_type = fields.Char(required=True, index=True)
    target_model = fields.Char(required=True)
    target_id = fields.Integer(
        default=0,
        help="0 for creates that haven't executed yet. Existing record "
        "id for updates / chatter notes.",
    )
    created_target_id = fields.Integer(
        default=0,
        help="On a successful create the new record id lands here so "
        "the UI's success card can open the record.",
    )

    params_json = fields.Text(
        required=True,
        help="JSON-serialised tool params as validated at propose "
        "time. Re-validated at execute time against the user's ACL.",
    )
    before_json = fields.Text(
        help="Pre-write field values for updates (move_stage, "
        "update_deal_value). Null on creates + chatter notes.",
    )
    after_json = fields.Text(
        help="Proposed post-write field values. Renders the diff in "
        "the confirmation card.",
    )
    human_summary = fields.Char(
        required=True,
        help="One-line summary the LLM produced for the confirmation "
        "card header. e.g. 'Create lead Acme Corp (LED wall) "
        "assigned to you'.",
    )

    confirmation_token = fields.Char(
        required=True, index=True,
        help="uuid4 returned to the UI and submitted back on "
        "/neon/ai_chat/confirm. Single-use; voided on first consume.",
    )
    params_hash = fields.Char(
        required=True,
        help="sha256(action_type + params). D29 binding: a token + "
        "hash mismatch on confirm is rejected as tampering.",
    )

    status = fields.Selection(
        _STATUS_CHOICES, required=True, default="proposed", index=True,
    )
    error_message = fields.Text()
    executed_at = fields.Datetime(index=True)

    expires_at = fields.Datetime(
        required=True, index=True,
        help="Token expiry (proposal + TTL). After this point a "
        "confirm submission is rejected with status='expired'.",
    )

    _sql_constraints = [
        (
            "write_log_token_unique",
            "unique(confirmation_token)",
            "Each confirmation_token must be globally unique.",
        ),
    ]

    # ==================================================================
    # PROPOSE
    # ==================================================================
    @api.model
    def propose(self, session, user, proposal):
        """Persist a write-tool proposal. Returns the saved record so
        the orchestrator can attach the confirmation_token to the
        tool-card payload sent to the UI.

        D29 binding: confirmation_token + sha256(action_type + params)
        + (session_id, user_id) is captured up front and verified on
        confirm. No write side-effect on the target model yet.

        Cap: at most ``_MAX_PENDING_PER_USER`` open proposals per
        user (status='proposed'). Beyond that, raises a friendly
        message the orchestrator surfaces as a chat reply.
        """
        # D34 — cap open proposals so a runaway LLM can't queue 50
        # pending writes a user has to dismiss one by one.
        open_count = self.sudo().search_count([
            ("user_id", "=", user.id),
            ("status", "=", "proposed"),
            ("expires_at", ">", fields.Datetime.now()),
        ])
        if open_count >= _MAX_PENDING_PER_USER:
            return {
                "ok": False,
                "error": (
                    "You have {n} pending actions waiting for "
                    "confirmation. Please confirm or cancel them "
                    "before queueing another."
                ).format(n=open_count),
                "is_proposal_cap": True,
            }
        token = uuid.uuid4().hex
        params = proposal.get("params") or {}
        rec = self.sudo().create({
            "session_id": session.id,
            "user_id": user.id,
            "action_type": proposal["action_type"],
            "target_model": proposal["target_model"],
            "target_id": int(proposal.get("target_id") or 0),
            "params_json": json.dumps(params, default=str),
            "before_json": (
                json.dumps(proposal["before_state"], default=str)
                if proposal.get("before_state") is not None else False),
            "after_json": (
                json.dumps(proposal["after_state"], default=str)
                if proposal.get("after_state") is not None else False),
            "human_summary": proposal["human_summary"],
            "confirmation_token": token,
            "params_hash": _params_hash(
                proposal["action_type"], params),
            "status": "proposed",
            "expires_at": (
                fields.Datetime.now()
                + timedelta(minutes=_TTL_MINUTES)),
        })
        return {"ok": True, "record": rec}

    # ==================================================================
    # CONFIRM / CANCEL
    # ==================================================================
    @api.model
    def consume_token(self, token, user, mode="confirm"):
        """Validate + lock + transition. Returns (rec, status_str).

        - token not found        -> (None, 'not_found')
        - expired                -> (rec, 'expired') + flips status
        - already consumed       -> (rec, 'replay') [no re-execute]
        - wrong user             -> (None, 'forbidden')
        - ok                     -> (rec, 'ok') [caller proceeds]

        D29 single-use guard: a second submit with the same token
        (regardless of mode) returns 'replay' with the recorded result
        rather than re-executing.
        """
        if not token:
            return (None, "not_found")
        rec = self.sudo().search(
            [("confirmation_token", "=", token)], limit=1)
        if not rec:
            return (None, "not_found")
        if rec.user_id.id != user.id:
            return (None, "forbidden")
        if rec.status in ("executed", "cancelled", "error", "expired"):
            return (rec, "replay")
        if rec.expires_at and rec.expires_at < fields.Datetime.now():
            rec.sudo().write({
                "status": "expired",
                "error_message": (
                    "Proposal expired after {n} minutes."
                ).format(n=_TTL_MINUTES),
            })
            return (rec, "expired")
        # status must be 'proposed' or 'confirmed' (rare race) here.
        if mode == "cancel" and rec.status == "proposed":
            rec.sudo().write({
                "status": "cancelled",
                "confirmed_by": user.id,
            })
            return (rec, "cancelled")
        return (rec, "ok")

    def mark_confirmed(self, user):
        """Flip proposed -> confirmed (intermediate step before
        execute()). Separate transition so a crash between confirm
        and execute is auditable."""
        self.ensure_one()
        self.sudo().write({
            "status": "confirmed",
            "confirmed_by": user.id,
        })

    def record_execution(self, created_target_id=None,
                         error_message=None):
        """Final transition. ``error_message`` set -> status='error';
        else status='executed' + executed_at stamped."""
        self.ensure_one()
        vals = {"executed_at": fields.Datetime.now()}
        if error_message:
            vals.update(status="error", error_message=error_message)
        else:
            vals.update(status="executed")
            if created_target_id:
                vals["created_target_id"] = int(created_target_id)
        self.sudo().write(vals)
