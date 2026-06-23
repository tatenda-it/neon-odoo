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
    # ⚠️ DECISION (B14c, D1): quantity_on_hand lives on
    # product.template (one number per product) per the D1 follow-
    # up spec. Semantically meaningful ONLY for tracking_mode in
    # ('quantity', 'batch'). For serial products the count comes
    # from len(equipment_unit_ids filtered to good + active) -- the
    # serial path is unchanged.
    quantity_on_hand = fields.Integer(
        string="Quantity On Hand",
        default=0,
        help="Total physical count on hand for quantity/batch-"
        "tracked products. For serial-tracked products, "
        "availability is computed from per-unit rows -- this field "
        "is ignored. Populated by the B14b legacy migration via "
        "the B14c back-fill script that parses 'legacy_qty=N' from "
        "unit notes.",
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
    # ============================================================
    # === UX-B-RATE — catalogue hire rate (display-only)
    # The engine prices quote lines via neon.finance.pricing.rule
    # (base_rate, the "Day-1 Base Rate"); product.list_price is the
    # misleading $1 default the engine ignores (Solution B hides it for
    # workshop items). This surfaces the REAL day-1 USD rate on the
    # catalogue, resolved through the SAME product-rule -> category-
    # fallback path the quote line uses. Display-only: no engine / quote
    # / list_price change; the quote line still computes the exact per-
    # line unit_rate on product pick.
    # ============================================================
    neon_unit_rate_currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_neon_unit_rate",
        help="USD -- the catalogue hire-rate display currency.",
    )
    neon_unit_rate = fields.Monetary(
        string="Hire rate (USD/day)",
        compute="_compute_neon_unit_rate",
        currency_field="neon_unit_rate_currency_id",
        help="The standard day-1 hire rate (USD) resolved from the "
        "pricing rules -- the per-product rule first, else the "
        "equipment category rule. This is the per-day rate a 1-day USD "
        "quote line populates; multi-day hires taper via the bracket "
        "multipliers and non-USD quotes resolve a different rule, so the "
        "quote line shows the exact rate. Blank when no pricing rule "
        "covers this product yet.",
    )
    neon_unit_rate_has_rule = fields.Boolean(
        compute="_compute_neon_unit_rate",
        help="True when a USD pricing rule (product or category) "
        "resolves -- drives whether the catalogue shows the rate or the "
        "'set via Pricing Rules' hint.",
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

    @api.depends("equipment_category_id")
    def _compute_neon_unit_rate(self):
        """Resolve the day-1 USD hire rate for the catalogue, mirroring the
        line engine's _find_pricing_rule tiers: PRIMARY per-product rule, then
        the CATEGORY fallback (via equipment_category_id), USD, latest
        effective_date <= today. Display-only. sudo so a Sales user (read-only
        ACL on pricing.rule, per P6.M1) still resolves. NON-STORED -> recomputed
        live so it never goes stale as rules / the effective date roll."""
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        Rule = self.env["neon.finance.pricing.rule"].sudo()
        today = fields.Date.context_today(self)
        for rec in self:
            rec.neon_unit_rate_currency_id = usd
            rule = self.env["neon.finance.pricing.rule"]
            if usd and rec.id:
                # 1) per-product rule (PRIMARY)
                rule = Rule.search([
                    ("product_template_id", "=", rec.id),
                    ("currency_id", "=", usd.id),
                    ("active", "=", True),
                    ("effective_date", "<=", today),
                ], order="effective_date desc, id desc", limit=1)
                # 2) category rule (fallback) via equipment_category_id
                if not rule and rec.equipment_category_id:
                    rule = Rule.search([
                        ("product_template_id", "=", False),
                        ("category_id", "=", rec.equipment_category_id.id),
                        ("currency_id", "=", usd.id),
                        ("active", "=", True),
                        ("effective_date", "<=", today),
                    ], order="effective_date desc, id desc", limit=1)
            rec.neon_unit_rate = rule.base_rate if rule else 0.0
            rec.neon_unit_rate_has_rule = bool(rule)

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
