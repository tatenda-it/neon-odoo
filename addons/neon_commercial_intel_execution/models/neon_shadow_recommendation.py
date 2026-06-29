# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class NeonShadowRecommendation(models.Model):
    """2D: turn an ACCEPTED recommendation into a concrete artifact - by explicit
    human action only. There is deliberately no cron and no auto-trigger: a
    person Accepts (2B) and then Executes (2D). Every execution is logged with a
    reference to what it created."""

    _inherit = "neon.shadow.recommendation"

    neon_executed = fields.Boolean(string="Executed", readonly=True, default=False)
    neon_executed_by = fields.Many2one("res.users", readonly=True)
    neon_executed_date = fields.Datetime(readonly=True)
    neon_executed_model = fields.Char(string="Created Artifact (model)", readonly=True)
    neon_executed_res_id = fields.Integer(string="Created Artifact (id)", readonly=True)
    neon_execution_note = fields.Char(readonly=True)

    # Recommendation types that map to a "create a To-Do activity" execution.
    _ACTIVITY_TYPES = (
        "next_action", "leak_alert", "recycle", "play_reco",
        "account_target", "brief_item", "score", "product_demand",
        "planning_pack", "competitor_mention", "partner_move",
    )

    def _neon_create_activity(self):
        """Create a To-Do mail.activity on the linked lead (or partner)."""
        self.ensure_one()
        record = False
        if self.lead_id:
            record = self.lead_id
        elif self.partner_id:
            record = self.partner_id
        if not record:
            raise UserError(_(
                "Nothing to attach the To-Do to: this recommendation has no "
                "linked lead or partner."))
        activity = self.env["mail.activity"].create({
            "res_model_id": self.env["ir.model"]._get_id(record._name),
            "res_id": record.id,
            "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
            "summary": self.name,
            "note": self.recommendation or self.rationale or "",
            "user_id": self.env.user.id,
        })
        return "mail.activity", activity.id, _("To-Do created on %s") % record.display_name

    def _neon_approve_campaign(self):
        """Flip a proposed campaign to approved (no launch, just status)."""
        self.ensure_one()
        if not self.campaign_id:
            raise UserError(_("This campaign recommendation has no linked campaign."))
        self.campaign_id.neon_plan_status = "approved"
        return "utm.campaign", self.campaign_id.id, _("Campaign '%s' approved") % self.campaign_id.name

    def action_execute(self):
        """Execute an ACCEPTED recommendation. Human-only; per-record; traceable."""
        for rec in self:
            if rec.state != "accepted":
                raise UserError(_(
                    "Only an ACCEPTED recommendation can be executed. Review and "
                    "accept it first."))
            if rec.neon_executed:
                raise UserError(_("This recommendation has already been executed."))
            if rec.rec_type == "campaign":
                model, res_id, note = rec._neon_approve_campaign()
            elif rec.rec_type in rec._ACTIVITY_TYPES:
                model, res_id, note = rec._neon_create_activity()
            else:
                raise UserError(_("No execution mapping for type '%s'.") % rec.rec_type)
            rec.write({
                "neon_executed": True,
                "neon_executed_by": self.env.user.id,
                "neon_executed_date": fields.Datetime.now(),
                "neon_executed_model": model,
                "neon_executed_res_id": res_id,
                "neon_execution_note": note,
            })
        return True
