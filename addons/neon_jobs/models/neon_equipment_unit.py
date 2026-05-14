# -*- coding: utf-8 -*-
"""
P5.M1 — Equipment Unit (per-physical-item identity).

One row per physical asset. The 8-state lifecycle (Schema Sketch
§3.2) drives reservation eligibility, repair workflow, and the
P5.M9 incident model. For P5.M1, the state field is a Selection
without enforcement — any transition is allowed. P5.M2 introduces
state-machine guards (action_* methods + _do_transition).

Inherits action.centre.mixin so future workshop triggers
(repair_required, asset_overdue_return, maintenance_due) have a
single hook surface.

Serial-tracked products spawn N units (one per serial). Quantity-
tracked products typically have a single "bulk" unit with serial
left blank and asset_tag carrying the bulk identifier.
"""
from odoo import _, api, fields, models


_UNIT_STATES = [
    ("draft",          "Draft (new, not yet in service)"),
    ("active",         "Active (in service, available)"),
    ("reserved",       "Reserved (held for upcoming job)"),
    ("checked_out",    "Checked Out (with crew on job)"),
    ("returned",       "Returned (back, pending check-in)"),
    ("maintenance",    "In Maintenance / Repair"),
    ("damaged",        "Damaged (incident-flagged)"),
    ("decommissioned", "Decommissioned (retired)"),
]


class NeonEquipmentUnit(models.Model):
    _name = "neon.equipment.unit"
    _description = "Workshop Equipment Unit"
    _inherit = ["action.centre.mixin", "mail.thread"]
    _order = "product_template_id, serial_number, id"

    name = fields.Char(
        compute="_compute_name",
        store=True,
        index=True,
    )
    product_template_id = fields.Many2one(
        "product.template",
        string="Product",
        required=True,
        ondelete="restrict",
        domain="[('is_workshop_item', '=', True)]",
        tracking=True,
    )
    # === Related convenience fields for filtering / search ===
    equipment_category_id = fields.Many2one(
        related="product_template_id.equipment_category_id",
        store=True,
        readonly=True,
        string="Category",
    )
    workshop_name = fields.Char(
        related="product_template_id.workshop_name",
        store=False,
        readonly=True,
    )
    tracking_mode = fields.Selection(
        related="product_template_id.tracking_mode",
        store=True,
        readonly=True,
    )

    # === Per-unit identity ===
    serial_number = fields.Char(
        string="Serial Number",
        tracking=True,
        help="The manufacturer's serial. Required for serial-tracked "
        "products (P5.M3 enforcement). Blank for quantity-tracked "
        "bulk units.",
    )
    asset_tag = fields.Char(
        string="Asset Tag",
        tracking=True,
        help="Neon's internal asset identifier — e.g. 'NL2', 'AC-014'. "
        "Optional but recommended for floor traceability.",
    )
    workshop_location = fields.Char(
        string="Location",
        tracking=True,
        help="Physical storage location — e.g. shelf, rack, vehicle.",
    )
    state = fields.Selection(
        _UNIT_STATES,
        string="State",
        default="draft",
        required=True,
        tracking=True,
        help="P5.M1 ships this as an unconstrained selection. P5.M2 "
        "adds the state-machine guards (action_* methods).",
    )

    # === Acquisition + accounting ===
    purchase_date = fields.Date(string="Purchase Date")
    purchase_price = fields.Monetary(
        string="Purchase Price",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )

    notes = fields.Text()
    active = fields.Boolean(default=True, tracking=True)

    _sql_constraints = [
        ("unique_serial_per_product",
         "UNIQUE (product_template_id, serial_number)",
         "Two units of the same product cannot share a serial number."),
        ("unique_asset_tag",
         "UNIQUE (asset_tag)",
         "Asset tags must be unique across all units."),
    ]

    @api.depends("product_template_id.workshop_name",
                 "product_template_id.name",
                 "serial_number", "asset_tag")
    def _compute_name(self):
        for rec in self:
            base = (rec.product_template_id.workshop_name
                    or rec.product_template_id.name
                    or _("(no product)"))
            tag = rec.serial_number or rec.asset_tag
            rec.name = f"{base} #{tag}" if tag else base
