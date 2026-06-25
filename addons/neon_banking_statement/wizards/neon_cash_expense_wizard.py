# -*- coding: utf-8 -*-
"""EXPENSE quick-entry (Zoho-style) -- money OUT of a cash/bank account.

Posts a normal Odoo journal entry underneath (NO suspense, NO reconcile step,
NO Dr/Cr jargon shown to the user):
    Dr Expense Account (net)  [+ Odoo auto-adds Dr Input VAT from tax_ids]
    Cr Cash/Bank Account (gross)
By crediting the GROSS (net + VAT) and putting tax_ids on the expense line, Odoo
generates the tax line itself and the move balances with NO suspense plug. The
posted move shows immediately in the Stage-1 statement; the running balance drops.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class NeonCashExpenseWizard(models.TransientModel):
    _name = "neon.cash.expense.wizard"
    _description = "Add Expense (cash/bank)"

    cash_account_id = fields.Many2one(
        "account.account", string="Paid From", required=True,
        domain="[('account_type','in',('asset_cash','asset_current'))]",
        help="The cash/bank account the money leaves.")
    expense_account_id = fields.Many2one(
        "account.account", string="Expense Account", required=True,
        domain="[('account_type','=','expense')]")
    date = fields.Date(string="Date", required=True, default=fields.Date.context_today)
    amount = fields.Monetary(string="Amount", required=True, currency_field="currency_id")
    tax_treatment = fields.Selection(
        [("exclusive", "Tax Exclusive"), ("inclusive", "Tax Inclusive")],
        string="Amount is", default="exclusive", required=True)
    tax_id = fields.Many2one(
        "account.tax", string="Tax", domain="[('type_tax_use','=','purchase')]",
        help="Optional. e.g. VAT 15.5% (Purchases).")
    vendor_id = fields.Many2one("res.partner", string="Vendor")
    reference = fields.Char(string="Reference #")
    description = fields.Char(string="Details", required=True)
    customer_id = fields.Many2one("res.partner", string="Customer")
    receipt = fields.Binary(string="Attach Receipt")
    receipt_filename = fields.Char()
    currency_id = fields.Many2one(
        "res.currency", compute="_compute_currency_id", string="Currency")

    @api.depends("cash_account_id")
    def _compute_currency_id(self):
        company_currency = self.env.company.currency_id
        for w in self:
            w.currency_id = w.cash_account_id.currency_id or company_currency

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        code = self.env.context.get("default_cash_account_code")
        if code and not res.get("cash_account_id"):
            acc = self.env["account.account"].search([("code", "=", code)], limit=1)
            if acc:
                res["cash_account_id"] = acc.id
        return res

    def _cash_journal(self):
        """The cash/bank journal whose default account is this cash account."""
        j = self.env["account.journal"].search(
            [("default_account_id", "=", self.cash_account_id.id),
             ("type", "in", ("bank", "cash"))], limit=1)
        if not j:
            raise UserError(_(
                "No cash/bank journal is set up for account %s.")
                % self.cash_account_id.display_name)
        return j

    def _amounts(self):
        """Return (net, gross) using Odoo's tax engine for the split."""
        currency = self.currency_id or self.env.company.currency_id
        if not self.tax_id:
            return self.amount, self.amount
        rate = self.tax_id.amount / 100.0
        if self.tax_treatment == "inclusive":
            net = currency.round(self.amount / (1.0 + rate))
        else:
            net = self.amount
        res = self.tax_id.compute_all(net, currency, 1.0)
        return net, res["total_included"]

    def action_save(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_("Amount must be greater than zero."))
        net, gross = self._amounts()
        partner = self.vendor_id or self.customer_id
        exp_line = {
            "account_id": self.expense_account_id.id,
            "name": self.description, "debit": net, "credit": 0.0,
        }
        if self.tax_id:
            exp_line["tax_ids"] = [(6, 0, [self.tax_id.id])]
        cash_line = {
            "account_id": self.cash_account_id.id,
            "name": self.description, "debit": 0.0, "credit": gross,
        }
        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": self._cash_journal().id,
            "date": self.date,
            "ref": self.reference or self.description,
            "partner_id": partner.id if partner else False,
            "line_ids": [(0, 0, exp_line), (0, 0, cash_line)],
        })
        move.action_post()
        if self.receipt:
            self.env["ir.attachment"].create({
                "name": self.receipt_filename or "receipt",
                "datas": self.receipt, "res_model": "account.move",
                "res_id": move.id,
            })
        return {"type": "ir.actions.act_window_close"}
