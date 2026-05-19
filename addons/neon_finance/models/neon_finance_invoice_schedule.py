# -*- coding: utf-8 -*-
"""P6.M7 -- multi-stage invoicing schedule (Schema Sketch §7.1).

One record per (quote, stage). Triggers an account.move invoice
creation when its trigger condition fires. Stages: deposit /
progress / final / retention. Triggers: on_acceptance (fires inside
quote.action_accept), on_date (cron-driven), on_event_state (write()
override on commercial.event.job), manual (button-driven).

⚠️ DECISION (P6.M7, locked at design pause): per-line invoice
proration with stage-charge semantics. Each invoice line is one-
time (quantity=1, price_unit = quote.line.line_subtotal *
percentage / 100) rather than decomposing into per-day rate. This
preempts M3 polish item D (blended unit_rate) leaking into invoice
display. Description names the stage explicitly ("Deposit on Sound
rig").

⚠️ DECISION (P6.M7): trigger_event_state Selection matches the
real event_job state machine -- ready_for_dispatch / in_progress /
completed. The Schema Sketch §7 used 'confirmed' (made-up); we
corrected to the literal state values.

Append-only: no perm_unlink. State machine 'scheduled' -> 'triggered'
-> 'invoiced' -> 'paid' (paid is set externally by payment matching
in P6.M9). Corrections via cancellation, never deletion.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


_logger = logging.getLogger(__name__)


_STAGES = [
    ("deposit", "Deposit"),
    ("progress", "Progress Payment"),
    ("final", "Final Balance"),
    ("retention", "Retention Hold"),
]

_TRIGGERS = [
    ("on_acceptance", "On Quote Acceptance"),
    ("on_date", "On Specific Date"),
    ("on_event_state", "On Event State Change"),
    ("manual", "Manual Trigger Only"),
]

_EVENT_STATES = [
    ("ready_for_dispatch", "Pre-Dispatch"),
    ("in_progress", "Event In Progress"),
    ("completed", "Event Completed"),
]

_SCHEDULE_STATES = [
    ("scheduled", "Scheduled"),
    ("triggered", "Triggered"),
    ("invoiced", "Invoiced"),
    ("paid", "Paid"),
    ("overdue", "Overdue"),
    ("cancelled", "Cancelled"),
]


class NeonFinanceInvoiceSchedule(models.Model):
    _name = "neon.finance.invoice.schedule"
    _description = "Invoice Schedule"
    _order = "quote_id, sequence, id"
    _rec_name = "name"
    _inherit = ["mail.thread"]

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
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    stage = fields.Selection(_STAGES, required=True, default="final")
    trigger = fields.Selection(
        _TRIGGERS, required=True, default="on_acceptance", tracking=True)
    trigger_date = fields.Date(
        help="For trigger='on_date': day to fire (cron daily sweep).",
    )
    trigger_event_state = fields.Selection(
        _EVENT_STATES,
        help="For trigger='on_event_state': event_job state that "
        "fires this schedule's invoice. See locked correction in "
        "design pause -- 'confirmed' from spec replaced with "
        "ready_for_dispatch / in_progress / completed.",
    )
    percentage = fields.Float(required=True, default=100.0)
    invoice_id = fields.Many2one(
        "account.move",
        readonly=True,
        copy=False,
        ondelete="set null",
        help="Set when action_create_invoice fires. State stays "
        "linked even if the invoice is later cancelled on the "
        "Odoo side.",
    )
    state = fields.Selection(
        _SCHEDULE_STATES,
        required=True,
        default="scheduled",
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
    )
    triggered_at = fields.Datetime(readonly=True, copy=False)
    currency_id = fields.Many2one(
        related="quote_id.currency_id",
        store=True,
        readonly=True,
    )
    amount = fields.Monetary(
        compute="_compute_amount",
        store=True,
        currency_field="currency_id",
        help="Computed invoice amount = quote.amount_total * "
        "percentage / 100. Refreshed when percentage or "
        "quote.amount_total changes.",
    )
    notes = fields.Text()

    _sql_constraints = [
        ("check_percentage_range",
         "CHECK (percentage >= 0 AND percentage <= 100)",
         "Schedule percentage must be between 0 and 100."),
    ]

    # ============================================================
    # === Lifecycle
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "neon.finance.invoice.schedule") or _("SCH-NEW")
        return super().create(vals_list)

    @api.depends("quote_id.amount_total", "percentage")
    def _compute_amount(self):
        for rec in self:
            rec.amount = (
                (rec.quote_id.amount_total or 0.0)
                * (rec.percentage or 0.0) / 100.0
            )

    # ============================================================
    # === Validation
    # ============================================================
    @api.constrains("trigger", "trigger_date", "trigger_event_state")
    def _check_trigger_fields(self):
        for rec in self:
            if rec.trigger == "on_date" and not rec.trigger_date:
                raise ValidationError(_(
                    "Schedule %s uses trigger 'on_date' but no "
                    "trigger_date is set."
                ) % rec.name)
            if rec.trigger == "on_event_state" and not rec.trigger_event_state:
                raise ValidationError(_(
                    "Schedule %s uses trigger 'on_event_state' but "
                    "no trigger_event_state is set."
                ) % rec.name)

    @api.constrains("quote_id", "percentage")
    def _check_percentage_sum_on_accepted(self):
        """Percentages must sum to 100 when quote.state='accepted'.
        Draft schedules can be incomplete during design."""
        for rec in self:
            if not rec.quote_id or rec.quote_id.state != "accepted":
                continue
            siblings = rec.quote_id.invoice_schedule_ids
            total = sum(siblings.mapped("percentage"))
            if abs(total - 100.0) > 0.01:
                raise ValidationError(_(
                    "Quote %(name)s is accepted; its invoice schedule "
                    "percentages must sum to 100 (got %(total).2f). "
                    "Adjust schedules or cancel the quote to revise."
                ) % {"name": rec.quote_id.name, "total": total})

    # ============================================================
    # === Trigger dispatch
    # ============================================================
    def action_trigger_now(self):
        """Manual trigger -- approver-gated. Creates the invoice
        immediately regardless of trigger type, as long as state is
        'scheduled'. Useful for ad-hoc billing outside the normal
        on_acceptance / on_date / on_event_state paths."""
        if not self.env.user.has_group(
                "neon_finance.group_neon_finance_approver"):
            raise AccessError(_(
                "Only users in the Finance / Approver group can "
                "manually trigger a schedule."))
        for rec in self:
            if rec.state != "scheduled":
                raise UserError(_(
                    "Schedule %(name)s is in state '%(state)s'; "
                    "only 'scheduled' schedules can be triggered."
                ) % {
                    "name": rec.name,
                    "state": dict(_SCHEDULE_STATES).get(rec.state),
                })
            rec.action_create_invoice()
        return True

    def action_create_invoice(self):
        """Materialise an account.move out_invoice for this schedule
        and transition state. Per-quote-line proration: each line of
        the quote contributes one invoice line with prorated amount.

        ⚠️ DECISION (P6.M7): the invoice line shape is a one-time
        stage charge per quote.line, NOT a per-day decomposition.
        quantity=1, price_unit=(quote.line.line_subtotal * pct/100),
        description="<stage_label> on <quote.line.name>". This avoids
        leaking M3's blended unit_rate semantics into invoice display.

        Uses sudo for the account.move create -- sales reps don't have
        write on account.move. Audit attribution captured in
        invoice_origin = quote.name + ' [' + stage_label + ']'.
        """
        AccountMove = self.env["account.move"].sudo()
        stage_labels = dict(_STAGES)
        for rec in self:
            if rec.state != "scheduled":
                # Idempotent: re-firing on a non-scheduled schedule
                # is a no-op (prevents duplicate invoices from
                # accidental double-trigger).
                continue
            if not rec.quote_id or not rec.quote_id.line_ids:
                _logger.warning(
                    "Schedule %s has no quote lines to invoice; "
                    "skipping.", rec.name)
                continue
            stage_label = stage_labels.get(rec.stage, rec.stage)
            invoice_lines = []
            for ql in rec.quote_id.line_ids:
                prorated = ql.line_subtotal * rec.percentage / 100.0
                invoice_lines.append((0, 0, {
                    "name": _("%(stage)s: %(line)s (%(pct).0f%% of "
                              "%(curr)s %(amt).2f)") % {
                        "stage": stage_label,
                        "line": ql.name,
                        "pct": rec.percentage,
                        "curr": rec.currency_id.name,
                        "amt": ql.line_subtotal,
                    },
                    "quantity": 1.0,
                    "price_unit": prorated,
                    "tax_ids": [(6, 0, ql.tax_id.ids)] if ql.tax_id else [],
                }))
            move = AccountMove.create({
                "move_type": "out_invoice",
                "partner_id": rec.quote_id.partner_id.id,
                "currency_id": rec.currency_id.id,
                "invoice_origin": "%s [%s]" % (
                    rec.quote_id.name, stage_label),
                "ref": rec.name,
                "invoice_line_ids": invoice_lines,
            })
            rec.sudo().write({
                "state": "invoiced",
                "invoice_id": move.id,
                "triggered_at": fields.Datetime.now(),
            })
            rec.quote_id.sudo().message_post(body=_(
                "Invoice %(inv)s created for %(stage)s stage "
                "(%(pct).0f%% = %(curr)s %(amt).2f)."
            ) % {
                "inv": move.name or move.display_name,
                "stage": stage_label,
                "pct": rec.percentage,
                "curr": rec.currency_id.name,
                "amt": rec.amount,
            })
        return True

    # ============================================================
    # === Cron: daily sweep for on_date triggers
    # ============================================================
    @api.model
    def _cron_check_invoice_schedules(self):
        """Daily sweep. Fires schedules where:
          state='scheduled' AND trigger='on_date' AND
          trigger_date <= today.

        on_acceptance fires inside quote.action_accept (immediate).
        on_event_state fires inside commercial.event.job.write()
        (M7 override). manual is button-driven.

        Returns the count of schedules invoiced this run.
        """
        today = fields.Date.context_today(self)
        candidates = self.sudo().search([
            ("state", "=", "scheduled"),
            ("trigger", "=", "on_date"),
            ("trigger_date", "<=", today),
        ])
        if not candidates:
            return 0
        count = 0
        for rec in candidates:
            try:
                rec.action_create_invoice()
                count += 1
            except Exception as e:  # noqa: BLE001
                _logger.error(
                    "Schedule %s on_date trigger failed: %s",
                    rec.name, e)
        _logger.info(
            "neon.finance.invoice.schedule: cron fired %d "
            "on_date invoices.", count)
        return count
