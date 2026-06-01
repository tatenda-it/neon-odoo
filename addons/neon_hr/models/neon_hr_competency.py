# -*- coding: utf-8 -*-
"""Neon HR R3a — competency catalog, per-employee competencies, and the
role -> competency requirement map that drives the crew-assignment gate.

* ``neon.hr.competency``          — catalog of skills/certs. Seeded
                                    EMPTY (ops populate). Internal-read.
* ``neon.hr.employee.competency`` — one row per (employee, competency),
                                    optional expiry. Confidential (owner
                                    + OD/MD/Admin). perm_unlink=0.
* ``neon.hr.role.competency``     — maps a crew role to the competencies
                                    it requires. Seeded EMPTY + flagged
                                    for ops (Gate-1 open item).
"""
from datetime import timedelta

from odoo import _, api, fields, models

# Crew roles mirror commercial.job.crew.role. Kept in sync by hand — a
# related selection would couple the two modules' field internals.
CREW_ROLE_SELECTION = [
    ("lead_tech", "Lead Tech"),
    ("tech", "Tech"),
    ("runner", "Runner"),
    ("driver", "Driver"),
    ("other", "Other"),
]


class NeonHrCompetency(models.Model):
    _name = "neon.hr.competency"
    _description = "Neon HR Competency (Skill / Certification)"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, help="Stable technical key.")
    sequence = fields.Integer(default=10)
    requires_expiry = fields.Boolean(
        string="Has Expiry",
        help="Tick for competencies that lapse (first-aid cert, "
        "working-at-heights, etc.). Such competencies flip to 'expired' "
        "past their expiry date and break the assignment gate until "
        "renewed.")
    active = fields.Boolean(default=True)
    description = fields.Text()

    _sql_constraints = [
        ("code_uniq", "unique(code)",
         "A competency with this code already exists."),
    ]


class NeonHrEmployeeCompetency(models.Model):
    _name = "neon.hr.employee.competency"
    _description = "Neon HR Employee Competency"
    _inherit = ["mail.thread"]
    _order = "employee_id, competency_id"
    _rec_name = "display_name"

    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="cascade",
        index=True, tracking=True)
    employee_user_id = fields.Many2one(
        "res.users", related="employee_id.user_id", store=True,
        index=True, string="Employee User")
    competency_id = fields.Many2one(
        "neon.hr.competency", required=True, ondelete="restrict",
        tracking=True)
    requires_expiry = fields.Boolean(
        related="competency_id.requires_expiry", store=True)
    attained_date = fields.Date(tracking=True)
    expiry_date = fields.Date(tracking=True)
    attachment_ids = fields.Many2many(
        "ir.attachment", "neon_hr_emp_competency_attachment_rel",
        "emp_competency_id", "attachment_id", string="Evidence")
    state = fields.Selection(
        [("valid", "Valid"),
         ("expiring", "Expiring Soon"),
         ("expired", "Expired")],
        compute="_compute_state", store=True, tracking=True, index=True)
    is_expired = fields.Boolean(compute="_compute_state", store=True)
    notes = fields.Text()

    _sql_constraints = [
        ("employee_competency_uniq",
         "unique(employee_id, competency_id)",
         "This competency is already recorded for the employee."),
    ]

    @api.depends("expiry_date", "requires_expiry")
    def _compute_state(self):
        today = fields.Date.context_today(self)
        lead = self.env["neon.hr.licence"]._licence_lead_days()
        horizon = today + timedelta(days=lead)
        for rec in self:
            if not rec.requires_expiry or not rec.expiry_date:
                rec.state = "valid"
                rec.is_expired = False
            elif rec.expiry_date < today:
                rec.state = "expired"
                rec.is_expired = True
            elif rec.expiry_date <= horizon:
                rec.state = "expiring"
                rec.is_expired = False
            else:
                rec.state = "valid"
                rec.is_expired = False

    @api.depends("employee_id", "competency_id")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s — %s" % (
                rec.employee_id.name or _("New"),
                rec.competency_id.name or _("Competency"))

    @api.model
    def _cron_refresh_states(self):
        recs = self.sudo().search([("requires_expiry", "=", True),
                                   ("expiry_date", "!=", False)])
        if recs:
            recs.modified(["expiry_date"])
            recs._compute_state()
        return True


class NeonHrRoleCompetency(models.Model):
    _name = "neon.hr.role.competency"
    _description = "Neon HR Role -> Competency Requirement"
    _order = "crew_role"
    _rec_name = "display_name"

    crew_role = fields.Selection(
        CREW_ROLE_SELECTION, required=True, string="Crew Role")
    competency_ids = fields.Many2many(
        "neon.hr.competency", string="Required Competencies")
    active = fields.Boolean(default=True)
    note = fields.Text(
        help="Ops note. The role->competency map ships EMPTY; populate "
        "it to start gating a role on competencies.")

    _sql_constraints = [
        ("crew_role_uniq", "unique(crew_role)",
         "A requirement row for this crew role already exists."),
    ]

    @api.depends("crew_role")
    def _compute_display_name(self):
        roles = dict(CREW_ROLE_SELECTION)
        for rec in self:
            rec.display_name = roles.get(rec.crew_role) or _("Role")
