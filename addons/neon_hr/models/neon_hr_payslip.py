# -*- coding: utf-8 -*-
"""Neon HR R1b-2 — payslip engine (custom; CE has no payroll).

Salaried employees (permanent / fixed-term / employed techs) draw their
monthly ``wage`` from the contract; freelancers are paid per event (sum
of approved event-wage lines in the period). Gross → deductions
(statutory rules + due loan instalments) → net. State machine:
draft → computed → confirmed → paid. Confidential (Q28): payslips are
visible to OD/MD/Admin + the record owner only (record rules).
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

PAYSLIP_STATES = [
    ("draft", "Draft"),
    ("computed", "Computed"),
    ("confirmed", "Confirmed"),
    ("paid", "Paid"),
]


class NeonHrPayslip(models.Model):
    _name = "neon.hr.payslip"
    _description = "Neon HR Payslip"
    _inherit = ["mail.thread"]
    _order = "period_end desc, employee_id"
    _rec_name = "display_name"

    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="restrict",
        index=True, tracking=True)
    employee_user_id = fields.Many2one(
        "res.users", related="employee_id.user_id", store=True,
        index=True, string="Employee User")
    contract_id = fields.Many2one("hr.contract", tracking=True)
    period_start = fields.Date(required=True, tracking=True)
    period_end = fields.Date(required=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.ref("base.USD", raise_if_not_found=False),
        tracking=True)
    state = fields.Selection(
        PAYSLIP_STATES, default="draft", required=True, tracking=True,
        index=True)
    is_final_pay = fields.Boolean(
        string="Final Pay (exit)", tracking=True,
        help="Tick for an employee's final payslip. Paying is blocked "
        "while the employee has an outstanding loan balance (Q19).")
    line_ids = fields.One2many(
        "neon.hr.payslip.line", "payslip_id", string="Lines")
    gross_amount = fields.Monetary(
        compute="_compute_totals", store=True, currency_field="currency_id")
    total_deductions = fields.Monetary(
        compute="_compute_totals", store=True, currency_field="currency_id")
    net_amount = fields.Monetary(
        compute="_compute_totals", store=True, currency_field="currency_id")
    note = fields.Text()

    @api.depends("line_ids.amount", "line_ids.is_deduction")
    def _compute_totals(self):
        for slip in self:
            earn = sum(l.amount for l in slip.line_ids if not l.is_deduction)
            ded = sum(l.amount for l in slip.line_ids if l.is_deduction)
            slip.gross_amount = earn
            slip.total_deductions = ded
            slip.net_amount = earn - ded

    @api.depends("employee_id", "period_start", "period_end")
    def _compute_display_name(self):
        for slip in self:
            slip.display_name = "%s — %s..%s" % (
                slip.employee_id.name or _("New"),
                slip.period_start or "?", slip.period_end or "?")

    # ----- compute (build lines) -----
    def action_compute(self):
        """(Re)build payslip lines: gross + statutory deductions + due
        loan instalments. Idempotent — clears prior lines first."""
        Line = self.env["neon.hr.payslip.line"]
        Statutory = self.env["neon.hr.statutory.rule"].sudo()
        for slip in self:
            if slip.state not in ("draft", "computed"):
                raise UserError(_(
                    "Only draft/computed payslips can be recomputed."))
            slip.line_ids.unlink()
            vals = []
            seq = 10
            # ----- Gross earnings -----
            contract = slip.contract_id or slip.employee_id.contract_id
            ctype = (contract.neon_contract_type
                     or slip.employee_id.neon_category_id.code)
            if ctype == "freelance_technician":
                # paid per event — sum approved event wages in period
                wages = self.env["neon.hr.event.wage"].sudo().search([
                    ("employee_id", "=", slip.employee_id.id),
                    ("state", "=", "approved"),
                    ("date", ">=", slip.period_start),
                    ("date", "<=", slip.period_end),
                ])
                gross = sum(wages.mapped("amount"))
                vals.append((0, 0, {
                    "name": _("Per-event wages (%d events)") % len(wages),
                    "code": "GROSS_FREELANCE", "category": "basic",
                    "amount": gross, "sequence": seq}))
            else:
                gross = contract.wage if contract else 0.0
                vals.append((0, 0, {
                    "name": _("Monthly salary"), "code": "GROSS_SALARY",
                    "category": "basic", "amount": gross, "sequence": seq}))
            seq += 10
            # ----- Statutory deductions (flagged rates) -----
            for rule in Statutory.search([("active", "=", True)]):
                vals.append((0, 0, {
                    "name": rule.name + (
                        _(" (rate pending finance confirmation)")
                        if rule.needs_finance_confirmation else ""),
                    "code": "STAT_" + (rule.code or "").upper(),
                    "category": "statutory", "is_deduction": True,
                    "amount": rule._compute_amount(gross),
                    "statutory_rule_id": rule.id, "sequence": seq}))
                seq += 10
            # ----- Loan instalments due in period -----
            repayments = self.env["neon.hr.loan.repayment"].sudo().search([
                ("loan_id.employee_id", "=", slip.employee_id.id),
                ("loan_id.state", "=", "active"),
                ("state", "=", "scheduled"),
                ("due_date", ">=", slip.period_start),
                ("due_date", "<=", slip.period_end),
            ])
            for rp in repayments:
                vals.append((0, 0, {
                    "name": _("Loan repayment %s") % (rp.loan_id.display_name or ""),
                    "code": "LOAN", "category": "loan", "is_deduction": True,
                    "amount": rp.amount, "loan_repayment_id": rp.id,
                    "sequence": seq}))
                seq += 10
            slip.write({"line_ids": vals, "state": "computed"})
        return True

    def action_confirm(self):
        for slip in self:
            if slip.state != "computed":
                raise UserError(_("Only computed payslips can be confirmed."))
            slip.state = "confirmed"
            slip.message_post(body=_("Payslip confirmed by %s.")
                              % self.env.user.name)
        return True

    def action_mark_paid(self):
        """Confirmed → paid. Marks the period's loan instalments
        deducted. Q19 final-pay block: refuse if a final pay leaves an
        outstanding loan balance."""
        for slip in self:
            if slip.state != "confirmed":
                raise UserError(_("Only confirmed payslips can be paid."))
            if slip.is_final_pay:
                outstanding = self.env["neon.hr.loan"].sudo().search([
                    ("employee_id", "=", slip.employee_id.id),
                    ("state", "=", "active")])
                bal = sum(outstanding.mapped("balance_amount"))
                slip_loan = sum(
                    l.amount for l in slip.line_ids if l.category == "loan")
                if (bal - slip_loan) > 0.005:
                    raise UserError(_(
                        "Final pay blocked: %(emp)s still owes "
                        "%(bal).2f on staff loan(s). Settle or schedule "
                        "the balance before final pay (Q19)."
                    ) % {"emp": slip.employee_id.name,
                         "bal": bal - slip_loan})
            # mark this period's repayments deducted
            for line in slip.line_ids.filtered(
                    lambda l: l.category == "loan" and l.loan_repayment_id):
                line.loan_repayment_id.action_mark_deducted(slip)
            slip.state = "paid"
            slip.message_post(body=_("Payslip marked paid by %s.")
                              % self.env.user.name)
        return True


class NeonHrPayslipLine(models.Model):
    _name = "neon.hr.payslip.line"
    _description = "Neon HR Payslip Line"
    _order = "payslip_id, sequence, id"

    payslip_id = fields.Many2one(
        "neon.hr.payslip", required=True, ondelete="cascade", index=True)
    employee_user_id = fields.Many2one(
        related="payslip_id.employee_user_id", store=True, index=True)
    name = fields.Char(required=True)
    code = fields.Char()
    category = fields.Selection(
        [("basic", "Basic / Earnings"),
         ("allowance", "Allowance"),
         ("statutory", "Statutory Deduction"),
         ("loan", "Loan Repayment"),
         ("deduction", "Other Deduction")],
        required=True, default="basic")
    is_deduction = fields.Boolean()
    amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        related="payslip_id.currency_id", store=True, readonly=True)
    statutory_rule_id = fields.Many2one("neon.hr.statutory.rule")
    loan_repayment_id = fields.Many2one("neon.hr.loan.repayment")
    sequence = fields.Integer(default=10)
