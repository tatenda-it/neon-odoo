# -*- coding: utf-8 -*-
"""
P5.M1 — Equipment Category.

Top-level taxonomy for Neon's workshop inventory. The 9 categories
seeded from the PHP-era workshop tooling (D3 in the M1 spec):
Sound, Visual, Lighting, Cabling and Accessories, Laptops, Staging,
Dance Floor, Effects, Trussing.

Each category carries a default tracking mode (serial vs quantity)
per D4. product.template instances inherit the category's
default_tracking unless overridden explicitly on the product.
"""
from odoo import _, fields, models


_TRACKING_MODES = [
    ("serial",   "Serial-tracked (per unit)"),
    ("quantity", "Quantity-tracked (bulk)"),
    ("batch",    "Batch-tracked (groups)"),
]


class NeonEquipmentCategory(models.Model):
    _name = "neon.equipment.category"
    _description = "Workshop Equipment Category"
    _order = "sequence, name"

    name = fields.Char(string="Category", required=True, translate=True)
    code = fields.Char(
        string="Code",
        required=True,
        help="Stable identifier used in XML IDs and code references. "
        "Lowercase, no spaces — e.g. 'sound', 'dance_floor'.",
    )
    sequence = fields.Integer(default=10)
    default_tracking = fields.Selection(
        _TRACKING_MODES,
        string="Default Tracking",
        required=True,
        default="serial",
        help="The tracking mode applied to new product.template entries "
        "created in this category. Individual products can override.",
    )
    icon = fields.Char(
        string="Icon (FontAwesome)",
        help="FontAwesome class for kanban tile rendering — e.g. "
        "'fa-volume-up'. Used by P5.M10 workshop dashboard.",
    )
    description = fields.Text()
    active = fields.Boolean(default=True)

    # Reverse pointer to products in this category
    product_template_ids = fields.One2many(
        "product.template",
        "equipment_category_id",
        string="Products",
    )
    product_count = fields.Integer(
        compute="_compute_product_count",
        string="# Products",
    )

    _sql_constraints = [
        ("unique_code", "UNIQUE (code)",
         "Equipment category codes must be unique."),
    ]

    def _compute_product_count(self):
        for rec in self:
            rec.product_count = len(rec.product_template_ids)
