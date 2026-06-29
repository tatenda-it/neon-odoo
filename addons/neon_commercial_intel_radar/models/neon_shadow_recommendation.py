# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class NeonShadowRecommendation(models.Model):
    """Radar extension: add the 'market_signal' rec_type + back-ref, and the
    2D execution branch the spec (s12a) asks for - Accept->Execute on a
    market_signal creates a pre-filled crm.lead CANDIDATE. This is the human
    path; nothing automatic ever creates a lead."""

    _inherit = "neon.shadow.recommendation"

    rec_type = fields.Selection(
        selection_add=[("market_signal", "Market Radar Tender")],
        ondelete={"market_signal": "cascade"},
    )
    market_signal_id = fields.Many2one(
        "neon.market.signal", string="Market Signal",
        ondelete="set null")

    def action_execute(self):
        """Extend 2D execute: market_signal -> crm.lead candidate (human-only,
        per-record, traceable). All other rec_types fall through to 2D's
        existing mapping (To-Do / campaign-approve)."""
        radar = self.filtered(lambda r: r.rec_type == "market_signal")
        for rec in radar:
            if rec.state != "accepted":
                raise UserError(_(
                    "Only an ACCEPTED recommendation can be executed. Review "
                    "and accept it first."))
            if rec.neon_executed:
                raise UserError(_(
                    "This recommendation has already been executed."))
            lead = rec._neon_radar_create_lead_candidate()
            rec.write({
                "neon_executed": True,
                "neon_executed_by": self.env.user.id,
                "neon_executed_date": fields.Datetime.now(),
                "neon_executed_model": "crm.lead",
                "neon_executed_res_id": lead.id,
                "neon_execution_note": _("Lead candidate created: %s")
                % lead.display_name,
            })
        others = self - radar
        if others:
            return super(NeonShadowRecommendation, others).action_execute()
        return True

    def _neon_radar_create_lead_candidate(self):
        """Create a crm.lead pre-filled from the linked market signal. Reuses
        the 2A intelligence fields so the candidate lands ready to qualify."""
        self.ensure_one()
        sig = self.market_signal_id
        vals = {
            "name": (sig.name if sig else self.name) or _("Market Radar lead"),
            "type": "opportunity",
            "description": self.rationale or (sig.summary if sig else ""),
        }
        if sig:
            if sig.procuring_entity:
                vals["partner_name"] = sig.procuring_entity
            if sig.sector:
                vals["neon_sector"] = sig.sector
            if sig.event_type:
                vals["neon_event_type"] = sig.event_type
            if sig.estimated_value:
                vals["expected_revenue"] = sig.estimated_value
            if sig.deadline:
                vals["neon_next_action_date"] = sig.deadline
        return self.env["crm.lead"].create(vals)
