# -*- coding: utf-8 -*-
"""P6.M2 -- finance quote (Schema Sketch §5.1 / §5.3 / §5.5).

Central pivot of Phase 6. State machine drives the lifecycle from
draft to one of five terminal states; downstream milestones extend:

* P6.M3 -- pricing engine fills quote_line.unit_rate +
  bracket_multiplier + day_breakdown_json on save.
* P6.M4 -- replaces ``action_submit_for_approval``'s auto-approve
  placeholder with a real queue + approval_id link.
* P6.M5 -- cost lines + full margin (today line_cost=0 so margin =
  amount_untaxed).
* P6.M7 -- multi-stage invoice schedule wired off ``action_accept``.
* P6.M8 -- email + PDF wired off ``action_send``.

The mail.thread inheritance is in place now so future approval
notifications + WhatsApp hooks (P6/Phase 9) have a tracked log to
attach to; the form view in P6.M2 does NOT render the chatter
(Phase 12 polish gates that).
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


_logger = logging.getLogger(__name__)


_QUOTE_STATES = [
    ("draft", "Draft"),
    ("pending_approval", "Pending Approval"),
    ("approved", "Approved"),
    ("sent", "Sent to Client"),
    ("accepted", "Accepted"),
    ("rejected", "Rejected"),
    ("expired", "Expired"),
    ("cancelled", "Cancelled"),
]
_TERMINAL_STATES = ("accepted", "rejected", "expired", "cancelled")


class NeonFinanceQuote(models.Model):
    _name = "neon.finance.quote"
    _description = "Sales Quote (Phase 6)"
    _order = "create_date desc"
    _rec_name = "name"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # ============================================================
    # === Identity + scope
    # ============================================================
    name = fields.Char(
        required=True,
        default="/",
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
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
        index=True,
        readonly=True,
        string="Customer",
    )
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.ref(
            "base.USD", raise_if_not_found=False),
        tracking=True,
        help="Locks at create -- a quote's currency cannot change "
        "post-create. Issue a new quote if the customer wants the "
        "other currency.",
    )
    conversion_rate_id = fields.Many2one(
        "neon.finance.conversion.rate",
        string="Conversion Rate",
        ondelete="restrict",
        help="Stamped at action_send time so historical reconciliation "
        "always reads against the rate the customer saw on the quote.",
    )
    salesperson_id = fields.Many2one(
        "res.users",
        string="Salesperson",
        required=True,
        default=lambda self: self.env.user,
        index=True,
        tracking=True,
    )

    # ============================================================
    # === State machine
    # ============================================================
    state = fields.Selection(
        _QUOTE_STATES,
        required=True,
        default="draft",
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
    )

    # ============================================================
    # === Lines + display modes
    # ============================================================
    line_ids = fields.One2many(
        "neon.finance.quote.line",
        "quote_id",
        string="Quote Lines",
    )
    crew_display_mode = fields.Selection(
        [
            ("internal_only", "Crew as internal cost only"),
            ("itemised", "Crew itemised on quote"),
        ],
        default="internal_only",
        required=True,
        help="Per-quote toggle (Q4): whether crew lines appear on "
        "the customer-facing quote or are buried in margin. M2 "
        "leaves itemised-mode crew lines as manual entry; future "
        "milestones may auto-populate from event_job crew records.",
    )

    # ============================================================
    # === Payment terms + expiry
    # ============================================================
    payment_term_id = fields.Many2one(
        "neon.finance.payment.term",
        string="Payment Terms",
        ondelete="restrict",
        tracking=True,
        help="Required before submit_for_approval. The wizard at "
        "action_open_payment_term_wizard pre-populates from the "
        "partner's most recent term.",
    )
    expires_at = fields.Date(
        string="Expires",
        default=lambda self: fields.Date.add(
            fields.Date.context_today(self), days=30),
        tracking=True,
        help="When state='sent' and expires_at < today, the daily "
        "expiry cron transitions the quote to 'expired'. Salesperson-"
        "editable while state='draft'.",
    )

    # ============================================================
    # === Approval / send / accept / cancel audit (M2 placeholders
    # === for fields the workflow milestones will fully wire)
    # ============================================================
    # ⚠️ DECISION (P6.M2 / A): approval_id Many2one to the
    # neon.finance.approval model is DEFERRED to P6.M4 per the design
    # gate. Carrying a forward-reference Many2one for two milestones
    # adds noise without value; M4 adds the field via a one-line
    # additive migration.
    approved_by_id = fields.Many2one(
        "res.users",
        readonly=True,
        copy=False,
        tracking=True,
    )
    approved_at = fields.Datetime(readonly=True, copy=False)
    sent_at = fields.Datetime(readonly=True, copy=False)
    accepted_at = fields.Datetime(readonly=True, copy=False)
    rejected_at = fields.Datetime(readonly=True, copy=False)
    rejection_reason = fields.Text(readonly=True, copy=False)
    cancelled_at = fields.Datetime(readonly=True, copy=False)
    cancelled_reason = fields.Text(readonly=True, copy=False)

    # ============================================================
    # === Computed amounts
    # ============================================================
    amount_untaxed = fields.Monetary(
        string="Untaxed Total",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    amount_tax = fields.Monetary(
        string="Tax",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
    )
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amounts",
        store=True,
        currency_field="currency_id",
        tracking=True,
    )
    margin_total = fields.Monetary(
        string="Margin Total",
        compute="_compute_margin",
        store=True,
        currency_field="currency_id",
    )
    margin_pct = fields.Float(
        string="Margin %",
        compute="_compute_margin",
        store=True,
        digits=(5, 2),
    )

    notes = fields.Text()

    # ============================================================
    # === Lifecycle
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        """Stamp the sequence-derived ``name`` from the currency at
        create time. Choosing the sequence at create rather than at
        send means a draft has a stable identifier the salesperson
        can quote in conversation."""
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                currency_id = vals.get("currency_id")
                seq_code = self._sequence_code_for_currency(currency_id)
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    seq_code) or _("QUO-NEW")
        return super().create(vals_list)

    @api.model
    def _sequence_code_for_currency(self, currency_id):
        """Map currency_id -> sequence code. USD uses quote.usd, ZWG
        uses quote.zig; anything else falls back to quote.usd to keep
        ``name`` non-empty. Picked at create -- changing currency
        later (blocked by _check_currency_immutable) does NOT renumber."""
        if currency_id:
            currency = self.env["res.currency"].browse(currency_id)
            if currency.name == "ZWG":
                return "neon.finance.quote.zwg"
        return "neon.finance.quote.usd"

    def write(self, vals):
        """Block currency change post-create. Other fields write
        through unchanged."""
        if "currency_id" in vals:
            for rec in self:
                if rec.currency_id and rec.currency_id.id != vals["currency_id"]:
                    raise UserError(_(
                        "Quote currency is locked once the quote is "
                        "created (%s). Cancel this quote and create a "
                        "new one in the target currency."
                    ) % rec.name)
        return super().write(vals)

    @api.constrains("currency_id")
    def _check_currency_supported(self):
        # Phase 6 prices in USD and ZWG only. Anything else is a
        # misconfiguration we'd rather see early.
        for rec in self:
            if rec.currency_id.name not in ("USD", "ZWG"):
                raise ValidationError(_(
                    "Quote currency must be USD or ZWG (got %s)."
                ) % rec.currency_id.name)

    # ============================================================
    # === Compute amounts + margin
    # ============================================================
    @api.depends(
        "line_ids", "line_ids.line_subtotal", "line_ids.line_total_taxed",
    )
    def _compute_amounts(self):
        for rec in self:
            untaxed = sum(rec.line_ids.mapped("line_subtotal"))
            taxed = sum(rec.line_ids.mapped("line_total_taxed"))
            rec.amount_untaxed = untaxed
            rec.amount_tax = taxed - untaxed
            rec.amount_total = taxed

    @api.depends("amount_untaxed", "line_ids.line_margin")
    def _compute_margin(self):
        for rec in self:
            rec.margin_total = sum(rec.line_ids.mapped("line_margin"))
            if rec.amount_untaxed:
                rec.margin_pct = (
                    rec.margin_total / rec.amount_untaxed * 100.0)
            else:
                rec.margin_pct = 0.0

    # ============================================================
    # === State machine actions
    # ============================================================
    def action_submit_for_approval(self):
        """Draft -> pending_approval -> approved (auto, M2 placeholder).

        P6.M2 PLACEHOLDER: auto-approves immediately after passing the
        same validation a real submission would. P6.M4 replaces the
        auto-approve tail with an approval queue + neon.finance.approval
        record + Approver notification.
        """
        for rec in self:
            if rec.state != "draft":
                raise UserError(_(
                    "Only Draft quotes can be submitted (%s is %s)."
                ) % (rec.name, dict(_QUOTE_STATES)[rec.state]))
            if not rec.line_ids:
                raise UserError(_(
                    "Cannot submit %s with no quote lines."
                ) % rec.name)
            if not rec.payment_term_id:
                raise UserError(_(
                    "Cannot submit %s -- set payment terms first "
                    "(use the 'Set Payment Terms' button)."
                ) % rec.name)
            rec.state = "pending_approval"
            # P6.M2 PLACEHOLDER: auto-approve. Replaced in P6.M4 with
            # an approval queue + Approver notification.
            rec._auto_approve_placeholder()
        return True

    def _auto_approve_placeholder(self):
        """P6.M2 PLACEHOLDER -- replaced in P6.M4 with proper queue."""
        self.ensure_one()
        self.write({
            "state": "approved",
            "approved_by_id": self.env.user.id,
            "approved_at": fields.Datetime.now(),
        })

    def action_approve(self):
        """Pending -> approved. Restricted to Approver group."""
        if not self.env.user.has_group(
                "neon_finance.group_neon_finance_approver"):
            raise AccessError(_(
                "Only users in the Finance / Approver group can "
                "approve quotes."))
        for rec in self:
            if rec.state != "pending_approval":
                raise UserError(_(
                    "Only Pending Approval quotes can be approved "
                    "(%s is %s)."
                ) % (rec.name, dict(_QUOTE_STATES)[rec.state]))
            rec.write({
                "state": "approved",
                "approved_by_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
            })
        return True

    def action_reject(self):
        """Pending -> rejected. Restricted to Approver group. Requires
        a ``rejection_reason`` in the context."""
        if not self.env.user.has_group(
                "neon_finance.group_neon_finance_approver"):
            raise AccessError(_(
                "Only users in the Finance / Approver group can "
                "reject quotes."))
        reason = (self.env.context.get("rejection_reason") or "").strip()
        if not reason:
            raise UserError(_(
                "A rejection reason is required. Pass via context "
                "{'rejection_reason': '...'} or use the rejection wizard."
            ))
        for rec in self:
            if rec.state != "pending_approval":
                raise UserError(_(
                    "Only Pending Approval quotes can be rejected "
                    "(%s is %s)."
                ) % (rec.name, dict(_QUOTE_STATES)[rec.state]))
            rec.write({
                "state": "rejected",
                "rejection_reason": reason,
                "rejected_at": fields.Datetime.now(),
            })
        return True

    def action_send(self):
        """Approved -> sent. Salesperson or finance role.

        P6.M2 PLACEHOLDER: state-only transition. P6.M8 wires the
        actual email + PDF generation here.
        """
        for rec in self:
            if rec.state != "approved":
                raise UserError(_(
                    "Only Approved quotes can be sent (%s is %s)."
                ) % (rec.name, dict(_QUOTE_STATES)[rec.state]))
            if not rec._user_can_act_as_salesperson():
                raise AccessError(_(
                    "Only the quote's salesperson or a Finance "
                    "Bookkeeper / Approver can send %s."
                ) % rec.name)
            rec.write({
                "state": "sent",
                "sent_at": fields.Datetime.now(),
            })
        return True

    def action_accept(self):
        """Sent -> accepted. Salesperson or finance role.

        P6.M2 PLACEHOLDER: state-only transition. P6.M7 wires the
        multi-stage invoice schedule materialisation here.
        """
        for rec in self:
            if rec.state != "sent":
                raise UserError(_(
                    "Only Sent quotes can be accepted (%s is %s)."
                ) % (rec.name, dict(_QUOTE_STATES)[rec.state]))
            if not rec._user_can_act_as_salesperson():
                raise AccessError(_(
                    "Only the quote's salesperson or a Finance "
                    "Bookkeeper / Approver can mark %s as accepted."
                ) % rec.name)
            rec.write({
                "state": "accepted",
                "accepted_at": fields.Datetime.now(),
            })
        return True

    def action_cancel(self):
        """Any non-terminal -> cancelled. Requires cancelled_reason
        in the context."""
        reason = (
            self.env.context.get("cancelled_reason") or ""
        ).strip()
        if not reason:
            raise UserError(_(
                "A cancellation reason is required. Pass via context "
                "{'cancelled_reason': '...'} or use the cancel wizard."
            ))
        for rec in self:
            if rec.state in _TERMINAL_STATES:
                raise UserError(_(
                    "%s is already in a terminal state (%s)."
                ) % (rec.name, dict(_QUOTE_STATES)[rec.state]))
            if not rec._user_can_act_as_salesperson():
                raise AccessError(_(
                    "Only the quote's salesperson or a Finance "
                    "Bookkeeper / Approver can cancel %s."
                ) % rec.name)
            rec.write({
                "state": "cancelled",
                "cancelled_at": fields.Datetime.now(),
                "cancelled_reason": reason,
            })
        return True

    def _user_can_act_as_salesperson(self):
        """True for the assigned salesperson plus any Bookkeeper /
        Approver. Sales reps without the assignment are NOT cleared
        even though their group can write the record -- the record
        rule lets them see only their own quotes anyway, but Sales
        reps from a different rep's quote should not be able to act
        on it via shared visibility (super-user / sudo paths)."""
        self.ensure_one()
        user = self.env.user
        if user.has_group("neon_finance.group_neon_finance_bookkeeper"):
            return True
        if user.has_group("neon_finance.group_neon_finance_approver"):
            return True
        return self.salesperson_id == user

    # ============================================================
    # === Payment term wizard entry point
    # ============================================================
    def action_open_payment_term_wizard(self):
        """Open the per-quote payment term wizard. Pre-populates from
        the partner's most recent term when one exists."""
        self.ensure_one()
        existing = self.env["neon.finance.payment.term"].get_default_for_partner(
            self.partner_id.id)
        ctx = {
            "default_quote_id": self.id,
            "default_partner_id": self.partner_id.id,
        }
        if existing:
            ctx.update({
                "default_deposit_due_days": existing.deposit_due_days,
                "default_deposit_pct": existing.deposit_pct,
                "default_final_due_days": existing.final_due_days,
                "default_late_policy": existing.late_policy,
            })
        return {
            "type": "ir.actions.act_window",
            "name": _("Set Payment Terms"),
            "res_model": "neon.finance.payment.term.wizard",
            "view_mode": "form",
            "target": "new",
            "context": ctx,
        }

    # ============================================================
    # === Daily cron -- sent quotes past expires_at -> expired
    # ============================================================
    @api.model
    def _cron_expire_quotes(self):
        """Daily expiry sweep. Picks up sent quotes whose expires_at
        is strictly before today and walks them to 'expired'. Uses
        sudo so the cron-runner user (base.user_root by default)
        doesn't trip the record rules."""
        today = fields.Date.context_today(self)
        expiring = self.sudo().search([
            ("state", "=", "sent"),
            ("expires_at", "<", today),
        ])
        if not expiring:
            return 0
        expiring.write({"state": "expired"})
        _logger.info(
            "neon.finance.quote: expired %d quote(s) past their "
            "expires_at date.", len(expiring))
        return len(expiring)
