# -*- coding: utf-8 -*-
"""Neon HR R2 — handbook versions + employee acknowledgements.

Tracks which employees acknowledged which handbook VERSION; surfaces
the non-acknowledged as a compliance flag on the employee. A dedicated
model (not neon.hr.document) because the requirement is version-centric
(one CURRENT handbook everyone must acknowledge), which the per-employee
document checklist does not model.
"""
from odoo import _, api, fields, models


class NeonHrHandbook(models.Model):
    _name = "neon.hr.handbook"
    _description = "Neon HR Handbook Version"
    _order = "publish_date desc, id desc"
    _rec_name = "display_name"

    name = fields.Char(required=True, default="Employee Handbook")
    version = fields.Char(required=True, help="e.g. v3, 2026-01.")
    publish_date = fields.Date(default=fields.Date.context_today)
    is_current = fields.Boolean(
        string="Current Version",
        help="The version all staff must acknowledge. Setting this "
        "unsets it on every other version.")
    attachment_ids = fields.Many2many(
        "ir.attachment", "neon_hr_handbook_attachment_rel",
        "handbook_id", "attachment_id", string="Document")
    active = fields.Boolean(default=True)
    ack_ids = fields.One2many("neon.hr.handbook.ack", "handbook_id")
    ack_count = fields.Integer(compute="_compute_ack_count")

    @api.depends("name", "version")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s %s" % (rec.name or "", rec.version or "")

    @api.depends("ack_ids.state")
    def _compute_ack_count(self):
        for rec in self:
            rec.ack_count = len(rec.ack_ids.filtered(
                lambda a: a.state == "acknowledged"))

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs.filtered("is_current")._enforce_single_current()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if vals.get("is_current"):
            self._enforce_single_current()
        return res

    def _enforce_single_current(self):
        for rec in self:
            (self.search([("is_current", "=", True), ("id", "!=", rec.id)])
             ).write({"is_current": False})

    def action_acknowledge(self, employee=None):
        """Record (or confirm) the current user's / an employee's
        acknowledgement of this handbook version."""
        self.ensure_one()
        Ack = self.env["neon.hr.handbook.ack"].sudo()
        emp = employee or self.env.user.employee_id
        if not emp:
            return False
        ack = Ack.search([("handbook_id", "=", self.id),
                          ("employee_id", "=", emp.id)], limit=1)
        vals = {"state": "acknowledged",
                "acknowledged_date": fields.Date.context_today(self)}
        if ack:
            ack.write(vals)
        else:
            ack = Ack.create(dict(vals, handbook_id=self.id, employee_id=emp.id))
        return ack


class NeonHrHandbookAck(models.Model):
    _name = "neon.hr.handbook.ack"
    _description = "Neon HR Handbook Acknowledgement"
    _order = "handbook_id, employee_id"

    handbook_id = fields.Many2one(
        "neon.hr.handbook", required=True, ondelete="cascade", index=True)
    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="cascade", index=True)
    employee_user_id = fields.Many2one(
        related="employee_id.user_id", store=True, index=True)
    acknowledged_date = fields.Date()
    state = fields.Selection(
        [("pending", "Pending"), ("acknowledged", "Acknowledged")],
        default="pending", required=True, index=True)

    _sql_constraints = [
        ("handbook_emp_uniq", "unique(handbook_id, employee_id)",
         "An acknowledgement already exists for this employee + version."),
    ]


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    handbook_ack_pending = fields.Boolean(
        compute="_compute_handbook_ack_pending",
        help="True when there is a CURRENT handbook this employee has "
        "not acknowledged — a compliance flag.")

    @api.depends_context("uid")
    def _compute_handbook_ack_pending(self):
        current = self.env["neon.hr.handbook"].sudo().search(
            [("is_current", "=", True)], limit=1)
        Ack = self.env["neon.hr.handbook.ack"].sudo()
        for emp in self:
            if not current:
                emp.handbook_ack_pending = False
                continue
            emp.handbook_ack_pending = not Ack.search_count([
                ("handbook_id", "=", current.id),
                ("employee_id", "=", emp.id),
                ("state", "=", "acknowledged")])
