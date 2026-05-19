# -*- coding: utf-8 -*-
"""P6.M2 -- quote line schema. P6.M3 -- pricing engine wiring.

One line is one billable item on a quote: equipment + duration, a crew
slot, a sub-rental, a consumable, or 'other'. The pricing-engine
compute lives here (filling ``unit_rate`` + ``bracket_multiplier`` +
``day_breakdown_json`` + ``pricing_status``); it runs once at create
time when an equipment-typed line has a resolvable rule, takes a
snapshot, then never auto-recomputes -- a salesperson can change
``duration_days`` on the line and the unit_rate stays put. The
"Recalculate Pricing" button on the parent quote (draft-only) clears
``snapshot_taken`` and re-runs the engine.

⚠️ DECISION (P6.M3): the design-pause spec D5 prescribed
``unit_rate = base_rate * bracket_multiplier`` with the day
multiplier folded directly into ``line_subtotal`` via a separate
direct assignment. That collides with the M2 stored compute
``line_subtotal = qty * unit_rate * duration_days``. Resolution:
``unit_rate`` here is stamped as the *blended per-day rate* --
``base_rate * bracket_multiplier * day_multiplier_blend``. Under the
M3 fallback (event_days == duration_days, no setup/strike split) the
blend is just ``event_day_multiplier``. ``bracket_multiplier`` is
still snapshotted as a separate field for audit + view display, and
``day_breakdown_json`` records the per-day-type breakdown. Result:
``line_subtotal`` compute logic stays in one place, sales reps see a
meaningful per-day rate, and ``bracket_multiplier`` remains visible
as the bracket snapshot.
"""
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


_LINE_TYPES = [
    ("equipment", "Equipment"),
    ("crew", "Crew"),
    ("sub_rental", "Sub-rental"),
    ("consumable", "Consumable"),
    ("other", "Other"),
]

_PRICING_STATUS = [
    ("not_yet", "Not yet priced"),
    ("priced", "Priced from rule"),
    ("no_rule", "No rule found"),
    ("manual", "Manually overridden"),
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
        "line_type='equipment'. P6.M3 uses this to resolve the "
        "category for pricing-rule lookup.",
    )
    product_template_id = fields.Many2one(
        "product.template",
        string="Product",
        help="Optional product reference. P6.M3 currently routes pricing "
        "lookup through equipment_line_id.category_id; future milestones "
        "may also resolve via product_template_id.equipment_category_id.",
    )
    name = fields.Char(required=True)
    quantity = fields.Float(required=True, default=1.0)
    unit_rate = fields.Monetary(
        required=True,
        currency_field="currency_id",
        help="Per-unit-per-day blended rate. Stamped by the pricing "
        "engine as base_rate * bracket_multiplier * day_multiplier "
        "(event-day blend under the M3 day-decomposition fallback). "
        "Salesperson can override manually; snapshot semantics prevent "
        "subsequent duration_days edits from drifting the rate.",
    )
    duration_days = fields.Integer(required=True, default=1)
    bracket_multiplier = fields.Float(
        default=1.0,
        readonly=True,
        help="Bracket multiplier snapshotted at the moment the pricing "
        "engine priced this line. Read-only -- changing the bracket "
        "happens upstream on neon.finance.pricing.bracket and is only "
        "reflected here when the quote owner clicks Recalculate.",
    )
    day_breakdown_json = fields.Text(
        readonly=True,
        help="JSON snapshot of the day-by-day multiplier breakdown the "
        "pricing engine used. Shape: "
        "{setup_days, event_days, strike_days, base_rate, "
        "bracket_multiplier, event_day_multiplier, "
        "setup_day_multiplier, strike_day_multiplier}.",
    )
    snapshot_taken = fields.Boolean(
        default=False,
        readonly=True,
        copy=False,
        help="True once the pricing engine has stamped this line. Used "
        "to prevent auto-recompute on subsequent edits to "
        "duration_days / quantity. Cleared by the parent quote's "
        "Recalculate action.",
    )
    pricing_status = fields.Selection(
        _PRICING_STATUS,
        default="not_yet",
        readonly=True,
        copy=False,
        help="Tracks why this line has its current unit_rate. 'priced' "
        "means the engine found a rule and applied it; 'no_rule' means "
        "the engine ran but found no matching pricing rule for the "
        "line's category x currency; 'manual' is the salesperson "
        "having set the rate by hand; 'not_yet' is the new-line default "
        "before any pricing path has run.",
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
        "P6.M3 leaves at 0 (placeholder); P6.M5 wires cost compute from "
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

    # ============================================================
    # === Defaults + computes (M2 logic, unchanged)
    # ============================================================
    @api.model
    def _default_tax(self):
        """Default to the ZIMRA 15.5% standard sale tax if installed,
        else leave empty so the salesperson picks. account.tax is per-
        company in Odoo (not per-currency), so the single sale-tax
        record applies to lines in either USD or ZWG -- VAT reporting
        derives the per-currency split from the invoice line itself."""
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
        for rec in self:
            rec.line_margin = rec.line_subtotal - rec.line_cost

    @api.constrains("line_type", "equipment_line_id")
    def _check_equipment_line_consistency(self):
        for rec in self:
            if rec.equipment_line_id and rec.line_type != "equipment":
                raise ValidationError(_(
                    "Line %(name)s has an equipment_line_id set but its "
                    "line_type is '%(type)s'. Clear the equipment link "
                    "or change the line type to 'equipment'."
                ) % {"name": rec.name, "type": rec.line_type})

    # ============================================================
    # === P6.M3 pricing engine
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        """Take the pricing snapshot on create for equipment-typed lines
        that have a resolvable rule. Manual lines (unit_rate set in the
        vals, no equipment_line_id) bypass the engine and stamp
        pricing_status='manual'."""
        lines = super().create(vals_list)
        for line in lines:
            if line.snapshot_taken:
                # Created with an explicit snapshot (e.g. by the
                # Recalculate action) -- don't re-snapshot.
                continue
            if line.line_type == "equipment" and line.equipment_line_id:
                line._compute_line_pricing()
            elif line.unit_rate > 0:
                # Salesperson typed in a rate without an equipment link
                # -- treat as manual.
                line.pricing_status = "manual"
        return lines

    def _find_pricing_rule(self):
        """Return the most-recent active pricing rule for this line's
        category x currency, or an empty recordset if none exists.

        Lookup chain:
          equipment_line_id -> category_id
          quote_id -> currency_id
          neon.finance.pricing.rule(category, currency, effective_date<=today)
            ordered by effective_date desc, take first.

        Returns the rule's sudo recordset so the salesperson's
        read-only ACL on pricing.rule still resolves the lookup
        (P6.M1 CSV grants Sales read-only)."""
        self.ensure_one()
        if not self.equipment_line_id:
            return self.env["neon.finance.pricing.rule"]
        category = self.equipment_line_id.category_id
        currency = self.quote_id.currency_id
        if not category or not currency:
            return self.env["neon.finance.pricing.rule"]
        return self.env["neon.finance.pricing.rule"].sudo().search(
            [
                ("category_id", "=", category.id),
                ("currency_id", "=", currency.id),
                ("active", "=", True),
                ("effective_date", "<=", fields.Date.context_today(self)),
            ],
            order="effective_date desc, id desc",
            limit=1,
        )

    @staticmethod
    def _find_bracket(rule, total_days):
        """Return the bracket whose [day_from, day_to] window contains
        ``total_days``. day_to == -1 is the open-ended tail (matches
        any day >= day_from). Returns an empty recordset if the rule's
        brackets don't cover the requested day count."""
        for bracket in rule.bracket_ids.sorted("sequence"):
            if bracket.day_from <= total_days and (
                bracket.day_to == -1 or bracket.day_to >= total_days
            ):
                return bracket
        return rule.bracket_ids[:0]

    def _decompose_days(self):
        """Return (setup_days, event_days, strike_days) for this line.

        commercial.event.job does NOT yet expose setup/event/strike day
        fields (confirmed at P6.M3 discovery -- only event_date,
        event_end_date, prep_start_datetime, return_eta_datetime
        exist, and those are for equipment reservation windows, not
        crew schedule). P6.M3 falls back to treating the entire
        duration_days as event days. A future milestone will add the
        three day-type fields to commercial.event.job; until then the
        day_multiplier table on neon.finance.day.multiplier still
        applies via the event_day_multiplier."""
        self.ensure_one()
        event_job = self.quote_id.event_job_id
        if event_job and hasattr(event_job, "setup_days"):
            return (
                int(getattr(event_job, "setup_days", 0) or 0),
                int(getattr(event_job, "event_days", 0) or 0),
                int(getattr(event_job, "strike_days", 0) or 0),
            )
        return (0, self.duration_days, 0)

    def _compute_line_pricing(self):
        """Run the pricing engine for this line. Stamps unit_rate,
        bracket_multiplier, day_breakdown_json, snapshot_taken,
        pricing_status. Posts a chatter message on the parent quote
        when no matching rule is found.

        Idempotent: clearing snapshot_taken (via the parent quote's
        Recalculate) and calling again re-snaps to current rules.

        Default-tier fallbacks when day-multiplier values are missing
        match the spec D5: setup 0.5, event 1.0, strike 0.5."""
        for line in self:
            rule = line._find_pricing_rule()
            if not rule:
                line.write({
                    "snapshot_taken": False,
                    "pricing_status": "no_rule",
                })
                _logger.info(
                    "neon.finance.quote.line: no pricing.rule found for "
                    "line %s (category=%s, currency=%s); leaving unit_rate "
                    "at %s for manual entry.",
                    line.name,
                    line.equipment_line_id.category_id.display_name or "(none)",
                    line.currency_id.name or "(none)",
                    line.unit_rate,
                )
                continue

            setup_days, event_days, strike_days = line._decompose_days()
            total_days = setup_days + event_days + strike_days or line.duration_days

            bracket = line._find_bracket(rule, total_days)
            if not bracket:
                line.write({
                    "snapshot_taken": False,
                    "pricing_status": "no_rule",
                })
                _logger.warning(
                    "neon.finance.quote.line: rule %s has no bracket "
                    "covering total_days=%s. Line %s left unpriced.",
                    rule.name, total_days, line.name,
                )
                continue

            mult = line.env["neon.finance.day.multiplier"].sudo().search(
                [("category_id", "=", rule.category_id.id)], limit=1,
            )
            setup_mult = mult.setup_day_multiplier if mult else 0.5
            event_mult = mult.event_day_multiplier if mult else 1.0
            strike_mult = mult.strike_day_multiplier if mult else 0.5

            # Blended per-day rate -- see DECISION marker at module top.
            # weighted_total / total_days gives a single per-day rate
            # that _compute_subtotal can multiply by qty * duration to
            # reach line_subtotal correctly.
            effective_rate = rule.base_rate * bracket.multiplier
            weighted = (
                effective_rate * setup_mult * setup_days
                + effective_rate * event_mult * event_days
                + effective_rate * strike_mult * strike_days
            )
            if total_days <= 0:
                blended = effective_rate * event_mult
            else:
                blended = weighted / total_days

            breakdown = {
                "setup_days": setup_days,
                "event_days": event_days,
                "strike_days": strike_days,
                "base_rate": rule.base_rate,
                "bracket_multiplier": bracket.multiplier,
                "setup_day_multiplier": setup_mult,
                "event_day_multiplier": event_mult,
                "strike_day_multiplier": strike_mult,
                "blended_per_day": blended,
            }

            line.write({
                "unit_rate": blended,
                "duration_days": total_days,
                "bracket_multiplier": bracket.multiplier,
                "day_breakdown_json": json.dumps(breakdown, sort_keys=True),
                "snapshot_taken": True,
                "pricing_status": "priced",
            })
