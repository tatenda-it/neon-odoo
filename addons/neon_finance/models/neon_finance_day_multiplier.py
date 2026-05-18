# -*- coding: utf-8 -*-
"""
P6.M1 — per-category tiered day-type multipliers.

Drives the Q1 A3 tiered day-rate model: each category declares its
own setup-day and strike-day rate relative to the event-day rate.
Event day is the full-rate baseline (typically 1.00); setup and
strike are usually half-rate (0.50) but per-category overridable
because, for example, Trussing rigging crew time costs differently
from a Sound desk standing in place.

One row per category. Auto-created on category create (override
in addons/neon_finance/models/neon_equipment_category.py). Existing
categories backfilled by migrations/17.0.6.0.0/post-migrate.py.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class NeonFinanceDayMultiplier(models.Model):
    _name = "neon.finance.day.multiplier"
    _description = "Finance Day-Type Multiplier"
    _order = "category_id"
    _rec_name = "category_id"

    category_id = fields.Many2one(
        "neon.equipment.category",
        string="Category",
        required=True,
        ondelete="cascade",
        index=True,
    )
    event_day_multiplier = fields.Float(
        required=True,
        default=1.00,
        digits=(8, 4),
        help="Multiplier applied to the per-day rate on event days. "
        "1.00 = full rate.",
    )
    setup_day_multiplier = fields.Float(
        required=True,
        default=0.50,
        digits=(8, 4),
    )
    strike_day_multiplier = fields.Float(
        required=True,
        default=0.50,
        digits=(8, 4),
    )
    notes = fields.Text()

    _sql_constraints = [
        ("unique_category",
         "UNIQUE (category_id)",
         "Each category may have only one day-multiplier row."),
        ("check_event_non_negative",
         "CHECK (event_day_multiplier >= 0)",
         "Event day multiplier must be zero or positive."),
        ("check_setup_non_negative",
         "CHECK (setup_day_multiplier >= 0)",
         "Setup day multiplier must be zero or positive."),
        ("check_strike_non_negative",
         "CHECK (strike_day_multiplier >= 0)",
         "Strike day multiplier must be zero or positive."),
    ]

    @api.constrains("event_day_multiplier",
                    "setup_day_multiplier",
                    "strike_day_multiplier")
    def _check_multipliers_non_negative(self):
        # Belt + braces alongside the SQL CHECK so ORM-side writes
        # raise ValidationError (the Python-friendly error type)
        # instead of psycopg2 IntegrityError. T506 in p6m1_smoke
        # expects ValidationError.
        for rec in self:
            for fname in ("event_day_multiplier",
                          "setup_day_multiplier",
                          "strike_day_multiplier"):
                if rec[fname] < 0:
                    raise ValidationError(_(
                        "%(field)s on %(cat)s must be zero or "
                        "positive (got %(val)s)."
                    ) % {
                        "field": fname,
                        "cat": rec.category_id.display_name,
                        "val": rec[fname],
                    })
