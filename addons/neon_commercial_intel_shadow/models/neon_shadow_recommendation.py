# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class NeonShadowRecommendation(models.Model):
    """The 2B review queue. EVERY AI/rule output lands here in shadow state and
    a human accepts or rejects it. Accepting does NOT act on the system - it
    only records the decision (traceability). Turning an accepted recommendation
    into a task/record/message is Phase 2D and is deliberately not built here.
    """

    _name = "neon.shadow.recommendation"
    _description = "Neon Shadow Recommendation (Review Queue)"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    rec_type = fields.Selection(
        [
            ("score", "Lead Score"),
            ("next_action", "Next Best Action"),
            ("leak_alert", "Leak Alert"),
            ("partner_move", "Partner Move"),
            ("competitor_mention", "Competitor Mention"),
            ("brief_item", "Daily Brief Item"),
        ],
        string="Type",
        required=True,
    )
    recommendation = fields.Text(help="What the rule/AI suggests.")
    rationale = fields.Text(help="Why - the traceable reason (source data).")
    confidence = fields.Selection(
        [("high", "High"), ("medium", "Medium"), ("low", "Low")],
        default="low",
    )
    state = fields.Selection(
        [
            ("new", "Awaiting Review"),
            ("accepted", "Accepted (logged only)"),
            ("rejected", "Rejected"),
        ],
        default="new",
        required=True,
        help="Shadow mode: Accepted records the decision only - it does NOT "
             "create tasks or act on the system (that is Phase 2D).",
    )

    # Optional source links (whichever the rec_type implies).
    lead_id = fields.Many2one("crm.lead", ondelete="cascade")
    partner_id = fields.Many2one("res.partner", ondelete="set null")
    competitor_id = fields.Many2one("neon.competitor", ondelete="set null")
    play_id = fields.Many2one("neon.play", ondelete="set null")
    event_id = fields.Many2one("neon.event.opportunity", ondelete="set null")

    reviewed_by = fields.Many2one("res.users", readonly=True)
    reviewed_date = fields.Datetime(readonly=True)

    def action_accept(self):
        for rec in self:
            if rec.state != "new":
                raise UserError(_("Only items awaiting review can be accepted."))
            rec.write({
                "state": "accepted",
                "reviewed_by": self.env.user.id,
                "reviewed_date": fields.Datetime.now(),
            })
        return True

    def action_reject(self):
        for rec in self:
            if rec.state != "new":
                raise UserError(_("Only items awaiting review can be rejected."))
            rec.write({
                "state": "rejected",
                "reviewed_by": self.env.user.id,
                "reviewed_date": fields.Datetime.now(),
            })
        return True
