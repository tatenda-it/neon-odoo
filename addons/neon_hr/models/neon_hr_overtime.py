# -*- coding: utf-8 -*-
"""Neon HR R2 — overtime resolution + TOIL accrual.

Overtime is resolved case-by-case into one of {paid, TOIL, included}
(the configurable outcome flagged at R1b), with approval. When resolved
as TOIL, the approved hours accrue to a TOIL leave-type balance via an
``hr.leave.allocation`` — TAKING that TOIL is then a validated
``hr.leave`` that reduces the R1b crew-availability signal (reused, not
rebuilt). Confidential (owner + OD/MD/Admin).
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

OT_RESOLUTIONS = [
    ("paid", "Paid"),
    ("toil", "TOIL (time off in lieu)"),
    ("included", "Included (no extra)"),
]
HOURS_PER_DAY = 8.0


class NeonHrOvertime(models.Model):
    _name = "neon.hr.overtime"
    _description = "Neon HR Overtime / TOIL"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _rec_name = "display_name"

    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="restrict",
        index=True, tracking=True)
    employee_user_id = fields.Many2one(
        related="employee_id.user_id", store=True, index=True)
    date = fields.Date(default=fields.Date.context_today, required=True)
    hours = fields.Float(required=True, tracking=True)
    event_job_id = fields.Many2one("commercial.event.job", string="Event")
    resolution = fields.Selection(
        OT_RESOLUTIONS, tracking=True,
        help="Case-by-case outcome (Q16/S3): paid, TOIL, or included. "
        "Policy ownership pending (Lisa/ops).")
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved")],
        default="draft", required=True, tracking=True, index=True)
    approved_by_id = fields.Many2one("res.users", readonly=True, tracking=True)
    toil_allocation_id = fields.Many2one(
        "hr.leave.allocation", readonly=True, string="TOIL Allocation")
    notes = fields.Text()
    # R3b C4 -- add active field so the 17.0.6.0.0 post-migrate can
    # retire records without deletion (perm_unlink=0 audit rule
    # holds; data preserved, reversible by setting active=True).
    active = fields.Boolean(default=True, tracking=True)

    @api.depends("employee_id", "hours", "resolution")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s — %.1fh (%s)" % (
                rec.employee_id.name or _("New"), rec.hours or 0.0,
                dict(OT_RESOLUTIONS).get(rec.resolution, "unresolved"))

    def action_approve(self):
        """Approve the overtime + its resolution. On TOIL, accrue a
        validated leave allocation (the TOIL balance)."""
        if not (self.env.user.has_group("neon_core.group_neon_superuser")
                or self.env.user.has_group(
                    "neon_finance.group_neon_finance_approver")):
            raise AccessError(_(
                "Only OD/MD or a Finance Approver may approve overtime."))
        toil_type = self.env.ref("neon_hr.leave_type_toil",
                                 raise_if_not_found=False)
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft overtime can be approved."))
            if not rec.resolution:
                raise UserError(_(
                    "Choose a resolution (paid / TOIL / included) before "
                    "approving."))
            vals = {"state": "approved", "approved_by_id": self.env.user.id}
            if rec.resolution == "toil":
                if not toil_type:
                    raise UserError(_("TOIL leave type not configured."))
                alloc = self.env["hr.leave.allocation"].sudo().create({
                    "name": _("TOIL accrual: %s") % rec.display_name,
                    "employee_id": rec.employee_id.id,
                    "holiday_status_id": toil_type.id,
                    "number_of_days": (rec.hours or 0.0) / HOURS_PER_DAY,
                })
                try:
                    alloc.action_validate()
                except Exception:  # noqa: BLE001
                    alloc.sudo().write({"state": "validate"})
                vals["toil_allocation_id"] = alloc.id
            rec.write(vals)
            rec.message_post(body=_("Overtime approved (%s) by %s.")
                             % (rec.resolution, self.env.user.name))
        return True
