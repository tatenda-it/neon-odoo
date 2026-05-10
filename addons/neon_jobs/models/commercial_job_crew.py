# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class CommercialJobCrew(models.Model):
    _name = "commercial.job.crew"
    _description = "Commercial Job Crew Assignment"
    _inherit = ["mail.thread"]
    _order = "job_id desc, role, id"

    job_id = fields.Many2one(
        "commercial.job",
        string="Commercial Job",
        required=True,
        ondelete="cascade",
        tracking=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Crew Member",
        required=True,
        tracking=True,
    )
    role = fields.Selection(
        [
            ("lead_tech", "Lead Tech"),
            ("tech", "Tech"),
            ("runner", "Runner"),
            ("driver", "Driver"),
            ("other", "Other"),
        ],
        string="Role",
        default="tech",
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("pending", "Pending Confirmation"),
            ("confirmed", "Confirmed"),
            ("declined", "Declined"),
        ],
        string="Confirmation",
        default="pending",
        required=True,
        tracking=True,
    )
    assigned_on = fields.Datetime(
        string="Assigned On",
        default=fields.Datetime.now,
        readonly=True,
    )
    responded_on = fields.Datetime(
        string="Responded On",
        readonly=True,
        tracking=True,
    )
    decline_reason = fields.Text(
        string="Decline Reason",
        tracking=True,
        help="Required when state = declined. Triggers MD/OD reassignment activity.",
    )
    notification_sent = fields.Boolean(
        string="Notification Sent",
        default=False,
        help="Set to True once Odoo activity + WhatsApp message dispatched. "
        "Notification logic implemented in P2.M2+.",
    )

    # Convenience related fields for the tree view
    job_event_date = fields.Date(
        related="job_id.event_date",
        string="Event Date",
        store=True,
    )
    job_partner_id = fields.Many2one(
        related="job_id.partner_id",
        string="Client",
        store=True,
    )

    _sql_constraints = [
        (
            "unique_user_per_job",
            "UNIQUE (job_id, user_id)",
            "This crew member is already assigned to this job.",
        ),
    ]

    def name_get(self):
        result = []
        for rec in self:
            display = f"{rec.user_id.name} ({dict(self._fields['role'].selection).get(rec.role, '')})"
            if rec.job_id:
                display = f"{rec.job_id.name} — {display}"
            result.append((rec.id, display))
        return result
