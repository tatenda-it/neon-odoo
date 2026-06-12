# -*- coding: utf-8 -*-
"""
P6.M1 — top-level pricing rule per (category, currency, effective_date).

A pricing rule is a rate card for a single equipment category in a
single currency, dated. Brackets attached to the rule encode the
multi-day discount taper. Day-type multipliers (event / setup / strike)
live on a separate per-category model (neon.finance.day.multiplier).

The actual quote-line compute (rule + brackets + multipliers + days)
arrives in P6.M3. For P6.M1 we ship the schema, constraints, and
seed data; downstream milestones consume.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class NeonFinancePricingRule(models.Model):
    _name = "neon.finance.pricing.rule"
    _description = "Finance Pricing Rule"
    _order = "category_id, currency_id, effective_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        required=True,
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "neon.finance.pricing.rule") or _("New"),
        copy=False,
        readonly=True,
        index=True,
    )
    category_id = fields.Many2one(
        "neon.equipment.category",
        string="Category",
        required=False,
        ondelete="restrict",
        index=True,
        help="Category-scoped rule (the fallback tier). A rule is EITHER "
        "product-scoped (product_template_id set) OR category-scoped "
        "(category_id set) -- exactly one.",
    )
    # WA-12.1 per-product PRIMARY pricing: a product-scoped rule wins over the
    # category rule. nullable; the resolver tries product first, then category.
    product_template_id = fields.Many2one(
        "product.template",
        string="Product",
        required=False,
        ondelete="restrict",
        index=True,
        help="Product-scoped rule (the PRIMARY tier, WA-12.1). When set, this "
        "rate applies to exactly this product, ahead of any category rule.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        index=True,
    )
    base_rate = fields.Monetary(
        string="Day-1 Base Rate",
        required=True,
        currency_field="currency_id",
        help="Base rate for day 1 in this rule's currency. Multi-day "
        "discounts apply via the bracket multipliers.",
    )
    bracket_ids = fields.One2many(
        "neon.finance.pricing.bracket",
        "rule_id",
        string="Brackets",
    )
    override_formula = fields.Text(
        string="Override Formula",
        help="Optional Python expression for advanced pricing. "
        "Parsing happens in P6.M3 — for P6.M1 this is a freeform "
        "text field for future use.",
    )
    active = fields.Boolean(default=True, index=True)
    effective_date = fields.Date(
        required=True,
        default=fields.Date.context_today,
        index=True,
        help="Date this rate card takes effect. Pricing lookups choose "
        "the row with the latest effective_date <= the quote date.",
    )
    notes = fields.Text()

    _sql_constraints = [
        # Each only bites for its non-NULL key (Postgres treats NULLs as
        # distinct), so category rules (product NULL) and product rules
        # (category NULL) are each uniquely keyed without colliding.
        ("unique_category_currency_effective",
         "UNIQUE (category_id, currency_id, effective_date)",
         "A pricing rule already exists for this category, currency, "
         "and effective date. Adjust the existing record or pick a "
         "new effective date."),
        ("unique_product_currency_effective",
         "UNIQUE (product_template_id, currency_id, effective_date)",
         "A pricing rule already exists for this product, currency, "
         "and effective date. Adjust the existing record or pick a "
         "new effective date."),
    ]

    @api.constrains("base_rate")
    def _check_base_rate_non_negative(self):
        for rec in self:
            if rec.base_rate < 0:
                raise ValidationError(_(
                    "Base rate must be zero or positive (got %s) "
                    "on rule %s.") % (rec.base_rate, rec.display_name))

    @api.constrains("product_template_id", "category_id")
    def _check_exactly_one_scope(self):
        """A rule is EITHER product-scoped OR category-scoped, never both,
        never neither (WA-12.1 per-product PRIMARY + the category fallback)."""
        for rec in self:
            if bool(rec.product_template_id) == bool(rec.category_id):
                raise ValidationError(_(
                    "Pricing rule %s must set EXACTLY ONE of Product "
                    "(per-product rate) or Category (fallback rate) -- "
                    "not both, not neither.") % rec.display_name)
