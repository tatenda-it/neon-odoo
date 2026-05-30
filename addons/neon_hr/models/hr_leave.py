# -*- coding: utf-8 -*-
"""Neon HR R1b-1 — hr.employee leave-approver sync + availability signal.

The employee's native ``leave_manager_id`` (hr_holidays "Time Off
Responsible") is synced from the category's ``leave_approver_id`` so a
manager-validated leave routes to the right OD/MD (Q12). A clean
availability helper exposes whether an employee is free for a window —
the signal Operations + the future B10 scheduler consume (we do NOT
build the scheduler here).
"""
from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    is_available_today = fields.Boolean(
        compute="_compute_is_available_today",
        help="False when the employee has approved (validated) leave "
        "covering today.",
    )

    def _neon_sync_leave_approver(self):
        """Set leave_manager_id from the category's configured OD/MD
        approver. No-op when the category has no approver assigned yet
        (flagged-pending) so we never clear a manually-set responsible."""
        for emp in self:
            approver = emp.neon_category_id.leave_approver_id
            if approver and emp.leave_manager_id != approver:
                emp.leave_manager_id = approver.id

    @api.onchange("neon_category_id")
    def _onchange_neon_category_leave_approver(self):
        approver = self.neon_category_id.leave_approver_id
        if approver:
            self.leave_manager_id = approver

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        employees.filtered("neon_category_id")._neon_sync_leave_approver()
        return employees

    def write(self, vals):
        res = super().write(vals)
        if "neon_category_id" in vals:
            self.filtered("neon_category_id")._neon_sync_leave_approver()
        return res

    # ----- Availability signal (R1 scope; consumed by B10 later) -----
    def _check_available(self, date_from, date_to):
        """Return (available: bool, conflicting hr.leave recordset).
        Unavailable = a VALIDATED leave overlaps [date_from, date_to]
        (inclusive). Dates are plain Date objects."""
        self.ensure_one()
        Leave = self.env["hr.leave"].sudo()
        conflicts = Leave.search([
            ("employee_id", "=", self.id),
            ("state", "=", "validate"),
            ("request_date_from", "<=", date_to),
            ("request_date_to", ">=", date_from),
        ])
        return (not conflicts, conflicts)

    @api.model
    def _get_unavailable_employees(self, date_from, date_to):
        """Operations helper: employees with validated leave overlapping
        the window. Returns hr.employee recordset."""
        leaves = self.env["hr.leave"].sudo().search([
            ("state", "=", "validate"),
            ("request_date_from", "<=", date_to),
            ("request_date_to", ">=", date_from),
        ])
        return leaves.mapped("employee_id")

    @api.depends_context("uid")
    def _compute_is_available_today(self):
        today = fields.Date.context_today(self)
        for emp in self:
            emp.is_available_today = emp._check_available(today, today)[0]
