# -*- coding: utf-8 -*-
"""P6.M4 -- finance approval queue (Schema Sketch §5.4, Q14).

One record per quote-submission event. Replaces P6.M2's auto-approve
placeholder. State machine ``pending -> approved | rejected |
cancelled``; sales reps submit, approver-group users (OD/MD) resolve.
Each pending approval schedules a ``mail.activity`` TODO for every
user in ``group_neon_finance_approver`` so the inbox surfaces the
pending decision; approve/reject/cancel paths all call
``activity_feedback`` to dismiss those TODOs precisely.

⚠️ DECISION (P6.M4): the spec D1 listed a 2-state machine
``pending -> approved | rejected``. We added a fourth state
``cancelled`` so quote cancellation mid-approval has its own audit
trail, rather than overloading "rejected" with cancellation
semantics. ``_cancel_pending_approval(reason)`` is the cascade
helper invoked by ``neon.finance.quote.action_cancel``.

⚠️ DECISION (P6.M4): activities are scheduled on the **approval
record**, not the parent quote. Reason: ``activity_feedback`` is
scoped to ``self``, so dismissing approvers' TODOs needs to target
the same record the schedule lives on. Putting them on the quote
would risk clobbering unrelated TODOs sales reps may have on the
quote in future.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


_logger = logging.getLogger(__name__)


_APPROVAL_STATES = [
    ("pending", "Pending Review"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
    ("cancelled", "Cancelled"),
]
_TERMINAL_STATES = ("approved", "rejected", "cancelled")


class NeonFinanceApproval(models.Model):
    _name = "neon.finance.approval"
    _description = "Quote Approval"
    _order = "create_date desc, id desc"
    _rec_name = "name"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(
        required=True,
        default="/",
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
    )
    quote_id = fields.Many2one(
        "neon.finance.quote",
        string="Quote",
        required=True,
        ondelete="restrict",
        index=True,
    )
    state = fields.Selection(
        _APPROVAL_STATES,
        required=True,
        default="pending",
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
    )

    # ============================================================
    # === Request audit
    # ============================================================
    requested_by_id = fields.Many2one(
        "res.users",
        string="Requested By",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    requested_at = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
        readonly=True,
    )

    # ============================================================
    # === Resolution audit
    # ============================================================
    resolved_by_id = fields.Many2one(
        "res.users",
        readonly=True,
        copy=False,
        tracking=True,
    )
    resolved_at = fields.Datetime(readonly=True, copy=False)
    rejection_reason = fields.Text(readonly=True, copy=False)
    notes = fields.Text(
        help="Approver can add context on approve or reject (e.g. "
        "'Approved with caveat: confirm overtime with client before "
        "send'). Sales rep cannot edit -- this is the approver's "
        "voice."
    )

    # ============================================================
    # === Snapshot of quote state at submission time -- audit-grade
    # === so post-submission line edits don't drift the record.
    # ============================================================
    quote_amount_total_snapshot = fields.Monetary(
        string="Amount Total (snapshot)",
        readonly=True,
        currency_field="quote_currency_id_snapshot",
    )
    quote_currency_id_snapshot = fields.Many2one(
        "res.currency",
        string="Currency (snapshot)",
        readonly=True,
    )

    # ============================================================
    # === D (QUOTE-UX-1): LIVE read-only view of the quote the
    # === approver is actioning -- the full line items + totals on
    # === the approval form itself, so they never approve a quote
    # === whose contents they can't see (no click-through needed).
    # === All related/readonly: the approval record never mutates
    # === the quote; the audit snapshot above is unchanged.
    # ============================================================
    quote_currency_id = fields.Many2one(
        related="quote_id.currency_id", string="Currency", readonly=True)
    quote_line_ids = fields.One2many(
        related="quote_id.line_ids", string="Quote Lines", readonly=True)
    quote_amount_untaxed = fields.Monetary(
        related="quote_id.amount_untaxed", string="Untaxed",
        currency_field="quote_currency_id", readonly=True)
    quote_amount_tax = fields.Monetary(
        related="quote_id.amount_tax", string="VAT",
        currency_field="quote_currency_id", readonly=True)
    quote_amount_total = fields.Monetary(
        related="quote_id.amount_total", string="Total",
        currency_field="quote_currency_id", readonly=True)

    # ============================================================
    # === Phase 9 prep (WhatsApp dispatcher) -- declared now,
    # === wired by Phase 9.
    # ============================================================
    notification_sent = fields.Boolean(
        default=False,
        readonly=True,
        copy=False,
        help="Set to True by the Phase 9 WhatsApp dispatcher once a "
        "notification message has been delivered to OD/MD. M4 leaves "
        "this at False -- declared for forward compatibility.",
    )
    notification_sent_at = fields.Datetime(readonly=True, copy=False)

    # ============================================================
    # === Lifecycle: name from sequence on create
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "neon.finance.approval") or _("APR-NEW")
        return super().create(vals_list)

    # ============================================================
    # === Form-button entry points -- delegate to the quote so the
    # === authoritative state machine lives in one place.
    # ============================================================
    def action_approve_from_form(self):
        """Approve button on the approval form -- delegates to
        the parent quote's action_approve. Authority + state checks
        run there."""
        for rec in self:
            if not rec.quote_id:
                raise UserError(_(
                    "Approval %s has no linked quote."
                ) % rec.name)
            rec.quote_id.action_approve()
        return True

    def action_reject_from_form(self):
        """Reject button on the approval form -- delegates to the
        parent quote's action_reject, lifting the rejection_reason
        from context as the quote method expects."""
        for rec in self:
            if not rec.quote_id:
                raise UserError(_(
                    "Approval %s has no linked quote."
                ) % rec.name)
            rec.quote_id.action_reject()
        return True

    # ============================================================
    # === Cancel cascade helper -- called from quote.action_cancel
    # ============================================================
    def _cancel_pending_approval(self, reason=None):
        """Mark a pending approval as cancelled and dismiss the
        approvers' TODO activities. Called from the parent quote's
        ``action_cancel`` when a sales rep cancels mid-approval.

        Idempotent: if the approval is already in a terminal state
        (approved/rejected/cancelled), this is a no-op.

        sudo() on the writes: sales reps have R-only on approval at
        the ACL layer. The workflow path (cancel cascade) is the only
        legitimate place a non-approver mutates an approval record,
        so we mint the writes under sudo. resolved_by_id captures
        env.user before the sudo so attribution is honest.
        """
        actor = self.env.user
        for rec in self:
            if rec.state in _TERMINAL_STATES:
                continue
            rec.sudo().write({
                "state": "cancelled",
                "resolved_by_id": actor.id,
                "resolved_at": fields.Datetime.now(),
                "notes": (rec.notes or "") + _(
                    "\nCancelled with quote: %s"
                ) % (reason or "(no reason given)"),
            })
            rec.sudo().activity_feedback(
                ["mail.mail_activity_data_todo"],
                feedback=_("Quote cancelled before approval: %s") % (
                    reason or "(no reason given)"),
            )
        return True
