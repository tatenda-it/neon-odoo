# -*- coding: utf-8 -*-
"""
Extend the Soft Hold on a pending Commercial Job (P2.M5).

Anyone in group_neon_jobs_user can extend. Hard caps:
- 3 extensions max (soft_hold_extension_count >= 3 blocks)
- 28 total days from create_date (defensive — catches manual edits
  to soft_hold_until that bypassed the wizard)
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


_MAX_EXTENSIONS = 3
_MAX_TOTAL_DAYS = 28


class CommercialJobSoftHoldExtendWizard(models.TransientModel):
    _name = "commercial.job.soft_hold.extend.wizard"
    _description = "Extend Soft Hold on a Commercial Job"

    job_id = fields.Many2one(
        "commercial.job",
        string="Commercial Job",
        required=True,
    )
    current_expiry = fields.Date(
        related="job_id.soft_hold_until",
        string="Current Expiry",
        readonly=True,
    )
    extension_count = fields.Integer(
        related="job_id.soft_hold_extension_count",
        string="Extensions Used",
        readonly=True,
    )
    extension_days = fields.Selection(
        [
            ("7", "7 days"),
            ("14", "14 days"),
            ("21", "21 days"),
        ],
        string="Extend by",
        default="7",
        required=True,
    )
    new_expiry = fields.Date(
        string="New Expiry",
        compute="_compute_new_expiry",
    )
    reason = fields.Text(
        string="Reason",
        help="Optional — captured in the chatter alongside the extension.",
    )

    @api.depends("job_id", "extension_days", "current_expiry")
    def _compute_new_expiry(self):
        today = fields.Date.today()
        for w in self:
            if not w.job_id or not w.extension_days:
                w.new_expiry = False
                continue
            anchor = w.current_expiry or today
            # Extending an already-expired hold from a past date would
            # still land in the past; anchor on today in that case.
            if anchor < today:
                anchor = today
            w.new_expiry = fields.Date.add(anchor, days=int(w.extension_days))

    def action_confirm(self):
        self.ensure_one()
        job = self.job_id
        if job.state != "pending":
            raise UserError(_(
                "Soft hold can only be extended on pending jobs (current state: %s)."
            ) % job.state)
        if job.soft_hold_extension_count >= _MAX_EXTENSIONS:
            raise UserError(_(
                "This job has already had %d extensions. The soft hold cannot "
                "be extended further. Either move to Active, archive as lost, "
                "or cancel."
            ) % _MAX_EXTENSIONS)
        # Defensive total-days check from create_date — catches manual
        # edits of soft_hold_until that bypassed this wizard.
        create_date = fields.Date.to_date(job.create_date)
        max_allowed = fields.Date.add(create_date, days=_MAX_TOTAL_DAYS)
        if self.new_expiry > max_allowed:
            raise UserError(_(
                "Cannot extend: the new expiry (%s) would exceed the total "
                "soft-hold cap of %d days from job creation (limit: %s). "
                "Pick a shorter extension, or move the job forward."
            ) % (self.new_expiry, _MAX_TOTAL_DAYS, max_allowed))
        new_count = job.soft_hold_extension_count + 1
        job.write({
            "soft_hold_until": self.new_expiry,
            "soft_hold_extension_count": new_count,
            "last_expiry_notification_date": False,
        })
        body = _(
            "Soft hold extended by %s days by %s. New expiry: %s. "
            "Extension %d of %d."
        ) % (self.extension_days, self.env.user.name, self.new_expiry,
             new_count, _MAX_EXTENSIONS)
        if self.reason:
            body += _(" Reason: %s") % self.reason
        job.message_post(body=body)
        return {"type": "ir.actions.act_window_close"}
