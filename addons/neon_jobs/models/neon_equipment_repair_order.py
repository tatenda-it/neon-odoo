# -*- coding: utf-8 -*-
"""P5.M9 — Equipment repair order.

Workshop fix lifecycle on a damaged or under-maintenance unit:
open → diagnosed → quoted → approved → in_progress → completed
(with cancelled as the escape hatch). Approval and cancellation
are manager-gated. Completion writes the actual_cost and walks
the unit from maintenance back to active.

Repair orders are distinct from incidents (loss / theft / etc.)
but can be linked via incident_id when a single incident produces
one or more repair orders — see neon.equipment.incident
(P5.M9 §3.7). The link is optional: a repair can stand alone for
routine workshop fixes.

Cost recovery (Q14): is_client_caused + chargeback_to_event_id
exist as data fields for the manager to capture intent, but the
actual chargeback journal entry is deferred to the P7 finance
rebuild. Today's behaviour is a chatter note on the event_job
flagging the intent — no invoicing.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_REPAIR_STATES = [
    ("open",        "Open"),
    ("diagnosed",   "Diagnosed"),
    ("quoted",      "Quoted"),
    ("approved",    "Approved"),
    ("in_progress", "In Progress"),
    ("completed",   "Completed"),
    ("cancelled",   "Cancelled"),
]


_ALLOWED_TRANSITIONS = {
    "open":        ["diagnosed", "cancelled"],
    "diagnosed":   ["quoted", "cancelled"],
    "quoted":      ["approved", "cancelled"],
    "approved":    ["in_progress", "cancelled"],
    "in_progress": ["completed", "cancelled"],
    "completed":   [],
    "cancelled":   [],
}


_NON_TERMINAL_STATES = (
    "open", "diagnosed", "quoted", "approved", "in_progress")


class NeonEquipmentRepairOrder(models.Model):
    _name = "neon.equipment.repair.order"
    _description = "Equipment Repair Order"
    _inherit = ["action.centre.mixin", "mail.thread"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "neon.equipment.repair.order") or _("New"),
        copy=False,
        readonly=True,
        index=True,
    )
    unit_id = fields.Many2one(
        "neon.equipment.unit",
        string="Unit",
        required=True,
        index=True,
        ondelete="restrict",
        tracking=True,
    )
    state = fields.Selection(
        _REPAIR_STATES,
        default="open",
        required=True,
        readonly=True,
        tracking=True,
        index=True,
    )

    # === Source context ===
    source_movement_id = fields.Many2one(
        "neon.equipment.movement",
        string="Source Movement",
        ondelete="set null",
        help="The movement that surfaced the fault — typically a "
        "check-in where condition_at_event was 'damaged' or 'poor'.",
    )
    source_event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Source Event",
        ondelete="set null",
        help="The event the damage occurred at, if known.",
    )
    source_stock_take_line_id = fields.Many2one(
        "neon.equipment.stock.take.line",
        string="Source Stock-Take Line",
        ondelete="set null",
        help="Set when the repair was opened from a stock-take "
        "discrepancy via action_open_repair_order on the line.",
    )
    incident_id = fields.Many2one(
        "neon.equipment.incident",
        string="Linked Incident",
        ondelete="set null",
        index=True,
        help="Optional link when this repair is the workshop "
        "follow-up on a loss / theft / accident incident.",
    )

    # === Repair details ===
    fault_description = fields.Text(required=True)
    diagnosis_notes = fields.Text()
    repair_vendor_id = fields.Many2one(
        "res.partner",
        string="Vendor / Workshop Staff",
    )
    is_internal = fields.Boolean(
        default=True,
        help="True when Neon's workshop handles the repair; "
        "False when sent to an external vendor.",
    )
    estimated_cost = fields.Monetary(
        string="Estimated Cost",
        currency_field="currency_id",
    )
    actual_cost = fields.Monetary(
        string="Actual Cost",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )

    # === Timeline ===
    quoted_at = fields.Datetime(tracking=True, readonly=True)
    approved_at = fields.Datetime(tracking=True, readonly=True)
    approved_by_id = fields.Many2one(
        "res.users", string="Approved By", readonly=True)
    started_at = fields.Datetime(tracking=True, readonly=True)
    completed_at = fields.Datetime(tracking=True, readonly=True)

    # === Cost recovery (Q14 — manager intent capture; no invoicing) ===
    is_client_caused = fields.Boolean(
        default=False,
        tracking=True,
        help="Manager flag: damage was caused by client action. "
        "Chargeback handling is deferred to the P7 finance rebuild; "
        "for now setting this posts a chatter note on the linked "
        "event job.",
    )
    chargeback_to_event_id = fields.Many2one(
        "commercial.event.job",
        string="Chargeback Event",
        ondelete="set null",
    )
    chargeback_notes = fields.Text()

    photo = fields.Image(
        max_width=1920, max_height=1080,
        help="Optional damage photo.",
    )

    # ============================================================
    # === State machine
    # ============================================================
    def _do_transition(self, new_state):
        self.ensure_one()
        allowed = _ALLOWED_TRANSITIONS.get(self.state, [])
        if new_state not in allowed:
            raise UserError(_(
                "Illegal repair transition: %(from)s → %(to)s. "
                "Allowed from %(from)s: %(allowed)s"
            ) % {"from": self.state, "to": new_state,
                 "allowed": allowed})
        self.write({"state": new_state})

    def action_diagnose(self):
        for rec in self:
            if not (rec.diagnosis_notes or "").strip():
                raise UserError(_(
                    "Diagnosis notes are required before moving to "
                    "Diagnosed."))
            rec._do_transition("diagnosed")

    def action_quote(self):
        for rec in self:
            if not rec.estimated_cost:
                raise UserError(_(
                    "Set an estimated cost before quoting."))
            rec.write({"quoted_at": fields.Datetime.now()})
            rec._do_transition("quoted")

    def action_approve(self):
        for rec in self:
            if not self.env.user.has_group(
                    "neon_jobs.group_neon_jobs_manager"):
                raise UserError(_(
                    "Repair approval is manager-only."))
            rec.write({
                "approved_at": fields.Datetime.now(),
                "approved_by_id": self.env.uid,
            })
            rec._do_transition("approved")

    def action_start_repair(self):
        for rec in self:
            rec.write({"started_at": fields.Datetime.now()})
            rec._do_transition("in_progress")
            # Unit walk: damaged → maintenance. If the unit is
            # already in maintenance, this no-ops cleanly.
            if rec.unit_id.state == "damaged":
                rec.unit_id.sudo()._do_transition("maintenance")

    def action_complete_repair(self):
        for rec in self:
            if not rec.actual_cost:
                raise UserError(_(
                    "Set the actual cost before completing the "
                    "repair."))
            rec.write({"completed_at": fields.Datetime.now()})
            rec._do_transition("completed")
            # Unit walk: maintenance → active.
            if rec.unit_id.state == "maintenance":
                rec.unit_id.sudo()._do_transition("active")
            rec._post_chargeback_note_if_flagged()

    def action_cancel(self):
        for rec in self:
            if not self.env.user.has_group(
                    "neon_jobs.group_neon_jobs_manager"):
                raise UserError(_(
                    "Repair cancellation is manager-only."))
            rec._do_transition("cancelled")

    def _post_chargeback_note_if_flagged(self):
        """Q14 — when is_client_caused + chargeback_to_event_id are
        set, post a chatter note on the event_job. Actual invoicing
        is deferred to P7."""
        self.ensure_one()
        if not (self.is_client_caused and self.chargeback_to_event_id):
            return
        cost = self.actual_cost or self.estimated_cost or 0.0
        self.chargeback_to_event_id.sudo().message_post(body=_(
            "Repair %(repair)s flagged as client-caused. "
            "Estimated/actual cost: %(cost)s %(ccy)s. Chargeback "
            "handling pending finance rebuild (P7)."
        ) % {
            "repair": self.display_name,
            "cost": cost,
            "ccy": self.currency_id.name or "",
        })

    # ============================================================
    # === Action Centre cron evaluator
    # repair_stalled fires when a repair has sat in any non-terminal
    # state for more than 7 days. Auto-closes via the mixin when the
    # repair transitions to completed or cancelled (handled below in
    # write()).
    # ============================================================
    @api.model
    def _evaluate_repair_stalled_trigger(self):
        cutoff = fields.Datetime.now() - timedelta(days=7)
        candidates = self.sudo().search([
            ("state", "in", list(_NON_TERMINAL_STATES)),
            ("write_date", "<", cutoff),
        ])
        for rec in candidates:
            try:
                rec._action_centre_create_item("repair_stalled")
            except Exception:  # noqa: BLE001
                continue
        return candidates

    def write(self, vals):
        res = super().write(vals)
        if "state" in vals:
            for rec in self.sudo():
                if rec.state in ("completed", "cancelled"):
                    rec._action_centre_close_items(
                        "repair_stalled", force=True)
        return res
