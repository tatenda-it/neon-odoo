# -*- coding: utf-8 -*-
"""Neon HR R1b-2 — event wages: USD-10 incentive + freelance grades.

Employed techs get a USD-10 per-event incentive kept SEPARATE from
salary and linked to the Event/Job (it is NOT summed into the salaried
payslip). Freelance techs are paid graded fixed rates (USD 50/30/20 by
qualification) — those DO sum into the freelancer's per-event payslip.
Both flow draft → reviewed → approved → paid. The USD-10 figure and the
grade amounts are CONFIG (ir.config_parameter / wage.grade rows), not
hard-coded constants.
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

WAGE_STATES = [
    ("draft", "Draft"),
    ("reviewed", "Reviewed"),
    ("approved", "Approved"),
    ("paid", "Paid"),
]
WAGE_TRANSITIONS = {
    "draft": ["reviewed"],
    "reviewed": ["approved", "draft"],
    "approved": ["paid"],
    "paid": [],
}
INCENTIVE_PARAM = "neon_hr.event_incentive_usd"


class NeonHrWageGrade(models.Model):
    _name = "neon.hr.wage.grade"
    _description = "Neon HR Freelance Wage Grade"
    _order = "sequence, code"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.ref("base.USD", raise_if_not_found=False))
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Wage grade code must be unique."),
    ]


class NeonHrEventWage(models.Model):
    _name = "neon.hr.event.wage"
    _description = "Neon HR Event Wage / Incentive"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _rec_name = "display_name"

    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="restrict", tracking=True)
    employee_user_id = fields.Many2one(
        related="employee_id.user_id", store=True, index=True)
    event_job_id = fields.Many2one(
        "commercial.event.job", required=True, ondelete="restrict",
        index=True, tracking=True,
        help="The Event/Job this wage line is linked to (Part 4).")
    wage_type = fields.Selection(
        [("incentive", "Employed-Tech Incentive (USD 10/event)"),
         ("freelance_grade", "Freelance Graded Rate")],
        required=True, default="incentive", tracking=True)
    grade_id = fields.Many2one(
        "neon.hr.wage.grade", string="Freelance Grade",
        help="Qualification grade (50/30/20) for freelance techs.")
    amount = fields.Monetary(currency_field="currency_id", tracking=True)
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.ref("base.USD", raise_if_not_found=False))
    date = fields.Date(
        required=True, default=fields.Date.context_today,
        help="Wage date — used to match the payslip period for freelancers.")
    state = fields.Selection(
        WAGE_STATES, default="draft", required=True, tracking=True, index=True)
    note = fields.Text()

    @api.depends("employee_id", "event_job_id", "wage_type")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s @ %s (%s)" % (
                rec.employee_id.name or _("New"),
                rec.event_job_id.name or "?",
                dict(WAGE_STATES).get(rec.state, rec.state))

    @api.onchange("wage_type", "grade_id")
    def _onchange_amount(self):
        if self.wage_type == "incentive":
            self.amount = self._incentive_amount()
        elif self.wage_type == "freelance_grade" and self.grade_id:
            self.amount = self.grade_id.amount

    @api.model
    def _incentive_amount(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(
            INCENTIVE_PARAM, "10")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 10.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("amount"):
                if vals.get("wage_type", "incentive") == "incentive":
                    vals["amount"] = self._incentive_amount()
                elif vals.get("grade_id"):
                    vals["amount"] = self.env["neon.hr.wage.grade"].browse(
                        vals["grade_id"]).amount
        return super().create(vals_list)

    def _set_state(self, target):
        for rec in self:
            if target not in WAGE_TRANSITIONS.get(rec.state, []):
                raise UserError(_(
                    "Invalid wage transition %(s)s → %(t)s.")
                    % {"s": rec.state, "t": target})
            if target in ("approved", "paid") and not (
                self.env.user.has_group("neon_core.group_neon_superuser")
                or self.env.user.has_group(
                    "neon_finance.group_neon_finance_approver")):
                raise AccessError(_(
                    "Only OD/MD or a Finance Approver may approve/pay "
                    "event wages."))
            rec.state = target
            rec.message_post(body=_("Wage moved to %s by %s.")
                             % (target, self.env.user.name))
        return True

    def action_review(self):
        return self._set_state("reviewed")

    def action_approve(self):
        return self._set_state("approved")

    def action_pay(self):
        return self._set_state("paid")
