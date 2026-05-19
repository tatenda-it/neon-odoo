# -*- coding: utf-8 -*-
"""P6.M2 -- per-quote payment term wizard (Schema Sketch §5.5).

Opens from the quote form's 'Set Payment Terms' button. Either
reuses an existing term that already matches the partner's history,
or creates a new neon.finance.payment.term and assigns it to the
quote in one step.

⚠️ DECISION (P6.M2): reuse-vs-create policy. We CREATE a new
payment.term record on every wizard save rather than searching for
a byte-identical existing one. Rationale: payment terms are tied to
a specific negotiation, and the same 50/30/reminder shape used on
two different jobs are not the same term -- a future audit may need
to know which quote each term was set for. Storage cost is trivial.
"""
from odoo import _, api, fields, models


_LATE_POLICY = [
    ("none", "None"),
    ("reminder", "Reminder only"),
    ("account_hold", "Account hold"),
]


class NeonFinancePaymentTermWizard(models.TransientModel):
    _name = "neon.finance.payment.term.wizard"
    _description = "Set Payment Terms Wizard"

    quote_id = fields.Many2one(
        "neon.finance.quote",
        required=True,
        ondelete="cascade",
    )
    partner_id = fields.Many2one(
        "res.partner",
        related="quote_id.partner_id",
        readonly=True,
    )
    deposit_due_days = fields.Integer(default=0)
    deposit_pct = fields.Float(default=50.0)
    final_due_days = fields.Integer(default=30)
    late_policy = fields.Selection(
        _LATE_POLICY, default="reminder", required=True)
    notes = fields.Text()

    def action_save(self):
        """Materialise a neon.finance.payment.term and attach to the
        quote. Pre-existing payment_term_id is replaced (not unlinked
        -- nothing on this model unlinks)."""
        self.ensure_one()
        term = self.env["neon.finance.payment.term"].create({
            "partner_id": self.partner_id.id,
            "deposit_due_days": self.deposit_due_days,
            "deposit_pct": self.deposit_pct,
            "final_due_days": self.final_due_days,
            "late_policy": self.late_policy,
            "notes": self.notes,
        })
        self.quote_id.payment_term_id = term.id
        return {"type": "ir.actions.act_window_close"}
