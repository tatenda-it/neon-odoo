# -*- coding: utf-8 -*-
"""
P5.M1 — product.template extended with workshop equipment fields.

Standard Odoo products get an optional "workshop" facet — when
is_workshop_item=True, the product represents a physical piece of
Neon's inventory and the equipment_category_id + tracking_mode fields
become meaningful. Non-workshop products (services, sale-only SKUs)
ignore these fields entirely.

Per-unit identity lives on neon.equipment.unit (Schema Sketch §3.2),
which has a Many2one back to product.template. The two together
implement the hybrid granularity model from D2:
  - product.template = type / SKU / nickname
  - neon.equipment.unit = physical instance (serial, asset tag, state)
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    is_workshop_item = fields.Boolean(
        string="Workshop Item",
        default=False,
        help="Tick when this product is a physical piece of Neon's "
        "workshop inventory. Drives visibility of the Workshop tab "
        "and the equipment-related fields below.",
    )
    equipment_category_id = fields.Many2one(
        "neon.equipment.category",
        string="Equipment Category",
        help="The workshop category this product belongs to. Drives "
        "the default tracking mode and the kanban grouping in the "
        "workshop dashboard.",
    )
    tracking_mode = fields.Selection(
        [
            ("serial",   "Serial-tracked"),
            ("quantity", "Quantity-tracked"),
            ("batch",    "Batch-tracked"),
        ],
        string="Tracking Mode",
        compute="_compute_tracking_mode",
        store=True,
        readonly=False,
        help="Inherits the category default when set; can be "
        "overridden per product. Serial = one unit record per "
        "physical item. Quantity = bulk count only.",
    )
    workshop_name = fields.Char(
        string="Workshop Nickname",
        help="The colloquial name crew use on the workshop floor "
        "(e.g. 'QU16 MIXER', 'LENOVO P72'). Often shorter and "
        "more recognisable than the official product name.",
    )
    equipment_unit_ids = fields.One2many(
        "neon.equipment.unit",
        "product_template_id",
        string="Units",
    )
    total_units = fields.Integer(
        compute="_compute_unit_counts",
        string="Total Units",
    )
    available_units = fields.Integer(
        compute="_compute_unit_counts",
        string="Available Units",
        help="Count of units currently in 'active' state (in service "
        "and not reserved). P5.M4+ refines this with the reservation "
        "model.",
    )

    @api.depends("equipment_category_id",
                 "equipment_category_id.default_tracking")
    def _compute_tracking_mode(self):
        for rec in self:
            if rec.equipment_category_id and not rec.tracking_mode:
                rec.tracking_mode = (
                    rec.equipment_category_id.default_tracking)
            elif not rec.equipment_category_id and not rec.tracking_mode:
                rec.tracking_mode = "quantity"

    @api.depends("equipment_unit_ids", "equipment_unit_ids.state")
    def _compute_unit_counts(self):
        for rec in self:
            rec.total_units = len(rec.equipment_unit_ids)
            rec.available_units = len(rec.equipment_unit_ids.filtered(
                lambda u: u.state == "active"))

    # ============================================================
    # === P5.M3 — tracking_mode change validation (D5)
    # Tightening a tracking_mode (anything → serial or batch) must
    # not strand units in an invalid identity state. Loosening
    # (anything → quantity) is always allowed. Draft and
    # decommissioned units bypass — they are not in active service.
    # ============================================================
    @api.constrains("tracking_mode")
    def _check_tracking_mode_change_against_units(self):
        for rec in self:
            if rec.tracking_mode == "quantity":
                continue
            units = rec.equipment_unit_ids.filtered(
                lambda u: u.state not in ("draft", "decommissioned"))
            if not units:
                continue
            if rec.tracking_mode == "serial":
                bad = units.filtered(
                    lambda u: not (u.serial_number or "").strip())
                if bad:
                    raise ValidationError(_(
                        "Cannot switch %(p)s to serial-tracked — "
                        "%(n)d unit(s) have no serial number: "
                        "%(names)s"
                    ) % {"p": rec.display_name, "n": len(bad),
                         "names": ", ".join(
                             bad[:10].mapped("display_name"))})
            elif rec.tracking_mode == "batch":
                bad = units.filtered(
                    lambda u: not (u.batch_code or "").strip())
                if bad:
                    raise ValidationError(_(
                        "Cannot switch %(p)s to batch-tracked — "
                        "%(n)d unit(s) have no batch code: "
                        "%(names)s"
                    ) % {"p": rec.display_name, "n": len(bad),
                         "names": ", ".join(
                             bad[:10].mapped("display_name"))})
