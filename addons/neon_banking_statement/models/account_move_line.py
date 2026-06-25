# -*- coding: utf-8 -*-
"""Per-account running-ledger statement -- READ-ONLY computed fields over the
existing ledger (account.move.line). NO posting logic, NO write-path change.

Running balance: Odoo has no native per-transaction running balance. We add a
NON-STORED computed field that, for each line, returns the TRUE cumulative
balance of its account ordered by (date, id) -- computed over the FULL posted
history of that account up to the line, NOT just the visible/filtered page. So
it is correct under any filtering, ordering, or paging of the statement view.

Company currency (debit/credit/balance): exact for Petty Cash + CABS (USD)
(company-currency accounts). ⚠️ For a foreign-currency account (CABS (ZWG)) the
figures are the company-currency (USD) equivalents; a native-foreign-currency
variant (amount_currency-based) is a documented currency refinement for that
account, not built in Stage 1.
"""
from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    neon_running_balance = fields.Monetary(
        string="Balance",
        compute="_compute_neon_running_balance",
        currency_field="company_currency_id",
        help="Running balance of this account, cumulative by date then entry "
             "order, over the account's full posted history.")
    neon_counterpart_code = fields.Char(
        string="Acc Code",
        compute="_compute_neon_counterpart_code",
        help="The counterpart account this line is posted against.")

    @api.depends("balance", "date", "account_id", "parent_state")
    def _compute_neon_running_balance(self):
        # default (covers empty set + non-posted lines cleanly -> no crash)
        self.neon_running_balance = 0.0
        account_ids = self.account_id.ids
        if not account_ids:
            return
        AML = self.env["account.move.line"].sudo()
        for acc_id in set(account_ids):
            # full posted history of this account, in statement order
            history = AML.search(
                [("account_id", "=", acc_id), ("parent_state", "=", "posted")],
                order="date, id")
            running = 0.0
            running_map = {}
            for ml in history:
                running += ml.balance
                running_map[ml.id] = running
            for line in self.filtered(lambda l: l.account_id.id == acc_id):
                line.neon_running_balance = running_map.get(line.id, 0.0)

    @api.depends("move_id.line_ids.account_id", "account_id")
    def _compute_neon_counterpart_code(self):
        for line in self:
            others = line.move_id.line_ids.filtered(
                lambda l: l.account_id and l.account_id != line.account_id)
            codes = list(dict.fromkeys(others.account_id.mapped("code")))
            if not codes:
                line.neon_counterpart_code = ""
            elif len(codes) == 1:
                line.neon_counterpart_code = codes[0]
            else:
                line.neon_counterpart_code = ", ".join(codes)
