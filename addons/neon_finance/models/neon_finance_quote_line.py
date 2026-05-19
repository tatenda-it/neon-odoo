# -*- coding: utf-8 -*-
"""P6.M2 -- quote line. Schema Sketch §5.2.

One line is one billable item on a quote: equipment + duration, a
crew slot, a sub-rental, a consumable, or 'other'. The pricing-engine
compute that fills ``bracket_multiplier`` + ``day_breakdown_json`` +
the priced ``unit_rate`` lands in P6.M3. For M2 these fields exist as
schema placeholders -- ``unit_rate`` is salesperson-entered and
``bracket_multiplier`` defaults to 1.0.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_LINE_TYPES = [
    ("equipment", "Equipment"),
    ("crew", "Crew"),
    ("sub_rental", "Sub-rental"),
    ("consumable", "Consumable"),
    ("other", "Other"),
]


class NeonFinanceQuoteLine(models.Model):
    _name = "neon.finance.quote.line"
    _description = "Quote Line"
    _order = "sequence, id"

    quote_id = fields.Many2one(
        "neon.finance.quote",
        string="Quote",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(
        _LINE_TYPES,
        required=True,
        default="other",
    )
    equipment_line_id = fields.Many2one(
        "commercial.event.job.equipment.line",
        string="Equipment Line",
        ondelete="set null",
        help="Link to the event_job's equipment line, for reconciliation "
        "between quoted gear and dispatched gear. Only meaningful when "
        "line_type='equipment'. Left manual for P6.M2 -- the salesperson "
        "picks; P6.M3 may auto-link when the pricing engine wires up.",
    )
    product_template_id = fields.Many2one(
        "product.template",
        string="Product",
        help="Optional product reference. P6.M3 will use this together "
        "with the equipment_line_id to look up the pricing.rule.",
    )
    name = fields.Char(required=True)
    quantity = fields.Float(required=True, default=1.0)
    unit_rate = fields.Monetary(
        required=True,
        currency_field="currency_id",
        help="Per-unit-per-day rate after bracket multiplier is applied. "
        "Salesperson-entered for P6.M2; pricing-engine compute in P6.M3 "
        "fills this from pricing.rule + day_multipliers + bracket lookup.",
    )
    duration_days = fields.Integer(required=True, default=1)
    bracket_multiplier = fields.Float(
        default=1.0,
        help="Snapshot of the multi-day bracket multiplier that was "
        "applied to derive unit_rate. P6.M2 leaves this at 1.0; P6.M3's "
        "pricing engine writes the real value.",
    )
    day_breakdown_json = fields.Text(
        help="JSON snapshot of the day-by-day multiplier breakdown the "
        "pricing engine used to derive unit_rate. P6.M2 placeholder; "
        "P6.M3 fills.",
    )
    currency_id = fields.Many2one(
        related="quote_id.currency_id",
        store=True,
        readonly=True,
    )
    line_subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_subtotal",
        store=True,
        currency_field="currency_id",
    )
    tax_id = fields.Many2one(
        "account.tax",
        string="Tax",
        default=lambda self: self._default_tax(),
        domain="[('type_tax_use', '=', 'sale')]",
    )
    line_total_taxed = fields.Monetary(
        string="Total (Taxed)",
        compute="_compute_total_taxed",
        store=True,
        currency_field="currency_id",
    )
    line_cost = fields.Monetary(
        string="Line Cost",
        default=0.0,
        currency_field="currency_id",
        help="Internal cost basis for this line, used in margin compute. "
        "P6.M2 placeholder (defaults to 0). P6.M5 wires cost compute from "
        "the equipment category's cost_strategy (owned-zero, "
        "consumable-actual, sub-rental-supplier).",
    )
    line_margin = fields.Monetary(
        string="Line Margin",
        compute="_compute_line_margin",
        store=True,
        currency_field="currency_id",
    )
    notes = fields.Text()

    _sql_constraints = [
        ("check_quantity_positive",
         "CHECK (quantity > 0)",
         "Quantity must be strictly positive."),
        ("check_duration_days_positive",
         "CHECK (duration_days >= 1)",
         "Duration must be at least 1 day."),
        ("check_unit_rate_non_negative",
         "CHECK (unit_rate >= 0)",
         "Unit rate cannot be negative."),
    ]

    @api.model
    def _default_tax(self):
        """Default to the ZIMRA 15.5% standard sale tax if installed,
        else leave empty so the salesperson picks. Lookup by xml_id
        so a renamed UI label doesn't break the default."""
        tax = self.env.ref(
            "neon_finance.tax_vat_15_5_sale",
            raise_if_not_found=False,
        )
        return tax.id if tax else False

    @api.depends("quantity", "unit_rate", "duration_days")
    def _compute_subtotal(self):
        for rec in self:
            rec.line_subtotal = (
                rec.quantity * rec.unit_rate * rec.duration_days)

    @api.depends("line_subtotal", "tax_id")
    def _compute_total_taxed(self):
        for rec in self:
            if rec.tax_id and rec.line_subtotal:
                # account.tax.compute_all returns a dict; total_included
                # is the gross figure that lands on the customer invoice.
                tax_result = rec.tax_id.compute_all(
                    rec.line_subtotal,
                    currency=rec.currency_id,
                    quantity=1.0,
                )
                rec.line_total_taxed = tax_result.get(
                    "total_included", rec.line_subtotal)
            else:
                rec.line_total_taxed = rec.line_subtotal

    @api.depends("line_subtotal", "line_cost")
    def _compute_line_margin(self):
        # Margin = revenue - cost. line_cost is the P6.M5 placeholder;
        # for M2 with line_cost=0, margin == subtotal.
        for rec in self:
            rec.line_margin = rec.line_subtotal - rec.line_cost

    @api.constrains("line_type", "equipment_line_id")
    def _check_equipment_line_consistency(self):
        # Warning-level only: an equipment_line_id linked under a
        # non-equipment line_type indicates a misconfiguration. Raised
        # as ValidationError because the alternative (silent drift) is
        # worse for downstream reconciliation in P6.M11.
        for rec in self:
            if rec.equipment_line_id and rec.line_type != "equipment":
                raise ValidationError(_(
                    "Line %(name)s has an equipment_line_id set but its "
                    "line_type is '%(type)s'. Clear the equipment link "
                    "or change the line type to 'equipment'."
                ) % {"name": rec.name, "type": rec.line_type})
