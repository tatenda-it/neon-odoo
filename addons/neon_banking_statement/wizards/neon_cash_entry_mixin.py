# -*- coding: utf-8 -*-
"""Shared base for the Stage-3 "Add Transaction" quick-entry wizards.

Factors out the helpers Stage 2 proved (cash-account-from-context defaulting,
cash/bank journal resolution, currency-on-the-statement, amount + same-currency
guards) so each Stage-3 type stays a short, declarative wizard. Stage-2's two
wizards predate this mixin and are intentionally left untouched.

Nothing here posts anything; subclasses build the native account.move /
account.payment in their own action_save.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class NeonCashEntryMixin(models.AbstractModel):
    _name = "neon.cash.entry.mixin"
    _description = "Neon cash quick-entry shared base"

    cash_account_id = fields.Many2one(
        "account.account", string="Cash / Bank Account", required=True,
        domain="[('account_type','in',('asset_cash','asset_current'))]",
        help="The cash/bank account this transaction moves money on.")
    date = fields.Date(string="Date", required=True, default=fields.Date.context_today)
    amount = fields.Monetary(string="Amount", required=True, currency_field="currency_id")
    reference = fields.Char(string="Reference #")
    description = fields.Char(string="Details")
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
        if code and "cash_account_id" in self._fields and not res.get("cash_account_id"):
            acc = self.env["account.account"].search([("code", "=", code)], limit=1)
            if acc:
                res["cash_account_id"] = acc.id
        return res

    def _cash_journal(self):
        """The cash/bank journal whose default account is this cash account."""
        self.ensure_one()
        j = self.env["account.journal"].search(
            [("default_account_id", "=", self.cash_account_id.id),
             ("type", "in", ("bank", "cash"))], limit=1)
        if not j:
            raise UserError(_(
                "No cash/bank journal is set up for account %s.")
                % self.cash_account_id.display_name)
        return j

    def _check_amount(self):
        if self.amount <= 0:
            raise UserError(_("Amount must be greater than zero."))

    def _account_currency(self, account):
        return account.currency_id or self.env.company.currency_id

    def _guard_company_currency_cash(self, label):
        """Plain Dr/Cr equity entries can't carry a clean foreign-currency line
        without an FX rate. Restrict them to company-currency cash accounts;
        foreign-currency cash movements go through the bank with a rate."""
        company_currency = self.env.company.currency_id
        cash_cur = self.cash_account_id.currency_id
        if cash_cur and cash_cur != company_currency:
            raise UserError(_(
                "%(label)s is in %(c)s. This entry type currently supports "
                "%(co)s accounts only -- record a %(c)s movement from the bank "
                "with the agreed exchange rate instead.") % {
                    "label": label, "c": cash_cur.name, "co": company_currency.name})

    def _guard_same_currency(self, other_account, this_label, other_label):
        """Block a single-rate move between two differently-denominated cash
        accounts -- cross-currency needs FX handling, not a quick entry."""
        this_cur = self._account_currency(self.cash_account_id)
        other_cur = self._account_currency(other_account)
        if this_cur != other_cur:
            raise UserError(_(
                "%(this_label)s (%(c)s) and %(other_label)s (%(o)s) are in "
                "different currencies. A cross-currency move needs an exchange "
                "rate, so it can't be entered here -- record it from the bank "
                "with the agreed rate instead.") % {
                    "this_label": this_label, "other_label": other_label,
                    "c": this_cur.name, "o": other_cur.name})
