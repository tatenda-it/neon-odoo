# -*- coding: utf-8 -*-
from odoo import _, fields, models


class NeonPostEventReview(models.Model):
    """Structured post-event review (§12). Functional now - captures the
    outcomes the 2F loops will later learn from. Tie to an event/lead; fill
    after delivery."""

    _name = "neon.post.event.review"
    _description = "Neon Post-Event Review"
    _order = "review_date desc, id desc"

    name = fields.Char(string="Title", required=True)
    review_date = fields.Date(default=fields.Date.context_today)
    event_id = fields.Many2one("neon.event.opportunity", ondelete="set null")
    lead_id = fields.Many2one("crm.lead", ondelete="set null")
    partner_id = fields.Many2one("res.partner", string="Client", ondelete="set null")

    # Client satisfaction
    client_satisfaction = fields.Selection(
        [("excellent", "Excellent"), ("good", "Good"),
         ("average", "Average"), ("poor", "Poor")],
        string="Client Satisfaction",
    )
    satisfaction_comments = fields.Text()

    # Profitability
    profitability_signal = fields.Selection(
        [("profitable", "Profitable"), ("breakeven", "Breakeven"),
         ("poor", "Poor"), ("unknown", "Unknown")],
        default="unknown",
    )
    margin_estimate = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id)

    # Equipment learning
    equipment_gaps = fields.Text(string="Equipment Gaps")
    sub_hire_required = fields.Boolean()
    damaged_or_missing = fields.Text(string="Damaged / Missing Items")

    # Crew & execution
    execution_issues = fields.Text(
        string="Crew / Execution Issues",
        help="Late arrival, understaffing, setup or technical issues, praise.")

    # Future potential
    repeat_likely = fields.Boolean(string="Repeat Likely")
    expected_repeat_month = fields.Selection(
        [("01","Jan"),("02","Feb"),("03","Mar"),("04","Apr"),("05","May"),
         ("06","Jun"),("07","Jul"),("08","Aug"),("09","Sep"),("10","Oct"),
         ("11","Nov"),("12","Dec")], string="Expected Repeat Month")
    next_event_type = fields.Char()
    cross_sell = fields.Text(string="Cross-sell Opportunity")

    # Relationship + next actions
    thank_you_done = fields.Boolean(string="Thank-you Sent")
    testimonial_requested = fields.Boolean()
    referral_requested = fields.Boolean()
    next_actions = fields.Text(string="Next Actions")

    def action_capture_learning(self):
        """Create an Event-loop learning record from this review (manual, 2F).
        The automated loops are inert stubs; this is the human path."""
        Learning = self.env["neon.learning.record"]
        for rev in self:
            Learning.create({
                "name": _("Event loop: %s") % rev.name,
                "loop_type": "event",
                "lead_id": rev.lead_id.id or False,
                "event_id": rev.event_id.id or False,
                "captured": _("Satisfaction=%(s)s; profitability=%(p)s; repeat=%(r)s") % {
                    "s": rev.client_satisfaction or "-",
                    "p": rev.profitability_signal or "-",
                    "r": "yes" if rev.repeat_likely else "no",
                },
                "improvement": rev.next_actions or "",
            })
        return True
