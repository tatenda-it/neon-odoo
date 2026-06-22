# -*- coding: utf-8 -*-
"""QUOTE-UX-3b -- whole-quote discount wizard.

Opens from the quote form's draft-only 'Apply Whole-Quote Discount' button and
calls the SHARED neon.finance.quote.apply_whole_quote_discount -- the same
method the WhatsApp flow uses -- so the Odoo form and WhatsApp distribute a
whole-quote discount identically (a uniform per-line discount_pct + the
wa12_discount_note label). This is the ENGINE discount, NOT the stock OCA
account global discount (account.invoice.global.discount, which lives on
sale.order / account.move only).
"""
from odoo import fields, models


_MODE = [
    ("discount", "Discount amount off"),
    ("target", "Target final amount"),
]
_BASIS = [
    ("incl", "VAT-inclusive total"),
    ("ex", "Ex-VAT goods subtotal"),
]


class NeonFinanceWholeQuoteDiscountWizard(models.TransientModel):
    _name = "neon.finance.whole.quote.discount.wizard"
    _description = "Apply Whole-Quote Discount Wizard"

    quote_id = fields.Many2one(
        "neon.finance.quote",
        required=True,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(
        related="quote_id.currency_id",
        readonly=True,
    )
    current_total = fields.Monetary(
        related="quote_id.amount_total",
        currency_field="currency_id",
        readonly=True,
        string="Current Total (incl. VAT)",
    )
    mode = fields.Selection(
        _MODE, default="discount", required=True, string="Apply as")
    basis = fields.Selection(
        _BASIS, default="incl", required=True, string="Basis")
    amount = fields.Monetary(
        currency_field="currency_id",
        required=True,
        string="Amount",
        help="The discount to take off (Apply as = Discount amount off), or "
        "the desired final amount (Apply as = Target final amount). "
        "VAT-inclusive total basis lands the drop EXACTLY on the client Total; "
        "Ex-VAT basis discounts the goods subtotal (VAT then applies on top).",
    )

    def action_apply(self):
        """Distribute the whole-quote discount via the SHARED quote method.
        Runs as the current user (a rep editing their own draft quote); the
        method raises UserError on an invalid amount, surfaced natively here."""
        self.ensure_one()
        self.quote_id.apply_whole_quote_discount(
            self.amount,
            ex_vat=(self.basis == "ex"),
            is_target=(self.mode == "target"),
        )
        return {"type": "ir.actions.act_window_close"}
