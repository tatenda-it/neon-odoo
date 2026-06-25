# -*- coding: utf-8 -*-
"""PETTY CASH REPLENISHMENT quick-entry -- money IN to a cash/bank account.

Posts a normal Odoo journal entry (NO suspense, NO reconcile, NO Dr/Cr jargon):
    Dr Cash/Bank Account (amount)
    Cr Source Account (amount)        e.g. CABS bank -> Petty Cash
The posted move shows in the Stage-1 statement; the running balance rises.

Same-currency only: a cross-currency move-in (e.g. CABS ZWG -> Petty Cash USD)
needs FX handling -> directed to Odoo's native Internal Transfer instead of
posting a wrong single-rate entry (keeps us off the protected FX/payment path).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class NeonCashReplenishmentWizard(models.TransientModel):
    _name = "neon.cash.replenishment.wizard"
    _description = "Add Replenishment (money in)"

    cash_account_id = fields.Many2one(
        "account.account", string="Into", required=True,
        domain="[('account_type','in',('asset_cash','asset_current'))]",
        help="The cash/bank account the money comes into.")
    source_account_id = fields.Many2one(
        "account.account", string="From", required=True,
        domain="[('account_type','in',('asset_cash','asset_current'))]",
        help="Where the money comes from, e.g. CABS bank.")
    date = fields.Date(string="Date", required=True, default=fields.Date.context_today)
    amount = fields.Monetary(string="Amount", required=True, currency_field="currency_id")
    reference = fields.Char(string="Reference #")
    description = fields.Char(string="Details", required=True)
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
        j = self.env["account.journal"].search(
            [("default_account_id", "=", self.cash_account_id.id),
             ("type", "in", ("bank", "cash"))], limit=1)
        if not j:
            raise UserError(_(
                "No cash/bank journal is set up for account %s.")
                % self.cash_account_id.display_name)
        return j

    def action_save(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_("Amount must be greater than zero."))
        cash_cur = self.cash_account_id.currency_id or self.env.company.currency_id
        src_cur = self.source_account_id.currency_id or self.env.company.currency_id
        if cash_cur != src_cur:
            raise UserError(_(
                "Into (%(c)s) and From (%(s)s) are in different currencies. "
                "Use Internal Transfer for a cross-currency move so the exchange "
                "rate is handled correctly.")
                % {"c": cash_cur.name, "s": src_cur.name})
        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": self._cash_journal().id,
            "date": self.date,
            "ref": self.reference or self.description,
            "line_ids": [
                (0, 0, {"account_id": self.cash_account_id.id,
                        "name": self.description, "debit": self.amount, "credit": 0.0}),
                (0, 0, {"account_id": self.source_account_id.id,
                        "name": self.description, "debit": 0.0, "credit": self.amount}),
            ],
        })
        move.action_post()
        return {"type": "ir.actions.act_window_close"}
