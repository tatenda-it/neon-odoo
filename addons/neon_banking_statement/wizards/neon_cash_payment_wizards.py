# -*- coding: utf-8 -*-
"""Stage-3 payment-path quick-entries: Vendor Payment, Customer Receipt,
Vendor Advance.

Vendor Payment + Customer Receipt drive Odoo's NATIVE account.payment.register
wizard (active_model='account.move', active_ids=[bill/invoice]). This is
deliberate: the Neon cross-currency SCH- guard lives on
account.payment.register._create_payments(), so routing through it keeps that
guard active automatically -- a payment created directly on account.payment
would bypass it. Vendor Advance has no bill (nothing to reconcile and no SCH-
line), so it posts a plain outbound account.payment.

No debits/credits, journals, suspense or reconcile surfaced to the bookkeeper.
The posted payment lands in the cash/bank account and shows in the Stage-1
statement.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class NeonCashVendorPaymentWizard(models.TransientModel):
    _name = "neon.cash.vendor.payment.wizard"
    _inherit = "neon.cash.entry.mixin"
    _description = "Pay a Supplier Bill (cash/bank)"

    cash_account_id = fields.Many2one(string="Pay From")
    bill_id = fields.Many2one(
        "account.move", string="Bill", required=True,
        domain="[('move_type','=','in_invoice'),('state','=','posted'),"
               "('payment_state','in',('not_paid','partial'))]",
        help="The supplier bill being paid.")
    vendor_id = fields.Many2one(
        "res.partner", related="bill_id.partner_id", string="Vendor", readonly=True)

    @api.onchange("bill_id")
    def _onchange_bill_id(self):
        if self.bill_id:
            self.amount = self.bill_id.amount_residual
            if not self.reference:
                self.reference = self.bill_id.ref or self.bill_id.name

    def action_save(self):
        self.ensure_one()
        self._check_amount()
        journal = self._cash_journal()
        # Native register path -> Neon SCH- cross-currency guard stays active.
        reg = self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=[self.bill_id.id],
        ).create({
            "journal_id": journal.id,
            "payment_date": self.date,
            "amount": self.amount,
            "communication": self.reference or self.bill_id.name,
        })
        reg.action_create_payments()
        return {"type": "ir.actions.act_window_close"}


class NeonCashCustomerReceiptWizard(models.TransientModel):
    _name = "neon.cash.customer.receipt.wizard"
    _inherit = "neon.cash.entry.mixin"
    _description = "Receive a Customer Payment (cash/bank)"

    cash_account_id = fields.Many2one(
        string="Deposit To",
        help="Where the money is received -- a bank account, or Undeposited "
             "Funds to hold it until banked.")
    invoice_id = fields.Many2one(
        "account.move", string="Invoice", required=True,
        domain="[('move_type','=','out_invoice'),('state','=','posted'),"
               "('payment_state','in',('not_paid','partial'))]",
        help="The customer invoice being paid.")
    partner_id = fields.Many2one(
        "res.partner", related="invoice_id.partner_id", string="Customer", readonly=True)

    @api.onchange("invoice_id")
    def _onchange_invoice_id(self):
        if self.invoice_id:
            self.amount = self.invoice_id.amount_residual
            if not self.reference:
                self.reference = self.invoice_id.ref or self.invoice_id.name

    def action_save(self):
        self.ensure_one()
        self._check_amount()
        journal = self._cash_journal()
        # Native register path -> Neon SCH- cross-currency guard stays active.
        reg = self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=[self.invoice_id.id],
        ).create({
            "journal_id": journal.id,
            "payment_date": self.date,
            "amount": self.amount,
            "communication": self.reference or self.invoice_id.name,
        })
        reg.action_create_payments()
        return {"type": "ir.actions.act_window_close"}


class NeonCashVendorAdvanceWizard(models.TransientModel):
    _name = "neon.cash.vendor.advance.wizard"
    _inherit = "neon.cash.entry.mixin"
    _description = "Pay a Supplier in Advance (no bill yet)"

    cash_account_id = fields.Many2one(string="Pay From")
    vendor_id = fields.Many2one("res.partner", string="Vendor", required=True)
    description = fields.Char(string="Details", required=True)

    def action_save(self):
        self.ensure_one()
        self._check_amount()
        journal = self._cash_journal()
        # No bill to reconcile and no SCH- line -> a plain outbound payment.
        # Sits on the vendor's payable, ready to net off a future bill.
        payment = self.env["account.payment"].create({
            "payment_type": "outbound",
            "partner_type": "supplier",
            "partner_id": self.vendor_id.id,
            "journal_id": journal.id,
            "amount": self.amount,
            "date": self.date,
            "ref": self.reference or self.description,
        })
        payment.action_post()
        return {"type": "ir.actions.act_window_close"}
