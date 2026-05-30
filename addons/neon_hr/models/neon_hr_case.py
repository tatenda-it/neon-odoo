# -*- coding: utf-8 -*-
"""Neon HR R2 — disciplinary / incident / performance / recognition cases.

All categories (Q21) with evidence attachments and confidentiality
(record rules: OD/MD/Admin + owner only). Includes the same-day
event-absence path (Q22): a same-day absence escalates to the line
manager → (if warranted) disciplinary → OD clears to resume event
allocation. The clearance is a SIGNAL operations consumes to re-confirm
the crew assignment; it does not re-wire commercial.job.crew here.
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

CASE_TYPES = [
    ("disciplinary", "Disciplinary"),
    ("incident", "Incident"),
    ("performance", "Performance"),
    ("recognition", "Recognition"),
]
CASE_STATES = [
    ("draft", "Draft"),
    ("in_progress", "In Progress"),
    ("resolved", "Resolved"),
    ("closed", "Closed"),
]
ABSENCE_FLOW = [
    ("not_applicable", "Not an event absence"),
    ("escalated_line_manager", "Escalated to Line Manager"),
    ("escalated_disciplinary", "Escalated to Disciplinary"),
    ("od_cleared", "OD Cleared — may resume allocation"),
]


class NeonHrCase(models.Model):
    _name = "neon.hr.case"
    _description = "Neon HR Case (Disciplinary / Incident / Performance / Recognition)"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _rec_name = "display_name"

    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="restrict",
        index=True, tracking=True)
    employee_user_id = fields.Many2one(
        related="employee_id.user_id", store=True, index=True)
    case_type = fields.Selection(
        CASE_TYPES, required=True, default="incident", tracking=True)
    subject = fields.Char(required=True)
    description = fields.Text()
    date = fields.Date(default=fields.Date.context_today, required=True)
    severity = fields.Selection(
        [("low", "Low"), ("medium", "Medium"),
         ("high", "High"), ("critical", "Critical")],
        default="medium", tracking=True)
    attachment_ids = fields.Many2many(
        "ir.attachment", "neon_hr_case_attachment_rel",
        "case_id", "attachment_id", string="Evidence")
    state = fields.Selection(
        CASE_STATES, default="draft", required=True, tracking=True, index=True)
    reported_by_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, tracking=True)
    handled_by_id = fields.Many2one("res.users", tracking=True)
    outcome = fields.Text()

    # ----- same-day event-absence path (Q22) -----
    event_job_id = fields.Many2one(
        "commercial.event.job", string="Affected Event",
        help="Set when this case stems from a same-day event absence.")
    absence_flow = fields.Selection(
        ABSENCE_FLOW, default="not_applicable", tracking=True,
        string="Event-Absence Escalation")

    @api.depends("employee_id", "case_type", "date")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s — %s (%s)" % (
                dict(CASE_TYPES).get(rec.case_type, rec.case_type),
                rec.employee_id.name or _("New"), rec.date or "?")

    # ----- lifecycle -----
    def action_open(self):
        for rec in self:
            rec.write({"state": "in_progress",
                       "handled_by_id": rec.handled_by_id.id or self.env.user.id})
        return True

    def action_resolve(self):
        for rec in self:
            rec.state = "resolved"
        return True

    def action_close(self):
        for rec in self:
            rec.state = "closed"
        return True

    # ----- same-day event-absence escalation -----
    def action_escalate_line_manager(self):
        for rec in self:
            rec.write({"absence_flow": "escalated_line_manager",
                       "state": "in_progress"})
            rec.message_post(body=_("Same-day event absence escalated to "
                                    "line manager."))
        return True

    def action_escalate_disciplinary(self):
        for rec in self:
            rec.write({"absence_flow": "escalated_disciplinary",
                       "case_type": "disciplinary"})
            rec.message_post(body=_("Event absence escalated to "
                                    "disciplinary."))
        return True

    def action_od_clear(self):
        """OD/MD clears the employee to resume event allocation."""
        if not self.env.user.has_group("neon_core.group_neon_superuser"):
            raise AccessError(_(
                "Only OD/MD (Neon Superuser) may clear an event-absence "
                "case to resume allocation."))
        for rec in self:
            if rec.absence_flow == "not_applicable":
                raise UserError(_("This case is not an event-absence case."))
            rec.write({"absence_flow": "od_cleared", "state": "resolved"})
            rec.message_post(body=_(
                "OD cleared %(e)s to resume event allocation%(j)s.") % {
                "e": rec.employee_id.name,
                "j": (" for %s" % rec.event_job_id.name)
                     if rec.event_job_id else ""})
        return True
