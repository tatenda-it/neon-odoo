# -*- coding: utf-8 -*-
"""Neon HR R1b-2 — Zimbabwe statutory deduction rules (config-driven).

⚠️ DECISION (Gate 1): Zimbabwe statutory deductions (PAYE / NSSA /
AIDS levy / NEC) are CUSTOM — Odoo CE has no payroll. They are modelled
as CONFIG rows here, NOT hard-coded in the payslip engine. Every seeded
rate is a PLACEHOLDER with ``needs_finance_confirmation = True`` — the
payslip creates the deduction LINE so the structure is right, but the
rate values MUST be confirmed by finance/legal before go-live (the
directive is: do not present an unverified band as truth). PAYE is
progressive (bands) — the flat placeholder here is a stand-in until
finance supplies the current bands.
"""
from odoo import api, fields, models


class NeonHrStatutoryRule(models.Model):
    _name = "neon.hr.statutory.rule"
    _description = "Neon HR Statutory Deduction Rule (Zimbabwe)"
    _order = "sequence, code"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    deduction_type = fields.Selection(
        [("paye", "PAYE (income tax)"),
         ("nssa", "NSSA"),
         ("aids_levy", "AIDS Levy"),
         ("nec", "NEC (where applicable)"),
         ("other", "Other")],
        required=True,
    )
    calc_method = fields.Selection(
        [("percent", "Percent of basis"),
         ("fixed", "Fixed amount")],
        default="percent", required=True,
    )
    rate_percent = fields.Float(
        string="Rate %",
        help="⚠️ PLACEHOLDER pending finance confirmation. PAYE is "
        "banded — this flat rate is a stand-in until current bands are "
        "supplied.",
    )
    fixed_amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.ref("base.USD", raise_if_not_found=False),
    )
    basis = fields.Selection(
        [("gross", "Gross"), ("taxable", "Taxable (gross less exemptions)")],
        default="gross", required=True,
    )
    applies_where_applicable = fields.Boolean(
        help="NEC etc. only apply to certain sectors/categories.",
    )
    needs_finance_confirmation = fields.Boolean(
        string="Rate Pending Finance Confirmation", default=True,
        help="True until finance/legal supplies + signs off the current "
        "figure. Seeded True for every rule.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    note = fields.Text()

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Statutory rule code must be unique."),
    ]

    def _compute_amount(self, basis_amount):
        """Return the deduction amount for a given basis. Used by the
        payslip engine. Flagged rates simply yield a flagged line."""
        self.ensure_one()
        if self.calc_method == "fixed":
            return self.fixed_amount
        return round((basis_amount or 0.0) * (self.rate_percent or 0.0) / 100.0, 2)
