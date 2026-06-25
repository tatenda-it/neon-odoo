# -*- coding: utf-8 -*-
"""Stage-3 journal-entry quick-entries: Owner/Directors Drawings, Commission,
Owner Contribution / Other Money-In, Transfer / Deposit.

Each posts a plain two-line native account.move (NO suspense, NO reconcile, NO
Dr/Cr jargon shown). The target equity/expense/income account is an editable
M2O defaulted to a sensible account; the bookkeeper never touches the journal.

Money OUT (Dr target / Cr cash): Drawings, Commission.
Money IN  (Dr cash / Cr source): Owner Contribution / Other Money-In.
Between accounts (Dr to / Cr from): Transfer / Deposit -- same-currency only;
cross-currency is blocked (needs an FX rate, handled from the bank).
"""
from odoo import _, fields, models
from odoo.exceptions import UserError


def _acct_by_code(env, code):
    return env["account.account"].search([("code", "=", code)], limit=1).id or False


class NeonCashDrawingsWizard(models.TransientModel):
    _name = "neon.cash.drawings.wizard"
    _inherit = "neon.cash.entry.mixin"
    _description = "Owner / Directors Drawings (cash/bank)"

    cash_account_id = fields.Many2one(string="Paid From")
    drawings_account_id = fields.Many2one(
        "account.account", string="Drawings Account", required=True,
        domain="[('account_type','=','equity')]",
        default=lambda self: _acct_by_code(self.env, "303000"),
        help="The equity account drawings are charged to.")
    payee_id = fields.Many2one("res.partner", string="Payee")
    description = fields.Char(string="Details", required=True)

    def action_save(self):
        self.ensure_one()
        self._check_amount()
        self._guard_company_currency_cash(_("Paid From"))
        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": self._cash_journal().id,
            "date": self.date,
            "ref": self.reference or self.description,
            "partner_id": self.payee_id.id or False,
            "line_ids": [
                (0, 0, {"account_id": self.drawings_account_id.id,
                        "name": self.description, "debit": self.amount, "credit": 0.0}),
                (0, 0, {"account_id": self.cash_account_id.id,
                        "name": self.description, "debit": 0.0, "credit": self.amount}),
            ],
        })
        move.action_post()
        return {"type": "ir.actions.act_window_close"}


class NeonCashCommissionWizard(models.TransientModel):
    _name = "neon.cash.commission.wizard"
    _inherit = "neon.cash.entry.mixin"
    _description = "Commission (cash/bank)"

    cash_account_id = fields.Many2one(string="Paid From")
    commission_account_id = fields.Many2one(
        "account.account", string="Commission Account", required=True,
        domain="[('account_type','=','expense')]",
        default=lambda self: _acct_by_code(self.env, "627000"),
        help="The expense account commission is charged to.")
    payee_id = fields.Many2one("res.partner", string="Payee")
    description = fields.Char(string="Details", required=True)

    def action_save(self):
        self.ensure_one()
        self._check_amount()
        self._guard_company_currency_cash(_("Paid From"))
        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": self._cash_journal().id,
            "date": self.date,
            "ref": self.reference or self.description,
            "partner_id": self.payee_id.id or False,
            "line_ids": [
                (0, 0, {"account_id": self.commission_account_id.id,
                        "name": self.description, "debit": self.amount, "credit": 0.0}),
                (0, 0, {"account_id": self.cash_account_id.id,
                        "name": self.description, "debit": 0.0, "credit": self.amount}),
            ],
        })
        move.action_post()
        return {"type": "ir.actions.act_window_close"}


class NeonCashContributionWizard(models.TransientModel):
    _name = "neon.cash.contribution.wizard"
    _inherit = "neon.cash.entry.mixin"
    _description = "Owner Contribution / Other Money-In (cash/bank)"

    cash_account_id = fields.Many2one(string="Into")
    credit_account_id = fields.Many2one(
        "account.account", string="Source Account", required=True,
        domain="[('account_type','in',('equity','income','income_other'))]",
        default=lambda self: _acct_by_code(self.env, "301000"),
        help="Where the money comes from in the books -- owner capital, or an "
             "income account for other money-in.")
    description = fields.Char(string="Details", required=True)

    def action_save(self):
        self.ensure_one()
        self._check_amount()
        self._guard_company_currency_cash(_("Into"))
        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": self._cash_journal().id,
            "date": self.date,
            "ref": self.reference or self.description,
            "line_ids": [
                (0, 0, {"account_id": self.cash_account_id.id,
                        "name": self.description, "debit": self.amount, "credit": 0.0}),
                (0, 0, {"account_id": self.credit_account_id.id,
                        "name": self.description, "debit": 0.0, "credit": self.amount}),
            ],
        })
        move.action_post()
        return {"type": "ir.actions.act_window_close"}


class NeonCashTransferWizard(models.TransientModel):
    _name = "neon.cash.transfer.wizard"
    _inherit = "neon.cash.entry.mixin"
    _description = "Transfer / Deposit between cash/bank accounts"

    cash_account_id = fields.Many2one(string="From")
    dest_account_id = fields.Many2one(
        "account.account", string="To", required=True,
        domain="[('account_type','in',('asset_cash','asset_current'))]",
        help="The cash/bank account the money moves into.")
    description = fields.Char(string="Details", required=True)

    def action_save(self):
        self.ensure_one()
        self._check_amount()
        if self.dest_account_id == self.cash_account_id:
            raise UserError(_("From and To must be different accounts."))
        # Same-currency only, and company-currency only: a plain Dr/Cr move can't
        # carry a clean foreign-currency line without an FX rate. The same-currency
        # check blocks USD<->ZWG; the company-currency check additionally blocks a
        # same-but-foreign pairing (e.g. a second ZWG account added later).
        self._guard_same_currency(self.dest_account_id, _("From"), _("To"))
        self._guard_company_currency_cash(_("From"))
        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": self._cash_journal().id,
            "date": self.date,
            "ref": self.reference or self.description,
            "line_ids": [
                (0, 0, {"account_id": self.dest_account_id.id,
                        "name": self.description, "debit": self.amount, "credit": 0.0}),
                (0, 0, {"account_id": self.cash_account_id.id,
                        "name": self.description, "debit": 0.0, "credit": self.amount}),
            ],
        })
        move.action_post()
        return {"type": "ir.actions.act_window_close"}
