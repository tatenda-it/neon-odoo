# -*- coding: utf-8 -*-
from odoo import _, api, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    @api.model
    def _cron_neon_winloss_loop(self):
        """Stub win/loss loop. Placeholder: emit a learning record per recently
        closed (won/lost) opportunity. Real analysis needs live outcome volume."""
        Learning = self.env["neon.learning.record"]
        leads = self.search([("neon_outcome_tag", "in", ["won", "lost"])], limit=30)
        for lead in leads:
            Learning.create({
                "name": _("Win/Loss: %s") % lead.display_name,
                "loop_type": "win_loss",
                "lead_id": lead.id,
                "captured": _("Outcome=%(o)s; competitor=%(c)s") % {
                    "o": lead.neon_outcome_tag,
                    "c": lead.neon_competitor_id.display_name if lead.neon_competitor_id else "-",
                },
                "improvement": _("Win/loss stub - tune scoring/positioning from real data."),
            })
        return True

    @api.model
    def _cron_neon_learning_loops_other(self):
        """Stub for the remaining loops (campaign/partner/play/product/competitor).
        Inert placeholder - real loops are built once live data exists and the
        #2 intel boards are rebuilt on it."""
        Learning = self.env["neon.learning.record"]
        for loop in ("campaign", "partner", "play", "product_demand", "competitor"):
            Learning.create({
                "name": _("%s loop (stub)") % loop.replace("_", " ").title(),
                "loop_type": loop,
                "captured": _("Placeholder - needs live data."),
                "improvement": _("Inert until post-cutover data + #2 boards rebuilt."),
            })
        return True
