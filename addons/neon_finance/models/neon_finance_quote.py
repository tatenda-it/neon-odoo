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
    # P6.M4 resolves the P6.M2 DECISION deferral: approval_id is now
    # the M2O to the live neon.finance.approval record. Populated by
    # action_submit_for_approval (Standard branch) and read by
    # action_approve / action_reject / action_cancel for state
    # delegation + activity dismissal. ondelete='set null' so the
    # quote keeps its lifecycle state even if an approval somehow
    # gets force-unlinked outside the workflow.
    approval_id = fields.Many2one(
        "neon.finance.approval",
        string="Approval Record",
        ondelete="set null",
        readonly=True,
        copy=False,
        tracking=True,
    )
    # P6.M7 -- multi-stage invoicing schedule reverse o2m. Populated by
    # action_accept (instantiated from partner template or default
    # 100% on_acceptance fallback). Sales rep edits while state='draft';
    # locked after submit. Append-only: no perm_unlink on the child.
    invoice_schedule_ids = fields.One2many(
        "neon.finance.invoice.schedule",
        "quote_id",
        string="Invoice Schedule",
    )
    invoice_schedule_pct_total = fields.Float(
        compute="_compute_invoice_schedule_pct_total",
        string="Schedule % Total",
        help="Sum of stage percentages on this quote. The form banner "
             "warns the sales rep while drafting when this is not 100. "
             "Non-stored: recomputes on every form open.",
    )
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

    @api.depends("invoice_schedule_ids", "invoice_schedule_ids.percentage")
    def _compute_invoice_schedule_pct_total(self):
        for rec in self:
            rec.invoice_schedule_pct_total = sum(
                rec.invoice_schedule_ids.mapped("percentage"))

    # ============================================================
    # === State machine actions
    # ============================================================
    def action_submit_for_approval(self):
        """Draft -> pending_approval (standard branch) or directly to
        approved (config-flag relaxation).

        Reads ir.config_parameter ``neon_finance.approval_required_for_all``
        (default "True"): the True branch creates a
        neon.finance.approval record + schedules mail.activity TODOs
        for every user in group_neon_finance_approver. The False
        branch is an atomic draft->approved write that NEVER touches
        the pending_approval state -- this prevents orphaning a
        pending quote with no approval record if anything between two
        writes were to raise.
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

            require_all = (self.env["ir.config_parameter"].sudo().get_param(
                "neon_finance.approval_required_for_all", "True"
            ) == "True")

            if not require_all:
                # ⚠️ DECISION (P6.M4): atomic single-write transition
                # draft -> approved. We deliberately skip the
                # pending_approval intermediate state and do NOT
                # create an approval record. Future audits of
                # "auto-approved" quotes derive from approved_by_id +
                # approved_at + the absence of approval_id.
                rec.write({
                    "state": "approved",
                    "approved_by_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                })
                rec.message_post(body=_(
                    "Auto-approved (config relaxation: "
                    "approval_required_for_all = False)."))
                continue

            # ⚠️ DECISION (P6.M4): create the approval record BEFORE
            # touching quote.state -- so rec.approval_id is populated
            # atomically with the state transition. If the create
            # raises, the quote stays in draft.
            #
            # sudo() on the create: sales reps have perm_create=0 on
            # neon.finance.approval at the ACL layer (only Approver
            # has create rights) -- the workflow IS the only
            # legitimate creation path, so we mint the record on the
            # user's behalf. The requested_by_id is captured from
            # env.user before the sudo so attribution is honest.
            approval = self.env["neon.finance.approval"].sudo().create({
                "quote_id": rec.id,
                "requested_by_id": self.env.user.id,
                "requested_at": fields.Datetime.now(),
                "quote_amount_total_snapshot": rec.amount_total,
                "quote_currency_id_snapshot": rec.currency_id.id,
            })
            rec.write({
                "state": "pending_approval",
                "approval_id": approval.id,
            })

            # ⚠️ DECISION (P6.M4): schedule activities on the APPROVAL
            # record, not the parent quote. activity_feedback() on
            # approve/reject/cancel is scoped to ``self``; targeting
            # the approval keeps dismissal precise and avoids
            # clobbering unrelated TODOs on the quote.
            #
            # activity_schedule() is the higher-level mail.activity.mixin
            # helper; project precedent (crm_lead.py:128) uses manual
            # mail.activity.create(), but the helper is the right
            # Odoo API and we set the precedent for Phase 6 here.
            approver_group = self.env.ref(
                "neon_finance.group_neon_finance_approver")
            for user in approver_group.users:
                approval.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=user.id,
                    summary=_("Quote approval requested: %s") % rec.name,
                    note=_(
                        "Quote %(name)s for %(partner)s "
                        "(%(total)s %(currency)s). Submitted by %(user)s. "
                        "Review in the Approval Queue."
                    ) % {
                        "name": rec.name,
                        "partner": rec.partner_id.display_name,
                        "total": rec.amount_total,
                        "currency": rec.currency_id.name,
                        "user": self.env.user.name,
                    },
                )

            # Phase 9 will read approval records with state=pending
            # and notification_sent=False and dispatch WhatsApp to
            # OD/MD. M4 leaves notification_sent at the default False.
            rec.message_post(body=_(
                "Submitted for approval. Approval record: %s. "
                "%d approver(s) notified via TODO activity."
            ) % (approval.name, len(approver_group.users)))
        return True

    def action_approve(self):
        """Pending -> approved. Delegates to the approval record;
        approver-only via group check + ACL.

        Separation-of-duties guard (P6.predeploy): the approver
        cannot be the same user as the quote's salesperson. In the
        production matrix, Robin / Munashe / superuser hold both
        sales AND approver groups so the group check alone permits
        self-approval -- this method-level check enforces SoD.
        Approvers may still approve OTHER reps' quotes freely.
        """
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
            if rec.salesperson_id == self.env.user:
                raise UserError(_(
                    "Separation of duties: you cannot approve "
                    "%(name)s because you are also the quote's "
                    "salesperson. Another approver must review."
                ) % {"name": rec.name})
            if not rec.approval_id:
                raise UserError(_(
                    "Quote %s is in pending_approval state but has "
                    "no approval record. Internal consistency error."
                ) % rec.name)
            rec.approval_id.write({
                "state": "approved",
                "resolved_by_id": self.env.user.id,
                "resolved_at": fields.Datetime.now(),
            })
            rec.write({
                "state": "approved",
                "approved_by_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
            })
            rec.approval_id.activity_feedback(
                ["mail.mail_activity_data_todo"],
                feedback=_("Approved by %s") % self.env.user.name,
            )
        return True

    def action_reject(self):
        """Pending -> rejected. Approver-only. Requires a
        ``rejection_reason`` in the context."""
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
            if rec.salesperson_id == self.env.user:
                raise UserError(_(
                    "Separation of duties: you cannot reject "
                    "%(name)s because you are also the quote's "
                    "salesperson. Another approver must review."
                ) % {"name": rec.name})
            if not rec.approval_id:
                raise UserError(_(
                    "Quote %s is in pending_approval state but has "
                    "no approval record. Internal consistency error."
                ) % rec.name)
            rec.approval_id.write({
                "state": "rejected",
                "resolved_by_id": self.env.user.id,
                "resolved_at": fields.Datetime.now(),
                "rejection_reason": reason,
            })
            rec.write({
                "state": "rejected",
                "rejection_reason": reason,
                "rejected_at": fields.Datetime.now(),
            })
            rec.approval_id.activity_feedback(
                ["mail.mail_activity_data_todo"],
                feedback=_("Rejected by %s: %s") % (
                    self.env.user.name, reason),
            )
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

        P6.M5 ADD: writes quoted_budget + currency onto the linked
        event_job. Multi-quote events: latest accept wins (the most
        recently accepted quote stamps its total as the event's
        quoted_budget). Idempotent -- re-accepting (which shouldn't
        happen but is defensive) overwrites with current amount_total
        and currency without raising.

        P6.M7 ADD: invoice schedule materialisation. If no schedules
        exist on the quote yet (sales rep didn't pre-design one),
        instantiate from the partner's most recent active template;
        fall back to a single-stage 100% on_acceptance schedule when
        no template exists. After instantiation, fire any
        on_acceptance-triggered schedules immediately.
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
            # P6.M7 -- a pre-designed schedule must sum to exactly 100.
            # Empty o2m is fine; _materialise_invoice_schedule below
            # will fall back to the default single-stage 100%
            # on_acceptance row.
            if rec.invoice_schedule_ids and abs(
                    rec.invoice_schedule_pct_total - 100.0) > 0.01:
                raise UserError(_(
                    "Cannot accept %s: invoice schedule stage "
                    "percentages sum to %.2f, not 100. Adjust the "
                    "Invoice Schedule tab or clear it to use the "
                    "default 100%% on-acceptance fallback."
                ) % (rec.name, rec.invoice_schedule_pct_total))
            rec.write({
                "state": "accepted",
                "accepted_at": fields.Datetime.now(),
            })
            if rec.event_job_id:
                rec.event_job_id.sudo().write({
                    "quoted_budget": rec.amount_total,
                    "quoted_budget_currency_id": rec.currency_id.id,
                })
            # P6.M7 -- schedule materialisation + on_acceptance fire.
            rec._materialise_invoice_schedule()
            for sched in rec.invoice_schedule_ids.filtered(
                lambda s: s.state == "scheduled" and s.trigger == "on_acceptance"
            ):
                sched.sudo().action_create_invoice()
        return True

    def _materialise_invoice_schedule(self):
        """P6.M7 -- instantiate invoice schedule rows on a freshly
        accepted quote. Skips if rows already exist (sales rep
        pre-designed). Looks up partner's most recent active template;
        falls back to a single-stage 100% on_acceptance schedule.

        sudo() the create: sales reps have R-only on schedule when
        their own quote's salesperson, but at the moment of accept
        the workflow is the only legitimate creation path. We mint
        the records on the user's behalf.
        """
        self.ensure_one()
        if self.invoice_schedule_ids:
            # Sales rep designed it pre-submit; respect that.
            return
        Schedule = self.env["neon.finance.invoice.schedule"].sudo()
        Template = self.env[
            "neon.finance.invoice.schedule.template"].sudo()
        template = Template.search([
            ("partner_id", "=", self.partner_id.id),
            ("active", "=", True),
        ], order="id desc", limit=1)
        if template and template.line_ids:
            # Instantiate from template lines as a single batch create
            # so the constraint _check_percentage_sum_on_accepted sees
            # the final 100% sum, not intermediate partials.
            today = fields.Date.context_today(self)
            vals_list = []
            for tline in template.line_ids.sorted("sequence"):
                vals = {
                    "quote_id": self.id,
                    "sequence": tline.sequence,
                    "stage": tline.stage,
                    "trigger": tline.trigger,
                    "percentage": tline.percentage,
                }
                if tline.trigger == "on_date":
                    vals["trigger_date"] = fields.Date.add(
                        today, days=tline.trigger_offset_days or 0)
                if tline.trigger == "on_event_state":
                    vals["trigger_event_state"] = tline.trigger_event_state
                vals_list.append(vals)
            Schedule.create(vals_list)
            return
        # Fallback: single-stage 100% on_acceptance.
        Schedule.create([{
            "quote_id": self.id,
            "sequence": 10,
            "stage": "final",
            "trigger": "on_acceptance",
            "percentage": 100.0,
        }])

    def action_cancel(self):
        """Any non-terminal -> cancelled. Requires cancelled_reason
        in the context. If cancelling from pending_approval state,
        cascades to the approval record via _cancel_pending_approval
        (which dismisses the approvers' TODO activities)."""
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
            # P6.M4 — cascade to the approval record BEFORE flipping
            # the quote state so the activity dismissal sees the
            # approval still resolvable. The helper is idempotent for
            # already-terminal approvals (no-op).
            if rec.approval_id and rec.approval_id.state == "pending":
                rec.approval_id._cancel_pending_approval(reason=reason)
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
    def action_recalculate_pricing(self):
        """Clear the pricing snapshot on every line and re-run the
        engine. Draft-only -- once a quote has moved past draft, the
        snapshot is contractual.

        Posts a chatter message attributing the recalc to the
        invoking user for audit.
        """
        for quote in self:
            if quote.state != "draft":
                raise UserError(_(
                    "Recalculate Pricing is only available while %s is "
                    "in Draft state (currently %s). Cancel and reopen "
                    "the quote to recompute."
                ) % (quote.name, dict(_QUOTE_STATES)[quote.state]))
            if not quote.line_ids:
                raise UserError(_(
                    "Quote %s has no lines to recalculate."
                ) % quote.name)
            for line in quote.line_ids:
                # Clear the snapshot and re-run. Manual-entry lines
                # (no equipment_line_id and no rule) flip to pricing_
                # status='manual' if unit_rate > 0, else 'not_yet'.
                line.snapshot_taken = False
                # Re-price via the engine for a reservation-backed line, OR a
                # reservation-less categorised line that is NOT a hand-set
                # ('manual') line. Keying on pricing_status (not unit_rate) is
                # what lets an engine-priced reservation-less line (unit_rate now
                # >0 from the rule) RE-price on recalc instead of flipping to
                # 'manual', while a genuinely hand-set 'manual' line is preserved.
                if line.line_type == "equipment" and (
                        line.equipment_line_id
                        or (line.product_template_id.equipment_category_id
                            and line.pricing_status != "manual")):
                    line._compute_line_pricing()
                elif line.unit_rate > 0:
                    line.pricing_status = "manual"
                else:
                    line.pricing_status = "not_yet"
            quote.message_post(body=_(
                "Pricing recalculated by %s. %d line(s) refreshed against "
                "current rules."
            ) % (self.env.user.name, len(quote.line_ids)))
        return True

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
