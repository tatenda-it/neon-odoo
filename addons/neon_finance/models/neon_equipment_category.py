# -*- coding: utf-8 -*-
"""
P6.M1 — extend neon.equipment.category with finance fields.

Phase 5 built the category model in `addons/neon_jobs`. Phase 6 adds
cost-tracking semantics: each category declares whether its units
incur a per-line cost (consumable / sub-rental) or fall through as
owned at zero per-line cost (the default for Neon's owned fleet).

Also adds a Monetary companion `currency_id` (defaults to company
currency, USD on this deployment) so consumable_cost_per_unit can
be priced cleanly.

Also overrides create() so every new category auto-spawns its
neon.finance.day.multiplier with the default 1.0 / 0.5 / 0.5 tier
values. Existing categories on first -u get the same backfill via
migrations/17.0.6.0.0/post-migrate.py.
"""
from odoo import _, api, fields, models


_COST_STRATEGIES = [
    ("owned_zero",
     "Owned (no per-line cost)"),
    ("consumable_actual",
     "Consumable (per-use cost)"),
    ("sub_rental_pass_through",
     "Sub-rental (vendor pass-through)"),
]


class NeonEquipmentCategory(models.Model):
    _inherit = "neon.equipment.category"

    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
        help="Currency for consumable_cost_per_unit. Defaults to "
        "company currency (USD on this deployment).",
    )
    cost_strategy = fields.Selection(
        _COST_STRATEGIES,
        string="Cost Strategy",
        default="owned_zero",
        required=True,
        help="Drives quote/cost-line computation in P6.M5. "
        "owned_zero: no per-line cost (Neon-owned fleet). "
        "consumable_actual: charge cost per use. "
        "sub_rental_pass_through: pass vendor invoice cost through.",
    )
    consumable_cost_per_unit = fields.Monetary(
        string="Consumable Cost / Unit",
        currency_field="currency_id",
        default=0.0,
        help="Default per-unit cost when cost_strategy is "
        "'consumable_actual'. Quote lines can override.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # P6.M1 — auto-spawn the day-multiplier row for every new
        # category. Migration handles the backfill for the 9
        # pre-existing categories on first -u.
        DayMultiplier = self.env["neon.finance.day.multiplier"].sudo()
        for cat in records:
            exists = DayMultiplier.search_count(
                [("category_id", "=", cat.id)])
            if not exists:
                DayMultiplier.create({"category_id": cat.id})
        return records
