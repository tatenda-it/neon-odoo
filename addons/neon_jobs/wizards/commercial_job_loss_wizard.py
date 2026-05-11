# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CommercialJobLossWizard(models.TransientModel):
    _name = "commercial.job.loss.wizard"
    _description = "Capture loss details for pending Commercial Jobs linked to a lost CRM lead"

    lead_id = fields.Many2one(
        "crm.lead",
        string="CRM Lead",
        required=True,
    )
    job_ids = fields.Many2many(
        "commercial.job",
        string="Pending Jobs",
        compute="_compute_job_ids",
        store=False,
    )
    loss_reason = fields.Text(
        string="Loss Reason",
        required=True,
        help="Plain-English narrative — fed back into sales-process learning. "
        "Defaults to the lead's CRM lost reason if set.",
    )
    lost_to_competitor = fields.Char(string="Lost To Competitor")

    @api.depends("lead_id")
    def _compute_job_ids(self):
        for wiz in self:
            wiz.job_ids = wiz.lead_id.commercial_job_ids.filtered(
                lambda j: j.state == "pending"
            )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        lead_id = vals.get("lead_id") or self.env.context.get("default_lead_id")
        if lead_id and "loss_reason" in fields_list and not vals.get("loss_reason"):
            lead = self.env["crm.lead"].browse(lead_id)
            if lead.lost_reason_id:
                vals["loss_reason"] = lead.lost_reason_id.name
        return vals

    def action_confirm(self):
        self.ensure_one()
        pending = self.job_ids
        if not pending:
            raise UserError(_(
                "No pending Commercial Jobs are linked to this lead. "
                "Nothing to archive."
            ))
        pending.write({
            "loss_reason": self.loss_reason,
            "lost_to_competitor": self.lost_to_competitor or False,
        })
        pending.action_archive_lost()
        return {"type": "ir.actions.act_window_close"}
