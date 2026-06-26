# -*- coding: utf-8 -*-
"""CORRECT THIS ENTRY -- audit-clean fix of a logged cash entry (reverse + re-enter).

Reverses the original posted move (native account.move._reverse_moves -- the
original STAYS, an offsetting reversal is posted, append-only preserved) and
posts a fresh CORRECTED entry from pre-filled (editable) values. Net effect:
original + reversal (net zero) + corrected entry, all in the statement.

Scope = the wizard-created cash JOURNAL entries (Expense / Replenishment /
Drawings / Commission / Money-In / Transfer). Payments (account.payment) and
bank-statement lines are NOT corrected here -- they have native cancel/reverse
flows, and routing them here would bypass the cross-currency register guard. No
free-edit/delete of posted entries; the reversal is the only mutation.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_CASH_CODES = ("101501", "101401", "101405", "101406")


class NeonCashCorrectWizard(models.TransientModel):
    _name = "neon.cash.correct.wizard"
    _inherit = "neon.cash.entry.mixin"
    _description = "Correct a logged cash entry (reverse + re-enter)"

    original_move_id = fields.Many2one("account.move", string="Original Entry", required=True)
    original_summary = fields.Char(string="Correcting", readonly=True)
    cash_account_id = fields.Many2one(string="Cash / Bank Account", readonly=True)
    counterpart_account_id = fields.Many2one(
        "account.account", string="Account", required=True,
        help="The account the corrected entry posts against (the other side of the cash movement).")
    is_outflow = fields.Boolean(string="Money out", readonly=True)
    tax_id = fields.Many2one("account.tax", string="Tax", domain="[('type_tax_use','in',('purchase','sale'))]")
    tax_treatment = fields.Selection(
        [("exclusive", "Tax Exclusive"), ("inclusive", "Tax Inclusive")],
        string="Amount is", default="exclusive")
    description = fields.Char(string="Details", required=True)
    reversal_date = fields.Date(string="Reversal Date", required=True, default=fields.Date.context_today)

    # ---- classification + pre-fill -------------------------------------
    @api.model
    def _correctable_or_raise(self, move):
        if not move or move.state != "posted":
            raise UserError(_("Only a posted entry can be corrected."))
        if move.move_type != "entry":
            raise UserError(_("This is an invoice/bill, not a cash entry. Use its own flow."))
        if move.payment_id or move.statement_line_id:
            raise UserError(_(
                "This entry is a payment or a bank-statement line. Correct it from "
                "its own screen (Record Payment / Reconciliation), not here."))
        if move.reversed_entry_id:
            raise UserError(_("This entry is itself a reversal and cannot be corrected."))
        if move.reversal_move_id:
            raise UserError(_("This entry has already been reversed/corrected."))
        if not move.line_ids.filtered(lambda l: l.account_id.code in _CASH_CODES):
            raise UserError(_("This entry has no cash/bank line and is not a cash entry."))
        return move

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        move = self.env["account.move"].browse(self.env.context.get("default_original_move_id"))
        if not move and self.env.context.get("active_model") == "account.move.line":
            move = self.env["account.move.line"].browse(self.env.context.get("active_id")).move_id
        if not move:
            return res
        self._correctable_or_raise(move)
        cash = move.line_ids.filtered(lambda l: l.account_id.code in _CASH_CODES)[:1]
        tax_line = move.line_ids.filtered(lambda l: l.tax_line_id)[:1]
        counterpart = (move.line_ids - cash - tax_line)[:1]
        is_out = cash.credit > 0
        res.update({
            "original_move_id": move.id,
            "original_summary": "%s | %s | %s" % (move.name, move.date, move.ref or ""),
            "cash_account_id": cash.account_id.id,
            "counterpart_account_id": counterpart.account_id.id,
            "is_outflow": is_out,
            "date": move.date,
            "description": (counterpart.name or move.ref or ""),
            "reversal_date": fields.Date.context_today(self),
        })
        if counterpart.tax_ids:
            res["tax_id"] = counterpart.tax_ids[:1].id
            res["tax_treatment"] = "exclusive"
            res["amount"] = abs(counterpart.balance)   # net
        else:
            res["amount"] = abs(cash.balance)
        return res

    # ---- amounts (mirror the Expense wizard's net/gross split) ----------
    def _amounts(self):
        currency = self.currency_id or self.env.company.currency_id
        if not self.tax_id:
            return self.amount, self.amount
        rate = self.tax_id.amount / 100.0
        net = currency.round(self.amount / (1.0 + rate)) if self.tax_treatment == "inclusive" else self.amount
        return net, self.tax_id.compute_all(net, currency, 1.0)["total_included"]

    def _check_period(self):
        lock = self.original_move_id.company_id.fiscalyear_lock_date
        if lock and (self.reversal_date <= lock or self.date <= lock):
            raise UserError(_(
                "The period is locked up to %s. Pick a reversal/entry date after "
                "that, or ask the accountant to adjust the lock date.") % lock)

    def action_post_correction(self):
        self.ensure_one()
        self._check_amount()
        move = self._correctable_or_raise(self.original_move_id)
        self._guard_company_currency_cash(_("Cash / Bank Account"))
        self._check_period()

        # 1) reverse the original (it stays; post the offsetting reversal so it
        #    actually nets in the statement -- _reverse_moves leaves it draft).
        reversal = move._reverse_moves([{
            "date": self.reversal_date,
            "ref": _("Correction reversal of %s") % move.name,
        }])
        reversal.action_post()

        # 2) post the corrected entry (same native account.move path the wizards use)
        net, gross = self._amounts()
        cp_line = {"account_id": self.counterpart_account_id.id, "name": self.description}
        cash_line = {"account_id": self.cash_account_id.id, "name": self.description}
        if self.is_outflow:                      # money out: Dr counterpart / Cr cash
            cp_line.update(debit=net, credit=0.0)
            cash_line.update(debit=0.0, credit=gross)
        else:                                    # money in: Dr cash / Cr counterpart
            cp_line.update(debit=0.0, credit=net)
            cash_line.update(debit=gross, credit=0.0)
        if self.tax_id:
            cp_line["tax_ids"] = [(6, 0, [self.tax_id.id])]
        corrected = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": self._cash_journal().id,
            "date": self.date,
            "ref": self.reference or self.description,
            "line_ids": [(0, 0, cp_line), (0, 0, cash_line)],
        })
        corrected.action_post()
        return {"type": "ir.actions.act_window_close"}
