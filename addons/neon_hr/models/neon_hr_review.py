# -*- coding: utf-8 -*-
"""P-HR-R3b C2 -- neon.hr.review (performance reviews).

Lifecycle: draft -> submitted -> acknowledged. perm_unlink=0
(audit-trail rule applies; append-only confidentiality model).
Confidential: visible to the OWNER (employee_user_id), the
REVIEWER, and HR Admin / HR Manager / OD/MD. The OR-rule pattern
mirrors R2 (accident / case / overtime).

⚠️ DECISION (R3b C2, marker 1): rating shape -- simple 1-5 on
three dimensions (overall, technical, conduct) + free-text
comments. Per the gate-1 AMBER default; can be expanded later
without breaking the lifecycle.

⚠️ DECISION (R3b C2, marker 2): reviewer is OD/MD per the
leave-approver pattern. Defaults to the company OD/MD; the
form lets HR Admin reassign. Employee acknowledges separately
(self-acknowledge from their own portal/login).

⚠️ DECISION (R3b C2, marker 3): review_period is a Char
(e.g. "2026-Q2", "2026-H1", "2026-Annual") not a structured
period. The shape varies by review cadence and the team is
still settling on it; a Char keeps the model flexible.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


_REVIEW_STATES = [
    ("draft", "Draft"),
    ("submitted", "Submitted"),
    ("acknowledged", "Acknowledged"),
]


class NeonHrReview(models.Model):
    _name = "neon.hr.review"
    _description = "Employee Performance Review (R3b)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "review_period desc, id desc"
    _rec_name = "display_name"

    # === Identity ===
    display_name = fields.Char(
        compute="_compute_display_name", store=True, index=True)
    employee_id = fields.Many2one(
        "hr.employee", string="Employee",
        required=True, index=True, ondelete="restrict",
        tracking=True)
    employee_user_id = fields.Many2one(
        related="employee_id.user_id", store=True, readonly=True,
        index=True,
        help="The employee's portal user. Drives the OWN-record "
        "rule for self-acknowledgement and confidentiality.")
    review_period = fields.Char(
        string="Review Period", required=True, index=True,
        help="Free-text label, e.g. '2026-Q2' / '2026-H1' / "
        "'2026-Annual'. Char by design (R3b-D3) -- the team is "
        "still settling on the review cadence.")
    reviewer_id = fields.Many2one(
        "res.users", string="Reviewer", required=True,
        index=True, ondelete="restrict", tracking=True,
        help="OD/MD by default; HR Admin can reassign on the "
        "form. The reviewer is the only non-owner who may write "
        "ratings + submit.")

    # === Lifecycle ===
    state = fields.Selection(
        _REVIEW_STATES, required=True, default="draft",
        readonly=True, tracking=True, index=True)

    # === Ratings (R3b-D2: 1-5 on 3 dimensions) ===
    rating_overall = fields.Integer(
        string="Overall Rating",
        help="1 (well below expectations) -- 5 (consistently "
        "exceeds). Required at submit.")
    rating_technical = fields.Integer(
        string="Technical Rating",
        help="Craft / domain skill. 1-5.")
    rating_conduct = fields.Integer(
        string="Conduct Rating",
        help="Professionalism / teamwork / safety culture. 1-5.")

    # === Comments ===
    reviewer_comments = fields.Text(
        string="Reviewer Comments",
        help="Free-text. Required at submit.")
    employee_comments = fields.Text(
        string="Employee Comments",
        help="Filled by the employee at acknowledgement (optional).")

    # === Audit timestamps + actors ===
    submitted_at = fields.Datetime(readonly=True, tracking=True)
    submitted_by_id = fields.Many2one(
        "res.users", readonly=True, tracking=True)
    acknowledged_at = fields.Datetime(readonly=True, tracking=True)
    acknowledged_by_id = fields.Many2one(
        "res.users", readonly=True, tracking=True)

    _sql_constraints = [
        ("rating_overall_range",
         "CHECK (rating_overall IS NULL OR "
         "(rating_overall >= 1 AND rating_overall <= 5))",
         "Overall rating must be 1-5."),
        ("rating_technical_range",
         "CHECK (rating_technical IS NULL OR "
         "(rating_technical >= 1 AND rating_technical <= 5))",
         "Technical rating must be 1-5."),
        ("rating_conduct_range",
         "CHECK (rating_conduct IS NULL OR "
         "(rating_conduct >= 1 AND rating_conduct <= 5))",
         "Conduct rating must be 1-5."),
    ]

    @api.depends("employee_id", "review_period")
    def _compute_display_name(self):
        for rec in self:
            if rec.employee_id and rec.review_period:
                rec.display_name = "%s — %s" % (
                    rec.employee_id.name, rec.review_period)
            else:
                rec.display_name = _("Review")

    # === Lifecycle actions ===
    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_(
                    "Only draft reviews can be submitted. "
                    "Current: %(s)s") % {"s": rec.state})
            if not (rec.rating_overall and rec.reviewer_comments):
                raise UserError(_(
                    "Submit requires at least an overall rating "
                    "and reviewer comments."))
            rec.sudo().write({
                "state": "submitted",
                "submitted_at": fields.Datetime.now(),
                "submitted_by_id": self.env.uid,
            })
        return True

    def action_acknowledge(self):
        for rec in self:
            if rec.state != "submitted":
                raise UserError(_(
                    "Only submitted reviews can be acknowledged. "
                    "Current: %(s)s") % {"s": rec.state})
            # The employee acknowledges -- the user must be the
            # owner OR an HR Admin acknowledging on their behalf.
            user = self.env.user
            is_owner = (rec.employee_user_id
                          and rec.employee_user_id.id == user.id)
            is_hr_admin = user.has_group(
                "neon_hr.group_neon_hr_admin")
            is_super = user.has_group(
                "neon_core.group_neon_superuser")
            if not (is_owner or is_hr_admin or is_super):
                raise UserError(_(
                    "Only the reviewed employee or an HR Admin "
                    "may acknowledge this review."))
            rec.sudo().write({
                "state": "acknowledged",
                "acknowledged_at": fields.Datetime.now(),
                "acknowledged_by_id": self.env.uid,
            })
        return True

    def action_back_to_draft(self):
        """Revoke a submitted review (HR Admin / Reviewer only).
        Acknowledged reviews are append-only -- no walk-back."""
        for rec in self:
            if rec.state == "acknowledged":
                raise UserError(_(
                    "Acknowledged reviews are append-only. To "
                    "amend, create a new review for the same "
                    "period."))
            if rec.state != "submitted":
                raise UserError(_(
                    "Only submitted reviews can be reverted to "
                    "draft."))
            user = self.env.user
            is_reviewer = (rec.reviewer_id
                            and rec.reviewer_id.id == user.id)
            is_hr_admin = user.has_group(
                "neon_hr.group_neon_hr_admin")
            is_super = user.has_group(
                "neon_core.group_neon_superuser")
            if not (is_reviewer or is_hr_admin or is_super):
                raise UserError(_(
                    "Only the reviewer or HR Admin can revert a "
                    "submitted review."))
            rec.sudo().write({
                "state": "draft",
                "submitted_at": False,
                "submitted_by_id": False,
            })
        return True
