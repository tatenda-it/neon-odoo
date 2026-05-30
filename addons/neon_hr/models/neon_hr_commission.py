# -*- coding: utf-8 -*-
"""Neon HR R1b-2 — sales commission (proposed, never auto-paid).

The system PROPOSES 10% (on value after VAT + subcontracted services,
supplied as the base) and routes it for MANUAL approval WITH EVIDENCE —
it is never auto-paid (Q15). State: proposed → under_review → approved
→ paid (+ rejected). Approval requires evidence + OD/MD/Finance
authority. Links to the originating job/sale. Confidential (Q28).
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

COMMISSION_STATES = [
    ("proposed", "Proposed (10%)"),
    ("under_review", "Under Review"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
    ("paid", "Paid"),
]
DEFAULT_RATE = 10.0


class NeonHrCommission(models.Model):
    _name = "neon.hr.commission"
    _description = "Neon HR Sales Commission"
    _inherit = ["mail.thread"]
    _order = "create_date desc, id desc"
    _rec_name = "display_name"

    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="restrict", tracking=True,
        help="The employee/salesperson earning the commission.")
    employee_user_id = fields.Many2one(
        related="employee_id.user_id", store=True, index=True)
    commercial_job_id = fields.Many2one(
        "commercial.job", string="Originating Job", index=True, tracking=True)
    sale_order_id = fields.Many2one(
        "sale.order", string="Originating Sale", index=True)
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.ref("base.USD", raise_if_not_found=False))
    base_amount = fields.Monetary(
        currency_field="currency_id", tracking=True,
        help="Commissionable value AFTER VAT + subcontracted services "
        "(supplied by finance / the sale).")
    rate_percent = fields.Float(
        string="Proposed Rate %", default=DEFAULT_RATE,
        help="System proposes 10% (Q15). Configurable per record.")
    proposed_amount = fields.Monetary(
        compute="_compute_proposed", store=True, currency_field="currency_id")
    approved_amount = fields.Monetary(
        currency_field="currency_id", tracking=True,
        help="The amount actually approved (manual — may differ from "
        "the proposal). Defaults to the proposal on approval.")
    evidence = fields.Text(
        help="Mandatory justification/evidence for approval (Q15).")
    state = fields.Selection(
        COMMISSION_STATES, default="proposed", required=True,
        tracking=True, index=True)
    approver_id = fields.Many2one("res.users", readonly=True, tracking=True)
    approved_at = fields.Datetime(readonly=True)
    rejection_reason = fields.Text()

    @api.depends("base_amount", "rate_percent")
    def _compute_proposed(self):
        for rec in self:
            rec.proposed_amount = round(
                (rec.base_amount or 0.0) * (rec.rate_percent or 0.0) / 100.0, 2)

    @api.depends("employee_id", "commercial_job_id", "state")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s — %s (%s)" % (
                rec.employee_id.name or _("New"),
                rec.commercial_job_id.name or rec.sale_order_id.name or "?",
                dict(COMMISSION_STATES).get(rec.state, rec.state))

    def _check_authority(self):
        if not (self.env.user.has_group("neon_core.group_neon_superuser")
                or self.env.user.has_group(
                    "neon_finance.group_neon_finance_approver")):
            raise AccessError(_(
                "Only OD/MD or a Finance Approver may approve/reject "
                "commission."))

    def action_submit(self):
        for rec in self:
            if rec.state != "proposed":
                raise UserError(_("Only proposed commissions can be submitted."))
            rec.state = "under_review"
        return True

    def action_approve(self):
        """Manual approval — requires evidence + authority. NEVER auto."""
        self._check_authority()
        for rec in self:
            if rec.state not in ("proposed", "under_review"):
                raise UserError(_("Only proposed/under-review can be approved."))
            if not (rec.evidence or "").strip():
                raise UserError(_(
                    "Commission approval requires evidence/justification "
                    "(Q15) — it is never auto-paid."))
            rec.write({
                "state": "approved",
                "approver_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
                "approved_amount": rec.approved_amount or rec.proposed_amount,
            })
            rec.message_post(body=_("Commission approved by %s.")
                             % self.env.user.name)
        return True

    def action_reject(self):
        self._check_authority()
        for rec in self:
            rec.write({"state": "rejected"})
            rec.message_post(body=_("Commission rejected by %s.")
                             % self.env.user.name)
        return True

    def action_pay(self):
        self._check_authority()
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("Only approved commissions can be paid."))
            rec.state = "paid"
        return True
