# -*- coding: utf-8 -*-
"""Neon HR — hr.employee extension (employee master).

⚠️ DECISION (B1-style, Gate 1): EXTEND Odoo ``hr.employee`` rather
than define a standalone ``neon.employee``. Rationale: hr.employee
already carries the personal/contact/identity/banking/emergency
fields (most behind groups="hr.group_hr_user", i.e. already
confidential), and inheriting it gives R1b the whole hr.contract /
hr_holidays / payroll ecosystem for free. We add only the
Neon-specific gaps here: category, statutory numbers, employment
status, the document-compliance checklist and the assignment gate.
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # ----- Classification -------------------------------------------
    neon_category_id = fields.Many2one(
        "neon.hr.category", string="Neon Category", tracking=True,
        help="Drives the required-document set, default pay type and "
        "(R1b) leave/payroll defaults.",
    )
    neon_employment_status = fields.Selection(
        [("probation", "On Probation"),
         ("active", "Active"),
         ("suspended", "Suspended"),
         ("notice", "On Notice"),
         ("exited", "Exited")],
        string="Employment Status", default="active", tracking=True,
    )

    # ----- Zimbabwe statutory (confidential — hr.group_hr_user) ------
    nssa_number = fields.Char(
        string="NSSA Number", groups="hr.group_hr_user", tracking=True,
        help="National Social Security Authority registration number.",
    )
    zimra_tin = fields.Char(
        string="ZIMRA TIN", groups="hr.group_hr_user", tracking=True,
        help="Zimbabwe Revenue Authority Taxpayer Identification "
        "Number.",
    )

    # ----- Compliance checklist -------------------------------------
    document_ids = fields.One2many(
        "neon.hr.document", "employee_id", string="Documents",
    )
    document_count = fields.Integer(compute="_compute_document_stats")
    is_compliant = fields.Boolean(
        compute="_compute_document_stats", store=True, tracking=True,
        help="True only when every document required by the "
        "employee's category is provided and unexpired.",
    )
    compliance_summary = fields.Char(compute="_compute_document_stats")

    # ----- Assignment gate (Q6 — soft block) ------------------------
    has_valid_contract = fields.Boolean(
        compute="_compute_has_valid_contract", store=True,
        help="True when an open contract exists whose end date is "
        "empty or in the future.",
    )
    assignment_override = fields.Boolean(
        string="Assignment Block Overridden",
        tracking=True,
        help="When set, the soft assignment block is bypassed. Only "
        "OD/MD may set this (Q6 default — override authority pending "
        "confirmation).",
    )

    # ----------------------------------------------------------------
    @api.depends(
        "neon_category_id",
        "neon_category_id.required_document_type_ids",
        "document_ids.state",
        "document_ids.document_type_id",
    )
    def _compute_document_stats(self):
        for emp in self:
            emp.document_count = len(emp.document_ids)
            required = emp.neon_category_id.required_document_type_ids
            if not emp.neon_category_id:
                emp.is_compliant = False
                emp.compliance_summary = _("No category assigned")
                continue
            provided_types = emp.document_ids.filtered(
                lambda d: d.state == "provided"
            ).mapped("document_type_id")
            missing = required - provided_types
            emp.is_compliant = not missing
            emp.compliance_summary = _(
                "%(p)s/%(t)s required documents provided"
            ) % {"p": len(required) - len(missing), "t": len(required)}

    @api.depends("contract_ids.state", "contract_ids.date_end")
    def _compute_has_valid_contract(self):
        today = fields.Date.context_today(self)
        for emp in self:
            valid = emp.contract_ids.filtered(
                lambda c: c.state == "open"
                and (not c.date_end or c.date_end >= today)
            )
            emp.has_valid_contract = bool(valid)

    # ----- Checklist generation -------------------------------------
    def _sync_compliance_documents(self):
        """Create missing checklist rows for the category's required
        document types. Existing rows are never deleted (perm_unlink=0
        audit discipline) — a category change only ADDS the newly
        required types; superseded ones simply stop counting toward
        compliance. Uses a single batched create per project memory on
        batch-create constraint timing."""
        Doc = self.env["neon.hr.document"]
        vals_list = []
        for emp in self:
            required = emp.neon_category_id.required_document_type_ids
            existing = emp.document_ids.mapped("document_type_id")
            for dtype in (required - existing):
                vals_list.append({
                    "employee_id": emp.id,
                    "document_type_id": dtype.id,
                })
        if vals_list:
            Doc.create(vals_list)

    def action_generate_checklist(self):
        self._sync_compliance_documents()
        return True

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        employees.filtered("neon_category_id")._sync_compliance_documents()
        return employees

    def write(self, vals):
        res = super().write(vals)
        if "neon_category_id" in vals:
            self.filtered("neon_category_id")._sync_compliance_documents()
        return res

    # ----- Assignment gate (Q6) -------------------------------------
    def _check_assignable(self):
        """Return (assignable: bool, reason: str). A missing or
        expired contract is a SOFT block — callers warn and allow an
        OD/MD override; they must not hard-raise."""
        self.ensure_one()
        if self.assignment_override:
            return True, _("Assignment block overridden by OD/MD.")
        if not self.contract_ids:
            return False, _("No contract on file for this employee.")
        if not self.has_valid_contract:
            return False, _(
                "No active contract — the latest contract is missing, "
                "draft, or past its end date.")
        return True, _("Employee has a valid active contract.")

    def action_assignment_gate(self):
        """User-facing soft check. Returns a (non-blocking) warning
        notification when blocked rather than raising — the block is
        advisory."""
        self.ensure_one()
        assignable, reason = self._check_assignable()
        if assignable:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "success",
                    "title": _("Assignable"),
                    "message": reason,
                    "sticky": False,
                },
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "warning",
                "title": _("Soft block — assignment not recommended"),
                "message": _(
                    "%(reason)s OD/MD may override on the employee "
                    "record to proceed.") % {"reason": reason},
                "sticky": True,
            },
        }

    def action_override_assignment(self):
        """OD/MD-only override of the soft assignment block (Q6)."""
        self.ensure_one()
        if not self.env.user.has_group(
                "neon_core.group_neon_superuser"):
            raise AccessError(_(
                "Only OD/MD (Neon Superuser) may override the "
                "assignment block. (Override authority Q6 — pending "
                "confirmation.)"))
        self.assignment_override = True
        self.message_post(body=_(
            "Assignment soft-block overridden by %(user)s."
        ) % {"user": self.env.user.name})
        return True
