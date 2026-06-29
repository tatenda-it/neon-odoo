# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    def action_neon_recommend_play(self):
        """Suggest a play for this lead -> review queue (propose-only).
        Placeholder heuristic: match a play whose competitor matches the lead's
        competitor, else the first active play. Real matching is post-data-gate."""
        Rec = self.env["neon.shadow.recommendation"]
        Play = self.env["neon.play"]
        for lead in self:
            play = False
            if lead.neon_competitor_id:
                play = Play.search([("competitor_id", "=", lead.neon_competitor_id.id)], limit=1)
            if not play:
                play = Play.search([("active", "=", True)], limit=1)
            Rec.create({
                "name": _("Play recommendation: %s") % lead.display_name,
                "rec_type": "play_reco",
                "lead_id": lead.id,
                "play_id": play.id or False,
                "recommendation": play.name if play else _("No play matched"),
                "rationale": _("Placeholder play match - tune post-data-gate."),
                "confidence": "low",
            })
        return True

    # --- Inert planning cron stubs (ship INACTIVE) -------------------------
    @api.model
    def _cron_neon_recycle_review(self):
        """Stub: surface lost/dormant opportunities eligible for reactivation.
        Placeholder: lost leads with outcome 'lost' or 'inactive'."""
        Rec = self.env["neon.shadow.recommendation"]
        leads = self.search([
            ("active", "=", True),
            ("neon_outcome_tag", "in", ["lost", "inactive", "postponed"]),
        ], limit=30)
        for lead in leads:
            Rec.create({
                "name": _("Recycle candidate: %s") % lead.display_name,
                "rec_type": "recycle",
                "lead_id": lead.id,
                "recommendation": _("Consider reactivation outreach."),
                "rationale": _("Recycle-review stub - outcome=%s.") % lead.neon_outcome_tag,
                "confidence": "low",
            })
        return True

    @api.model
    def _cron_neon_product_demand_review(self):
        """Stub: aggregate product-focus signals across recent opportunities.
        Placeholder: counts leads per play product_focus. Real demand modelling
        is post-data-gate."""
        Rec = self.env["neon.shadow.recommendation"]
        Rec.create({
            "name": _("Product demand review (stub)"),
            "rec_type": "product_demand",
            "recommendation": _("Review product-focus demand across the pipeline."),
            "rationale": _("Product-demand stub - needs live volume to be meaningful."),
            "confidence": "low",
        })
        return True

    @api.model
    def _cron_neon_monthly_planning_pack(self):
        """Stub: assemble a monthly planning pack item for directors.
        Placeholder summary; real pack composition is post-data-gate."""
        Rec = self.env["neon.shadow.recommendation"]
        Rec.create({
            "name": _("Monthly planning pack (stub)"),
            "rec_type": "planning_pack",
            "recommendation": _("Assemble monthly market/planning pack."),
            "rationale": _("Planning-pack stub - composed from live data post-cutover."),
            "confidence": "low",
        })
        return True
