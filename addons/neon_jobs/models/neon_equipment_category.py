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
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_TRACKING_MODES = [
    ("serial",   "Serial-tracked (per unit)"),
    ("quantity", "Quantity-tracked (bulk)"),
    ("batch",    "Batch-tracked (groups)"),
]


class NeonEquipmentCategory(models.Model):
    _name = "neon.equipment.category"
    _description = "Workshop Equipment Category"
    _order = "sequence, name"
    # ⚠️ DECISION (B1, D3): hierarchical categories (Selection
    # rejected -- can't grow without code change). Standard Odoo
    # parent_store pattern: parent_id + parent_path + child_ids.
    # A unit's "subcategory" is implicit -- if its
    # equipment_category_id.parent_id is set, the unit is in a
    # sub-category of the root.
    _parent_name = "parent_id"
    _parent_store = True

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
    is_high_impact = fields.Boolean(
        string="High-Impact Category",
        default=False,
        help="P5.M8 — when True, stock-take discrepancies on units "
        "in this category fire an immediate manager-tier alert via "
        "the Action Centre (stock_take_high_impact trigger). "
        "Seed values: Sound, Visual, Lighting, Laptops. Managers "
        "can override per category.",
    )
    description = fields.Text()
    active = fields.Boolean(default=True)

    # B1 (D3) -- hierarchy plumbing. parent_path is indexed by Odoo's
    # parent_store machinery; do NOT set it manually.
    parent_id = fields.Many2one(
        "neon.equipment.category",
        string="Parent Category",
        ondelete="restrict",
        index=True,
        help="When set, this category is a sub-category of the "
        "parent. Read by B2's conflict engine to widen the unit "
        "match net (sub-category of Sound -> Wireless mics will "
        "still count against the Sound population).",
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many(
        "neon.equipment.category", "parent_id",
        string="Sub-categories",
    )

    # B1 (D6) -- low_stock_threshold lives on category, NOT on unit.
    # Per-product-template override deferred to B14.
    low_stock_threshold = fields.Integer(
        string="Low Stock Threshold",
        default=0,
        help="Alert when the count of available units in this "
        "category drops to or below this value. 0 = no alert. "
        "Read by B2 deficit logic and the dashboards.",
    )

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
        # B1 -- a category cannot be its own ancestor. parent_store
        # enforces the tree shape but does not prevent depth-1
        # self-references at write time without a CHECK.
        ("low_stock_threshold_nonneg",
         "CHECK (low_stock_threshold >= 0)",
         "Low stock threshold cannot be negative."),
    ]

    @api.constrains("parent_id")
    def _check_category_recursion(self):
        # Explicit walk of the parent chain. Odoo's _check_recursion
        # helper depends on parent_path being consistent at constraint
        # time, which is unreliable from an odoo shell write path.
        for rec in self:
            seen = set()
            cur = rec.parent_id
            while cur:
                if cur.id == rec.id or cur.id in seen:
                    raise ValidationError(_(
                        "Recursive equipment category hierarchy not "
                        "allowed (cycle detected at %(name)s)."
                    ) % {"name": rec.display_name})
                seen.add(cur.id)
                cur = cur.parent_id

    def _compute_product_count(self):
        for rec in self:
            rec.product_count = len(rec.product_template_ids)
