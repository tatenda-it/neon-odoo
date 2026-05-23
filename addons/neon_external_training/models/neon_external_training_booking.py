# -*- coding: utf-8 -*-
"""neon.external.training.booking -- booking record + state
machine.

Phase 7c M2. State machine + reference auto-gen + cost field
with admin-only group visibility. M3 layers the approval
workflow on top; M4 wires auto-cert issuance on
cert_issued.

State graph:

    draft <-> pending_approval -> booked -> attended -> completed -> cert_issued
                                        |
                                        +-> no_show
                                        |
                                        +-> cancelled (most states)

Transitions are enforced by the action_* methods (Odoo
@api.constrains can't see prior state, so transition
checks live where the user invokes them).
"""
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


_STATE_SELECTION = [
    ("draft", "Draft"),
    ("pending_approval", "Pending Approval"),
    ("booked", "Booked"),
    ("attended", "Attended"),
    ("completed", "Completed"),
    ("cert_issued", "Cert Issued"),
    ("cancelled", "Cancelled"),
    ("no_show", "No Show"),
]


# Allowed transitions: source -> {valid destinations}.
# Anything not listed here raises UserError.
_ALLOWED_TRANSITIONS = {
    "draft": {"pending_approval", "cancelled"},
    "pending_approval": {"draft", "booked", "cancelled"},
    "booked": {"attended", "no_show", "cancelled"},
    "attended": {"completed", "cancelled"},
    "completed": {"cert_issued", "cancelled"},
    # Terminal-ish; M3+ rules may relax.
    "cert_issued": set(),
    "cancelled": set(),
    "no_show": {"cancelled"},
}


class NeonExternalTrainingBooking(models.Model):
    _name = "neon.external.training.booking"
    _description = "Neon External Training Booking"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "scheduled_date desc, id desc"
    _rec_name = "name"

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    reference = fields.Char(
        string="Reference",
        readonly=True,
        copy=False,
        index=True,
        help="Auto-generated BKG-YYYY-NNN by the booking "
             "sequence at create time.",
    )
    name = fields.Char(
        string="Booking",
        compute="_compute_name",
        store=True,
        help="Display name: reference + course + crew.",
    )

    # ------------------------------------------------------------------
    # Refs
    # ------------------------------------------------------------------
    vendor_id = fields.Many2one(
        "neon.external.training.vendor",
        string="Vendor",
        required=True,
        ondelete="restrict",
        tracking=True,
    )
    course_name = fields.Char(
        required=True,
        tracking=True,
    )
    crew_user_id = fields.Many2one(
        "res.users",
        string="Crew Member",
        required=True,
        domain=[("share", "=", False)],
        tracking=True,
    )
    cert_type_id = fields.Many2one(
        "neon.training.certification.type",
        string="Cert Type",
        ondelete="set null",
        help="Optional. If set, M4 auto-issues a "
             "neon.training.certification on cert_issued.",
    )

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------
    scheduled_date = fields.Date(
        required=True,
        tracking=True,
    )
    duration_days = fields.Integer(
        default=1,
        tracking=True,
    )
    location = fields.Char(tracking=True)

    # ------------------------------------------------------------------
    # Cost (admin-only visibility via groups attribute)
    # ------------------------------------------------------------------
    cost_amount = fields.Monetary(
        string="Cost",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
        groups="neon_core.group_neon_superuser,"
               "neon_core.group_neon_bookkeeper",
        help="Cost to Neon for this booking. Visible only to "
             "superuser + bookkeeper tiers.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: (
            self.env.company.currency_id.id),
    )

    # ------------------------------------------------------------------
    # Workflow state
    # ------------------------------------------------------------------
    state = fields.Selection(
        _STATE_SELECTION,
        string="Status",
        default="draft",
        tracking=True,
        required=True,
        copy=False,
    )
    date_attended = fields.Date(
        string="Attended On",
        readonly=True,
        copy=False,
    )
    date_completed = fields.Date(
        string="Completed On",
        readonly=True,
        copy=False,
    )

    notes = fields.Text()

    _sql_constraints = [
        ("booking_reference_unique",
         "UNIQUE(reference)",
         "Booking reference must be unique."),
    ]

    # ==================================================================
    # Create / compute
    # ==================================================================
    @api.depends("reference", "course_name", "crew_user_id")
    def _compute_name(self):
        for rec in self:
            crew = (rec.crew_user_id.name
                    if rec.crew_user_id else "(no crew)")
            rec.name = "%s: %s -- %s" % (
                rec.reference or "(new)",
                rec.course_name or "(no course)",
                crew,
            )

    @api.model_create_multi
    def create(self, vals_list):
        Seq = self.env["ir.sequence"]
        for vals in vals_list:
            if not vals.get("reference"):
                vals["reference"] = Seq.next_by_code(
                    "neon.external.training.booking"
                ) or "/"
        return super().create(vals_list)

    # ==================================================================
    # Validation
    # ==================================================================
    @api.constrains("cost_amount")
    def _check_cost_non_negative(self):
        for rec in self:
            if (rec.cost_amount or 0.0) < 0:
                raise ValidationError(_(
                    "Cost cannot be negative."))

    # ==================================================================
    # State machine -- transition guard
    # ==================================================================
    def _transition_to(self, new_state, extra_vals=None):
        """Move self to new_state, enforcing the
        _ALLOWED_TRANSITIONS graph. extra_vals merge into
        the write payload (e.g., date_attended)."""
        self.ensure_one()
        vals = dict(extra_vals or {})
        if self.state == new_state:
            # Idempotent no-op; surface as UserError so the
            # caller doesn't double-write.
            raise UserError(_(
                "Booking %s is already in state '%s'."
            ) % (self.reference or "(unsaved)", new_state))
        allowed = _ALLOWED_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise UserError(_(
                "Cannot transition booking %s from "
                "'%s' to '%s'. Allowed next states: %s."
            ) % (
                self.reference or "(unsaved)",
                self.state, new_state,
                ", ".join(sorted(allowed)) or "(none)",
            ))
        vals["state"] = new_state
        self.write(vals)

    # ------------------------------------------------------------------
    # Public action methods (M2 ships stubs; M3 enriches
    # approval-side wiring).
    # ------------------------------------------------------------------
    def action_submit_for_approval(self):
        self.ensure_one()
        # Past-date guard at submission only.
        if (self.scheduled_date
                and self.scheduled_date < fields.Date.today()):
            raise UserError(_(
                "Cannot submit booking %s for approval -- "
                "scheduled_date %s is in the past."
            ) % (self.reference or "(unsaved)",
                 self.scheduled_date))
        if not self.vendor_id or not self.crew_user_id:
            raise UserError(_(
                "Vendor and Crew Member are required before "
                "submission for approval."))
        self._transition_to("pending_approval")

    def action_mark_attended(self):
        self.ensure_one()
        self._transition_to("attended", {
            "date_attended": fields.Date.today(),
        })

    def action_mark_completed(self):
        self.ensure_one()
        self._transition_to("completed", {
            "date_completed": fields.Date.today(),
        })

    def action_mark_cert_issued(self):
        # M4 will layer auto-cert issuance here. M2 just
        # transitions state.
        self.ensure_one()
        self._transition_to("cert_issued")

    def action_cancel(self):
        self.ensure_one()
        self._transition_to("cancelled")

    def action_mark_no_show(self):
        self.ensure_one()
        self._transition_to("no_show")
