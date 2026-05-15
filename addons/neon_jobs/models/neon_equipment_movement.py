# -*- coding: utf-8 -*-
"""P5.M5 — Equipment movement audit log.

One row per physical event in a unit's life: checkout, transfer,
check-in, stock adjustment, write-off. Append-only; rows are
created by the source flow (P5.M5 wires checkout; P5.M6 / M7 wire
transfer + check-in) and never updated or unlinked outside the
maintenance context flag.

Location is currently a Char placeholder. Building a proper
neon.workshop.location master is out of P5.M5 scope (no warehouse
hierarchy decision yet) — the existing Char field workshop_location
on neon.equipment.unit is the canonical source for from_location_text
at checkout time.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


_MOVEMENT_TYPES = [
    ("checkout",     "Checkout (workshop → job)"),
    ("transfer_out", "Transfer Out (job → in-transit)"),
    ("transfer_in",  "Transfer In (in-transit → job)"),
    ("checkin",      "Check-In (job → workshop)"),
    ("stock_adjust", "Stock Adjustment"),
    ("write_off",    "Write-Off"),
]


_CONDITIONS = [
    ("good",    "Good"),
    ("fair",    "Fair"),
    ("poor",    "Poor"),
    ("damaged", "Damaged"),
    ("missing", "Missing"),
]


class NeonEquipmentMovement(models.Model):
    _name = "neon.equipment.movement"
    _description = "Equipment Movement (audit log)"
    _order = "create_date desc, id desc"

    name = fields.Char(
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "neon.equipment.movement") or _("New"),
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
    )
    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        index=True,
        ondelete="set null",
    )
    equipment_line_id = fields.Many2one(
        "commercial.event.job.equipment.line",
        string="Line",
        ondelete="set null",
    )
    reservation_id = fields.Many2one(
        "neon.equipment.reservation",
        string="Reservation",
        ondelete="set null",
    )
    movement_type = fields.Selection(
        _MOVEMENT_TYPES,
        required=True,
        index=True,
    )
    actor_id = fields.Many2one(
        "res.users",
        string="Actor",
        required=True,
        default=lambda self: self.env.uid,
    )
    assignee_id = fields.Many2one(
        "res.partner",
        string="Assignee",
        help="Person receiving / handling the unit at this movement.",
    )
    from_location_text = fields.Char(
        string="From Location",
        help="Char placeholder; structured location model deferred.",
    )
    to_location_text = fields.Char(
        string="To Location",
    )
    condition_at_event = fields.Selection(
        _CONDITIONS,
        string="Condition",
    )
    photo = fields.Image(
        max_width=1920, max_height=1080,
        help="Optional at checkout (Q8); mandatory at check-in "
        "(P5.M7 enforces).",
    )
    notes = fields.Text()
    requires_approval = fields.Boolean(
        default=False,
        help="P5.M6 sets this on transfers awaiting manager sign-off.",
    )
    approved_by_id = fields.Many2one("res.users", string="Approved By")
    approved_at = fields.Datetime()

    # ============================================================
    # === Append-only enforcement
    # Movements are an audit log — once written, they don't change
    # except via an explicit maintenance context flag set by support
    # (similar to the action.centre.item.history pattern).
    # ============================================================
    def write(self, vals):
        if not self.env.context.get("_allow_movement_write"):
            # Approval workflow legitimately writes approved_by_id /
            # approved_at after creation. Allow only that narrow set.
            permitted = {"approved_by_id", "approved_at"}
            extra = set(vals.keys()) - permitted
            if extra:
                raise UserError(_(
                    "Equipment movement records are append-only. "
                    "Cannot update fields: %(fields)s. Pass "
                    "_allow_movement_write=True in the context for "
                    "maintenance writes."
                ) % {"fields": sorted(extra)})
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get("_allow_movement_write"):
            raise UserError(_(
                "Equipment movement records are append-only and "
                "cannot be deleted. Pass _allow_movement_write=True "
                "for maintenance unlinks."
            ))
        return super().unlink()
