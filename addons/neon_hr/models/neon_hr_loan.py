# -*- coding: utf-8 -*-
"""Neon HR R1b-2 — staff loans + instalment repayment schedule (Q19).

Loans are allowed with instalment repayment, deducted from pay. A loan
record carries a generated repayment schedule; balance is principal
less deducted instalments; the payslip blocks a FINAL pay while a
balance is outstanding. Max amount is CONFIG (ir.config_parameter
neon_hr.loan_max_usd, default 0 = open, awaiting policy). Confidential
(Q28).
"""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

LOAN_STATES = [
    ("draft", "Draft"),
    ("approved", "Approved"),
    ("active", "Active (repaying)"),
    ("settled", "Settled"),
    ("cancelled", "Cancelled"),
]
LOAN_MAX_PARAM = "neon_hr.loan_max_usd"


class NeonHrLoan(models.Model):
    _name = "neon.hr.loan"
    _description = "Neon HR Staff Loan"
    _inherit = ["mail.thread"]
    _order = "create_date desc, id desc"
    _rec_name = "display_name"

    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="restrict", tracking=True)
    employee_user_id = fields.Many2one(
        related="employee_id.user_id", store=True, index=True)
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.ref("base.USD", raise_if_not_found=False))
    principal_amount = fields.Monetary(
        currency_field="currency_id", required=True, tracking=True)
    instalment_count = fields.Integer(
        string="Instalments", default=1, required=True, tracking=True)
    instalment_amount = fields.Monetary(
        compute="_compute_instalment", store=True, currency_field="currency_id")
    start_date = fields.Date(
        default=fields.Date.context_today, required=True, tracking=True)
    state = fields.Selection(
        LOAN_STATES, default="draft", required=True, tracking=True, index=True)
    repayment_ids = fields.One2many(
        "neon.hr.loan.repayment", "loan_id", string="Repayments")
    total_repaid = fields.Monetary(
        compute="_compute_balance", store=True, currency_field="currency_id")
    balance_amount = fields.Monetary(
        compute="_compute_balance", store=True, currency_field="currency_id")
    reason = fields.Text()

    @api.depends("principal_amount", "instalment_count")
    def _compute_instalment(self):
        for loan in self:
            n = loan.instalment_count or 1
            loan.instalment_amount = round((loan.principal_amount or 0.0) / n, 2)

    @api.depends("repayment_ids.amount", "repayment_ids.state",
                 "principal_amount")
    def _compute_balance(self):
        for loan in self:
            repaid = sum(r.amount for r in loan.repayment_ids
                         if r.state == "deducted")
            loan.total_repaid = repaid
            loan.balance_amount = (loan.principal_amount or 0.0) - repaid

    @api.depends("employee_id", "principal_amount", "state")
    def _compute_display_name(self):
        for loan in self:
            loan.display_name = "%s — %.2f %s (%s)" % (
                loan.employee_id.name or _("New"),
                loan.principal_amount or 0.0,
                loan.currency_id.name or "",
                dict(LOAN_STATES).get(loan.state, loan.state))

    def _check_max(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(
            LOAN_MAX_PARAM, "0")
        try:
            cap = float(raw)
        except (TypeError, ValueError):
            cap = 0.0
        if cap > 0:
            for loan in self:
                if (loan.principal_amount or 0.0) > cap:
                    raise UserError(_(
                        "Loan principal %(p).2f exceeds the configured "
                        "maximum %(c).2f (neon_hr.loan_max_usd)."
                    ) % {"p": loan.principal_amount, "c": cap})

    def action_approve(self):
        self._check_max()
        for loan in self:
            if loan.state != "draft":
                raise UserError(_("Only draft loans can be approved."))
            loan.state = "approved"
        return True

    def action_activate(self):
        """Generate the instalment schedule and start repaying."""
        Repay = self.env["neon.hr.loan.repayment"]
        for loan in self:
            if loan.state not in ("approved", "draft"):
                raise UserError(_("Only approved loans can be activated."))
            loan.repayment_ids.unlink()
            n = loan.instalment_count or 1
            base = round((loan.principal_amount or 0.0) / n, 2)
            rows = []
            allocated = 0.0
            for i in range(n):
                amt = base if i < n - 1 else round(
                    (loan.principal_amount or 0.0) - allocated, 2)
                allocated += amt
                rows.append((0, 0, {
                    "sequence": i + 1,
                    "due_date": (loan.start_date or fields.Date.context_today(
                        self)) + relativedelta(months=i),
                    "amount": amt,
                }))
            loan.write({"repayment_ids": rows, "state": "active"})
        return True

    def action_settle(self):
        for loan in self:
            loan.state = "settled"
        return True

    def action_cancel(self):
        for loan in self:
            loan.state = "cancelled"
        return True


class NeonHrLoanRepayment(models.Model):
    _name = "neon.hr.loan.repayment"
    _description = "Neon HR Loan Repayment Instalment"
    _order = "loan_id, sequence"

    loan_id = fields.Many2one(
        "neon.hr.loan", required=True, ondelete="cascade", index=True)
    employee_user_id = fields.Many2one(
        related="loan_id.employee_user_id", store=True, index=True)
    sequence = fields.Integer(default=1)
    due_date = fields.Date(required=True)
    amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        related="loan_id.currency_id", store=True, readonly=True)
    state = fields.Selection(
        [("scheduled", "Scheduled"),
         ("deducted", "Deducted"),
         ("waived", "Waived")],
        default="scheduled", required=True, index=True)
    payslip_id = fields.Many2one("neon.hr.payslip", readonly=True)
    deducted_date = fields.Date(readonly=True)

    def action_mark_deducted(self, payslip=None):
        for rp in self:
            rp.write({
                "state": "deducted",
                "payslip_id": payslip.id if payslip else False,
                "deducted_date": fields.Date.context_today(self),
            })
            if rp.loan_id.balance_amount <= 0.005:
                rp.loan_id.state = "settled"
        return True
