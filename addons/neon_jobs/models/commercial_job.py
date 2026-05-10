# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CommercialJob(models.Model):
    _name = "commercial.job"
    _description = "Commercial Job — central event record (Phase 2)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "event_date desc, name desc"

    # === Identity ===
    name = fields.Char(
        string="Job Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        tracking=True,
    )
    master_contract_id = fields.Many2one(
        "commercial.job.master",
        string="Master Contract",
        ondelete="set null",
        tracking=True,
        help="Optional. For multi-event corporate clients on a master contract.",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Client",
        required=True,
        tracking=True,
    )
    crm_lead_id = fields.Many2one(
        "crm.lead",
        string="Source CRM Opportunity",
        ondelete="set null",
        tracking=True,
    )
    sale_order_id = fields.Many2one(
        "sale.order",
        string="Sale Order / Quote",
        ondelete="set null",
        tracking=True,
    )
    invoice_ids = fields.Many2many(
        "account.move",
        string="Invoices",
        compute="_compute_invoice_ids",
        store=False,
    )
    invoice_count = fields.Integer(
        string="Invoice Count",
        compute="_compute_invoice_ids",
    )

    # === Two-state primary lifecycle ===
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("active", "Active"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
            ("archived", "Archived (Lost)"),
        ],
        string="Lifecycle",
        default="pending",
        required=True,
        tracking=True,
        help="Pending = quote sent, awaiting Won/Lost. "
        "Active = won, Capacity Gate passed, on the operations calendar. "
        "Completed = event delivered. "
        "Cancelled = explicit cancellation. "
        "Archived = lost lead, kept for reporting.",
    )

    # === Three parallel status tracks (within Active) ===
    commercial_status = fields.Selection(
        [
            ("negotiating", "Negotiating"),
            ("won", "Won"),
            ("lost", "Lost"),
            ("on_hold", "On Hold"),
        ],
        string="Commercial Status",
        default="negotiating",
        tracking=True,
    )
    finance_status = fields.Selection(
        [
            ("quoted", "Quoted"),
            ("deposit_pending", "Deposit Pending"),
            ("deposit_received", "Deposit Received"),
            ("partial_paid", "Partially Paid"),
            ("fully_paid", "Fully Paid"),
            ("overdue", "Overdue"),
        ],
        string="Finance Status",
        default="quoted",
        tracking=True,
    )
    operational_status = fields.Selection(
        [
            ("planning", "Planning"),
            ("soft_hold", "Soft Hold"),
            ("confirmed", "Confirmed"),
            ("pre_event", "Pre-event"),
            ("live", "Live"),
            ("wrapped", "Wrapped"),
            ("done", "Done"),
        ],
        string="Operational Status",
        default="planning",
        tracking=True,
    )

    # === Dates ===
    event_date = fields.Date(
        string="Event Date",
        required=True,
        tracking=True,
        help="Required at pending stage (tentative date OK). "
        "Per Q-S3 — no Commercial Job exists without at least a tentative date.",
    )
    event_end_date = fields.Date(string="Event End Date")
    soft_hold_until = fields.Date(
        string="Soft Hold Until",
        tracking=True,
        help="Auto-set to today + 7 days at pending creation. "
        "Cleared on activation.",
    )

    # === Venue + Room ===
    venue_id = fields.Many2one(
        "res.partner",
        string="Venue",
        required=True,
        domain=[("is_venue", "=", True)],
        tracking=True,
        help="Required at pending stage. Per Q-S3 — must know where, even tentatively.",
    )
    venue_room_id = fields.Many2one(
        "venue.room",
        string="Room",
        domain="[('venue_id', '=', venue_id)]",
        tracking=True,
        help="Specific room within the venue. Optional. "
        "Calendar conflict detection runs at room level when set.",
    )

    # === Equipment summary (high-level for Phase 2; Phase 5 deeper) ===
    equipment_count = fields.Integer(string="Equipment Count")
    equipment_summary = fields.Text(string="Equipment Summary")
    sub_hire_required = fields.Boolean(string="Sub-hire Required", tracking=True)
    logistics_flag = fields.Boolean(string="Logistics Flag", tracking=True)

    # === Crew ===
    crew_assignment_ids = fields.One2many(
        "commercial.job.crew",
        "job_id",
        string="Crew Assignments",
    )
    crew_total_count = fields.Integer(
        string="Crew Total",
        compute="_compute_crew_counts",
    )
    crew_confirmed_count = fields.Integer(
        string="Crew Confirmed",
        compute="_compute_crew_counts",
    )

    # === Money ===
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    quoted_value = fields.Monetary(
        string="Quoted Value",
        currency_field="currency_id",
    )
    deposit_received = fields.Monetary(
        string="Deposit Received",
        currency_field="currency_id",
        help="To be auto-computed from payments in P2.M2+. "
        "Manually editable for now.",
    )

    # === Loss capture ===
    loss_reason = fields.Text(
        string="Loss Reason",
        tracking=True,
        help="Required when state = archived. "
        "Per Robin Q1, Q5 — feeds learnings.",
    )
    lost_to_competitor = fields.Char(string="Lost To Competitor")

    # === Capacity Acceptance Gate result ===
    gate_result = fields.Selection(
        [
            ("not_run", "Not Run"),
            ("pass", "Pass"),
            ("warning", "Warning"),
            ("reject", "Reject"),
            ("overridden", "Overridden"),
        ],
        string="Gate Result",
        default="not_run",
        tracking=True,
        help="Capacity Acceptance Gate outcome. "
        "Per v4.1 §8 — runs automatically when state moves to active. "
        "Logic implemented in P2.M4.",
    )
    gate_run_at = fields.Datetime(string="Gate Last Run", tracking=True)
    gate_override_by = fields.Many2one(
        "res.users",
        string="Override By",
        tracking=True,
        help="MD or OD who overrode a reject. Either has authority (Q3).",
    )
    gate_override_reason = fields.Text(string="Override Reason")
    gate_check_log = fields.Text(
        string="Gate Check Log",
        help="JSON-serialized log of the 8 checks and their individual results.",
    )

    # ============================================================
    # === Computed methods
    # ============================================================
    @api.depends("sale_order_id", "sale_order_id.invoice_ids")
    def _compute_invoice_ids(self):
        for rec in self:
            rec.invoice_ids = rec.sale_order_id.invoice_ids if rec.sale_order_id else False
            rec.invoice_count = len(rec.invoice_ids)

    @api.depends("crew_assignment_ids", "crew_assignment_ids.state")
    def _compute_crew_counts(self):
        for rec in self:
            rec.crew_total_count = len(rec.crew_assignment_ids)
            rec.crew_confirmed_count = len(
                rec.crew_assignment_ids.filtered(lambda c: c.state == "confirmed")
            )

    # ============================================================
    # === Constraints (P2.M1 minimal — full rules live in P2.M2-M5)
    # ============================================================
    @api.constrains("state", "loss_reason")
    def _check_loss_reason_when_archived(self):
        for rec in self:
            if rec.state == "archived" and not rec.loss_reason:
                raise ValidationError(
                    _("Loss Reason is required when archiving a Commercial Job. "
                      "This data feeds future sales-process learning.")
                )

    @api.constrains("event_date", "event_end_date")
    def _check_event_dates(self):
        for rec in self:
            if rec.event_end_date and rec.event_date and rec.event_end_date < rec.event_date:
                raise ValidationError(_("Event End Date cannot be before Event Date."))

    @api.constrains("venue_room_id", "venue_id")
    def _check_room_belongs_to_venue(self):
        for rec in self:
            if rec.venue_room_id and rec.venue_room_id.venue_id != rec.venue_id:
                raise ValidationError(_("The selected Room does not belong to the selected Venue."))

    # ============================================================
    # === Create
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("commercial.job") or _("New")
                )
            # Auto-set soft_hold_until at pending creation if not provided
            if vals.get("state", "pending") == "pending" and not vals.get("soft_hold_until"):
                vals["soft_hold_until"] = fields.Date.add(
                    fields.Date.today(), days=7
                )
        return super().create(vals_list)

    # ============================================================
    # === Onchange — UX helpers
    # ============================================================
    @api.onchange("venue_id")
    def _onchange_venue_id(self):
        if self.venue_room_id and self.venue_room_id.venue_id != self.venue_id:
            self.venue_room_id = False

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        # If partner has an active master contract, suggest it
        if self.partner_id and not self.master_contract_id:
            active_master = self.env["commercial.job.master"].search([
                ("partner_id", "=", self.partner_id.id),
                ("state", "=", "active"),
            ], limit=1)
            if active_master:
                self.master_contract_id = active_master
