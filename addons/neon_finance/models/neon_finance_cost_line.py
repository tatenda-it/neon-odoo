# -*- coding: utf-8 -*-
"""P6.M5 -- event cost line (Schema Sketch §6.1).

One record per discrete cost incurred against an event_job. Ranganai
(Lead Tech) records cost lines as they materialise during prep,
event, and strike; the create() override dispatches a mail.activity
TODO to every user in the Approver group (Robin / Munashe) AND the
Bookkeeper group (Kudzi) so finance has oversight without depending
on Ranganai to ping them manually.

⚠️ DECISION (P6.M5, pre-approved at design pause):
Notification dispatch is scheduled on the cost.line record itself
(matching the M4 approval pattern). activity_feedback() dismissal
isn't currently wired -- cost lines have no resolution lifecycle yet
-- but the activities are stored against the cost.line so any future
"acknowledge cost" workflow can dismiss precisely.

No perm_unlink for any group: financial records are append-only.
Corrections come via new cost.line records (e.g. negative-amount
reversals) or by updating amount/notes; never via deletion.
"""
import logging

from odoo import _, api, fields, models


_logger = logging.getLogger(__name__)


_COST_TYPES = [
    ("crew", "Crew Labour"),
    ("sub_rental", "Sub-rental"),
    ("consumable", "Consumable"),
    ("transport", "Transport"),
    ("venue", "Venue"),
    ("write_off", "Equipment Write-Off"),
    ("other", "Other"),
]

_PAYMENT_STATES = [
    ("unpaid", "Unpaid"),
    ("paid", "Paid"),
    ("partial", "Partially Paid"),
]


class NeonFinanceCostLine(models.Model):
    _name = "neon.finance.cost.line"
    _description = "Event Cost Line"
    _order = "date_incurred desc, id desc"
    _rec_name = "name"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(
        required=True,
        default="/",
        copy=False,
        index=True,
        tracking=True,
        help="Sequence-stamped identifier (COST-NNNNNN) plus the "
        "human-readable label. The salesperson-visible name lives in "
        "the form's main name field above this sequence stamp.",
    )
    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        related="event_job_id.partner_id",
        store=True,
        readonly=True,
        string="Client",
        help="Filter handle so cost reports can be sliced by customer. "
        "Chained through commercial_job_id.partner_id (same pattern as "
        "neon.finance.quote).",
    )
    cost_type = fields.Selection(
        _COST_TYPES,
        required=True,
        default="other",
        tracking=True,
    )
    vendor_id = fields.Many2one(
        "res.partner",
        string="Vendor / Payee",
        help="Vendor or staff member receiving payment. Schema Sketch "
        "§6.1 calls this 'partner_id' but we renamed to vendor_id to "
        "avoid collision with the client partner accessed via the "
        "event_job chain.",
    )
    amount = fields.Monetary(
        required=True,
        default=0.0,
        currency_field="currency_id",
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.ref(
            "base.USD", raise_if_not_found=False),
        tracking=True,
    )
    date_incurred = fields.Date(
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    date_paid = fields.Date(tracking=True)
    payment_state = fields.Selection(
        _PAYMENT_STATES,
        default="unpaid",
        required=True,
        tracking=True,
    )
    source_movement_id = fields.Many2one(
        "neon.equipment.movement",
        string="Source Movement",
        readonly=True,
        help="Link back to the Phase 5 workshop write-off movement "
        "that originated this cost. P6.M5 leaves this unset; P6.M11 "
        "wires automatic cost.line creation from write-off movements.",
    )
    vendor_bill_id = fields.Many2one(
        "account.move",
        string="Vendor Bill",
        domain="[('move_type', '=', 'in_invoice')]",
        help="Linked vendor bill. P6.M5 leaves this unset; future "
        "milestone will wire the cost.line -> vendor.bill workflow.",
    )
    recorded_by_id = fields.Many2one(
        "res.users",
        string="Recorded By",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    recorded_at = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
        readonly=True,
    )
    notes = fields.Text()

    _sql_constraints = [
        ("check_amount_non_negative_with_writeoff_exception",
         "CHECK (amount >= 0 OR cost_type = 'write_off')",
         "Cost amount must be non-negative (except for write_off "
         "reversal lines, which may be negative)."),
    ]

    # ============================================================
    # === Lifecycle
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        """Stamp the sequence on name (if "/"); dispatch finance-
        oversight activities unless suppressed via context.

        ⚠️ DECISION (P6.M5): the create() override notifies on the
        per-line record (one activity per recipient per cost.line)
        rather than batching one activity per event_job for the
        recipient. Per-line notifications match the spec's intent
        (Ranganai records discrete items, finance reviews each); a
        bulk-import flow that wants to avoid notification storm
        should pass ``skip_finance_notification=True`` in context.
        """
        for vals in vals_list:
            provided = (vals.get("name") or "").strip()
            if provided in ("", "/"):
                provided = ""
            seq_part = self.env["ir.sequence"].next_by_code(
                "neon.finance.cost.line") or _("COST-NEW")
            vals["name"] = (
                "%s -- %s" % (seq_part, provided) if provided else seq_part
            )
        records = super().create(vals_list)
        if not self.env.context.get("skip_finance_notification"):
            for rec in records:
                rec._notify_finance_oversight()
        return records

    def _notify_finance_oversight(self):
        """Schedule a TODO mail.activity for every user in the
        Approver + Bookkeeper groups. Self-suppression: if the
        recorder is in the recipient set (e.g. Kudzi recording her
        own cost line), skip her TODO -- she already knows.

        Activities are scheduled via activity_schedule() rather than
        the manual env['mail.activity'].create() pattern; matches
        the M4 precedent. Loop runs at most O(approvers + bookkeepers)
        which is single-digit users in production.

        Phase 9 hook: the WhatsApp dispatcher will read pending
        activities of type=todo on this model and send messages.
        """
        self.ensure_one()
        approvers = self.env.ref(
            "neon_finance.group_neon_finance_approver",
            raise_if_not_found=False,
        )
        bookkeepers = self.env.ref(
            "neon_finance.group_neon_finance_bookkeeper",
            raise_if_not_found=False,
        )
        recipients = self.env["res.users"]
        if approvers:
            recipients |= approvers.users
        if bookkeepers:
            recipients |= bookkeepers.users
        if not recipients:
            # Empty groups (e.g. fresh fixture state) -- log + bail.
            _logger.info(
                "neon.finance.cost.line: no Approver or Bookkeeper "
                "users available to notify for %s.", self.name)
            return
        summary_label = _("Cost recorded on %s: %s %s%.2f") % (
            self.event_job_id.name,
            dict(self._fields["cost_type"].selection).get(
                self.cost_type, self.cost_type),
            self.currency_id.symbol or self.currency_id.name,
            self.amount,
        )
        note_body = _(
            "%(label)s\nRecorded by %(by)s on %(date)s.\n"
            "Notes: %(notes)s"
        ) % {
            "label": self.name,
            "by": self.recorded_by_id.name,
            "date": self.date_incurred,
            "notes": self.notes or _("(none)"),
        }
        for user in recipients:
            if user == self.recorded_by_id:
                # Self-suppression: don't notify the recorder.
                continue
            self.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=user.id,
                summary=summary_label,
                note=note_body,
            )

    # ============================================================
    # === Onchange warnings (soft enforcement of cost_strategy)
    # ============================================================
    @api.onchange("cost_type", "event_job_id")
    def _onchange_cost_strategy_warning(self):
        """Soft warning when a cost_type=consumable line lands on an
        event whose linked equipment category is set to 'owned_zero'.
        Doesn't block save -- a maintenance cost on owned gear may
        legitimately exist (e.g. replacing a damaged cable that
        belongs to a Sound-category kit).

        Currently checks against the first equipment line's category
        as a proxy; M11 wiring may make this more precise when
        cost.line is auto-created from write-off movements.
        """
        if self.cost_type != "consumable" or not self.event_job_id:
            return
        eq_lines = self.event_job_id.equipment_line_ids[:1]
        if not eq_lines:
            return
        category = eq_lines.category_id
        if not category or not hasattr(category, "cost_strategy"):
            return
        if category.cost_strategy == "owned_zero":
            return {
                "warning": {
                    "title": _("Cost on owned-zero category"),
                    "message": _(
                        "The first equipment line on %(event)s is in "
                        "category '%(cat)s' which is configured with "
                        "cost_strategy='owned_zero' (Neon-owned, no "
                        "per-event cost expected). Booking a "
                        "consumable cost here is allowed (e.g. for "
                        "maintenance items) but worth a sanity check."
                    ) % {
                        "event": self.event_job_id.name,
                        "cat": category.display_name,
                    },
                }
            }
