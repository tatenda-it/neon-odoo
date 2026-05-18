# -*- coding: utf-8 -*-
"""
P6.M1 — multi-day bracket multipliers within a pricing rule.

Each bracket says: for total event days N where day_from <= N <= day_to
(or N >= day_from if day_to == -1), apply multiplier to the rule's
base_rate to get the per-day price.

Constraints enforced at write-time:
  - day_from must be a positive integer
  - day_to must be >= day_from OR exactly -1 (open-ended tail)
  - multiplier must be non-negative
  - no two brackets on the same rule may overlap
  - at most one bracket per rule may have day_to == -1

NOT enforced at write-time:
  - contiguous coverage starting at day_from=1. Coverage gaps are
    legitimate during multi-step editing; the pricing-engine compute
    in P6.M3 fails loud when a quote falls into a gap. Validating
    coverage on every bracket write would force a specific create
    order and break edit-in-place workflows.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class NeonFinancePricingBracket(models.Model):
    _name = "neon.finance.pricing.bracket"
    _description = "Finance Pricing Bracket"
    _order = "rule_id, sequence, day_from, id"

    rule_id = fields.Many2one(
        "neon.finance.pricing.rule",
        string="Rule",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    day_from = fields.Integer(
        string="From Day",
        required=True,
        help="First event-day this bracket applies to (1-indexed).",
    )
    day_to = fields.Integer(
        string="To Day",
        required=True,
        help="Last event-day this bracket applies to. Use -1 for "
        "an open-ended tail (e.g. 15+ days).",
    )
    multiplier = fields.Float(
        required=True,
        digits=(8, 4),
        help="Per-day rate multiplier applied to the rule's "
        "base_rate. Typically between 0.0 and 1.0.",
    )

    _sql_constraints = [
        ("check_day_from_positive",
         "CHECK (day_from >= 1)",
         "Bracket day_from must be 1 or greater."),
        ("check_day_to_valid",
         "CHECK (day_to = -1 OR day_to >= day_from)",
         "Bracket day_to must be -1 (open-ended) or >= day_from."),
        ("check_multiplier_non_negative",
         "CHECK (multiplier >= 0)",
         "Bracket multiplier must be zero or positive."),
    ]

    @api.constrains("day_from", "day_to")
    def _check_day_to_valid(self):
        # Belt + braces alongside the SQL CHECK so ORM-side writes
        # raise ValidationError. T502 in p6m1_smoke expects this
        # Python-friendly error type.
        for rec in self:
            if rec.day_to != -1 and rec.day_to < rec.day_from:
                raise ValidationError(_(
                    "Bracket day_to (%(to)s) must be -1 or >= "
                    "day_from (%(fr)s)."
                ) % {"to": rec.day_to, "fr": rec.day_from})

    @api.constrains("rule_id", "day_from", "day_to")
    def _check_no_overlap_within_rule(self):
        for rec in self:
            if not rec.rule_id:
                continue
            peers = self.search([
                ("rule_id", "=", rec.rule_id.id),
                ("id", "!=", rec.id),
            ])
            for peer in peers:
                if _ranges_overlap(rec.day_from, rec.day_to,
                                   peer.day_from, peer.day_to):
                    raise ValidationError(_(
                        "Bracket [%(a_from)s..%(a_to)s] overlaps "
                        "with existing bracket [%(b_from)s..%(b_to)s] "
                        "on rule %(rule)s. Each event-day count "
                        "must map to exactly one bracket."
                    ) % {
                        "a_from": rec.day_from, "a_to": rec.day_to,
                        "b_from": peer.day_from, "b_to": peer.day_to,
                        "rule": rec.rule_id.display_name,
                    })

    @api.constrains("rule_id", "day_to")
    def _check_single_open_ended_tail(self):
        for rec in self:
            if rec.day_to != -1 or not rec.rule_id:
                continue
            tails = self.search_count([
                ("rule_id", "=", rec.rule_id.id),
                ("day_to", "=", -1),
            ])
            if tails > 1:
                raise ValidationError(_(
                    "Rule %s already has an open-ended tail bracket "
                    "(day_to = -1). Only one is allowed."
                ) % rec.rule_id.display_name)


def _ranges_overlap(a_from, a_to, b_from, b_to):
    """Treat day_to == -1 as +infinity for the overlap test."""
    INF = 10 ** 9
    a_hi = INF if a_to == -1 else a_to
    b_hi = INF if b_to == -1 else b_to
    return a_from <= b_hi and b_from <= a_hi
