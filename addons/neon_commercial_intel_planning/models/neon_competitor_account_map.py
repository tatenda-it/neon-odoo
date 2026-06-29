# -*- coding: utf-8 -*-
from odoo import _, fields, models


class NeonCompetitorAccountMap(models.Model):
    """Maps a competitor-served account to Neon's fit + switching likelihood,
    so competitor intelligence can be turned into ranked outreach targets
    (brief Workflow 7 / §10). Structural - usable now; ranking heuristics are
    placeholders until live competitor data accrues."""

    _name = "neon.competitor.account.map"
    _description = "Neon Competitor Account Target"
    _order = "fit_score desc, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    competitor_id = fields.Many2one(
        "neon.competitor", string="Competitor", required=True, ondelete="cascade"
    )
    account_id = fields.Many2one(
        "res.partner", string="Account", required=True, ondelete="cascade"
    )
    fit_score = fields.Integer(string="Account Fit Score", help="0-100 (placeholder).")
    switching_likelihood = fields.Selection(
        [("high", "High"), ("medium", "Medium"), ("low", "Low"), ("unknown", "Unknown")],
        default="unknown",
    )
    entry_point = fields.Selection(
        [
            ("hr", "HR"), ("procurement", "Procurement"), ("pa", "PA"),
            ("marketing", "Marketing"), ("ceo", "CEO / Exec"),
            ("organiser", "Organiser"), ("venue", "Venue"), ("partner", "Partner"),
            ("linkedin", "LinkedIn"), ("tender", "Tender Route"),
        ],
        string="Relationship Entry Point",
    )
    switching_reason = fields.Selection(
        [
            ("service", "Service"), ("speed", "Speed"), ("reliability", "Reliability"),
            ("relationship", "Relationship"), ("price", "Price"),
            ("production_quality", "Production Quality"),
        ],
        string="Likely Switching Reason",
        help="Why the account might switch to Neon (§25).",
    )
    positioning_note = fields.Text()
    status = fields.Selection(
        [
            ("identified", "Identified"),
            ("proposed", "Proposed for Outreach"),
            ("in_outreach", "In Outreach"),
            ("parked", "Parked"),
        ],
        default="identified",
    )

    def action_propose_outreach(self):
        """Propose this target for outreach -> review queue (propose-only)."""
        Rec = self.env["neon.shadow.recommendation"]
        for rec in self:
            rec.status = "proposed"
            Rec.create({
                "name": _("Target competitor account: %s") % rec.account_id.display_name,
                "rec_type": "account_target",
                "partner_id": rec.account_id.id,
                "competitor_id": rec.competitor_id.id,
                "recommendation": _("Pursue %(acc)s (served by %(comp)s); entry: %(ep)s") % {
                    "acc": rec.account_id.display_name,
                    "comp": rec.competitor_id.display_name,
                    "ep": dict(self._fields["entry_point"].selection).get(rec.entry_point, "?"),
                },
                "rationale": rec.positioning_note or _("Competitor-served, fit %s.") % rec.fit_score,
                "confidence": "low",
            })
        return True
