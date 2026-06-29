# -*- coding: utf-8 -*-
from odoo import api, fields, models


class NeonShadowScoringRule(models.Model):
    """Data-driven shadow scoring rule (2B).

    Rules are DATA, not code, so they can be tuned against live data after the
    cutover without a redeploy. Each rule awards points to a lead when its
    condition matches; the lead's shadow_score is the sum of matched points.

    SHADOW ONLY: nothing here writes to the live x_lead_score. Seeded rules are
    PLACEHOLDERS (see data file) and must be tuned once real data exists.
    """

    _name = "neon.shadow.scoring.rule"
    _description = "Neon Shadow Scoring Rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    field_name = fields.Char(
        string="Lead Field",
        required=True,
        help="Technical name of a crm.lead field to test (e.g. neon_sector).",
    )
    operator = fields.Selection(
        [
            ("set", "Is set"),
            ("not_set", "Is not set"),
            ("equals", "Equals value"),
            ("not_equals", "Does not equal value"),
            ("gt", "Greater than value"),
            ("lt", "Less than value"),
        ],
        string="Condition",
        default="set",
        required=True,
    )
    value = fields.Char(
        string="Compare Value",
        help="Used by equals / not_equals / gt / lt.",
    )
    points = fields.Integer(default=0)
    note = fields.Char(string="Rationale", help="Shown in the AI reason trace.")

    def _matches(self, lead):
        """Return True if this rule's condition holds for `lead`. Type-tolerant
        and guarded so a stale field name never raises."""
        self.ensure_one()
        if self.field_name not in lead._fields:
            return False
        current = lead[self.field_name]
        # Normalise m2o to its id for comparison.
        if hasattr(current, "id") and not isinstance(current, (int, bool, str, float)):
            current = current.id if current else False
        op = self.operator
        if op == "set":
            return bool(current)
        if op == "not_set":
            return not bool(current)
        cmp_val = self.value
        if op in ("gt", "lt"):
            try:
                cur_f = float(current or 0)
                cmp_f = float(cmp_val)
            except (TypeError, ValueError):
                return False
            return cur_f > cmp_f if op == "gt" else cur_f < cmp_f
        # equals / not_equals (string compare, tolerant)
        cur_s = "" if current in (False, None) else str(current)
        eq = cur_s == (cmp_val or "")
        return eq if op == "equals" else not eq

    @api.model
    def _score_lead(self, lead):
        """Sum matched points + collect rationale lines. Returns (score, reasons)."""
        score = 0
        reasons = []
        for rule in self.search([]):
            if rule._matches(lead):
                score += rule.points
                reasons.append("+%d %s" % (rule.points, rule.note or rule.name))
        return score, reasons
