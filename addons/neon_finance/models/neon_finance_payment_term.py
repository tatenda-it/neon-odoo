# -*- coding: utf-8 -*-
"""P6.M2 -- per-quote payment term (Schema Sketch §5.5, Q18).

Salespeople set deposit + final payment cadence per quote rather than
per partner, because the same client may negotiate different terms on
different jobs. A small standalone model rather than a tag on the
quote keeps the four fields reusable across quotes for the same
partner (the wizard pre-populates from the partner's most recent
term).

No perm_unlink on this model -- audit trail discipline: terms once
committed to a quote cannot disappear. Corrections happen via a new
record, ``write()`` on the existing record, or a new quote.
"""
from odoo import _, api, fields, models


class NeonFinancePaymentTerm(models.Model):
    _name = "neon.finance.payment.term"
    _description = "Finance Payment Term"
    _order = "id desc"
    _rec_name = "name"

    name = fields.Char(
        compute="_compute_name",
        store=True,
        readonly=True,
        index=True,
        help="Auto-generated descriptor: '50% deposit / 30 day final "
        "/ reminder'. Stable for the lifetime of the record; "
        "re-computed only when the four input fields change.",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        ondelete="restrict",
        index=True,
        help="The partner this term was negotiated with. Used to "
        "pre-populate the wizard when drafting a new quote for the "
        "same partner.",
    )
    deposit_due_days = fields.Integer(
        string="Deposit Due (days)",
        default=0,
        help="Days from quote acceptance until deposit invoice is "
        "due. 0 = due on acceptance (most common).",
    )
    deposit_pct = fields.Float(
        string="Deposit %",
        default=50.0,
        help="Percent of the quote total billed up front.",
    )
    final_due_days = fields.Integer(
        string="Final Due (days)",
        default=30,
        help="Days from event date until the final-balance invoice "
        "is due.",
    )
    late_policy = fields.Selection(
        [
            ("none", "None"),
            ("reminder", "Reminder only"),
            ("account_hold", "Account hold"),
        ],
        default="reminder",
        required=True,
        help="What happens if final payment is not received by the "
        "due date. 'Account hold' blocks new quotes for the "
        "partner until paid.",
    )
    notes = fields.Text()

    _sql_constraints = [
        ("check_deposit_pct_range",
         "CHECK (deposit_pct >= 0 AND deposit_pct <= 100)",
         "Deposit percent must be between 0 and 100."),
        ("check_deposit_due_days_non_negative",
         "CHECK (deposit_due_days >= 0)",
         "Deposit due days must be zero or positive."),
        ("check_final_due_days_non_negative",
         "CHECK (final_due_days >= 0)",
         "Final due days must be zero or positive."),
    ]

    @api.depends("deposit_pct", "deposit_due_days", "final_due_days",
                 "late_policy")
    def _compute_name(self):
        for rec in self:
            deposit = "%g%%" % rec.deposit_pct if rec.deposit_pct else "no"
            dep_when = (
                "on acceptance"
                if rec.deposit_due_days == 0
                else "%dd" % rec.deposit_due_days
            )
            final = "%dd final" % rec.final_due_days
            late = rec.late_policy or "none"
            rec.name = _("%s deposit (%s) / %s / %s") % (
                deposit, dep_when, final, late)

    @api.model
    def get_default_for_partner(self, partner_id):
        """Return the most recent payment term for ``partner_id`` or
        an empty recordset. Used by the wizard's default_get to seed
        the four fields from prior history."""
        if not partner_id:
            return self.browse()
        return self.search(
            [("partner_id", "=", partner_id)],
            order="id desc",
            limit=1,
        )
