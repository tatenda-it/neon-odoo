# -*- coding: utf-8 -*-
"""Guard a core Odoo 17.0 bug in account.bank.statement._get_invalid_statement_ids.

⚠️ CORE BUG (not ours): account/models/account_bank_statement.py builds
    ... AND st.journal_id IN %(journal_ids)s
with journal_ids = tuple(set(self.journal_id.ids)). When _compute_is_valid runs
on a recordset whose statements have NO journal_id -- e.g. the journal-less
NewId statement(s) created when a user clicks "New Transaction" on a
zero-statement cash/bank journal dashboard card -- that tuple is empty and
psycopg2 interpolates `journal_id IN ()`, a SQL syntax error.

This is journal-AGNOSTIC: the original auto-created Bank/Cash journals hit it
identically; the BANKING-SETUP work only EXPOSED it (the Banking shortcut +
named cards mean the bookkeeper now clicks "New Transaction"). Odoo 17.0.0
(base, FINAL) ships the unguarded code; a later 17.0 commit fixes it upstream,
but this instance is on base 17.0.0, so we guard it surgically here rather than
upgrade the whole account module.

Fix: when there are no concrete journals to scope the validity query (and we
are not in the all_statements path, which omits the IN clause), there is
nothing to validate -- return []. The normal path (statements WITH journals)
and the all_statements search path both fall straight through to super().
"""
from odoo import models


class AccountBankStatement(models.Model):
    _inherit = "account.bank.statement"

    def _get_invalid_statement_ids(self, all_statements=None):
        # Empty journal set on the scoped path -> core builds "IN ()" -> crash.
        # No journals means no statements to compare against -> none invalid.
        if not all_statements and not self.journal_id.ids:
            return []
        return super()._get_invalid_statement_ids(all_statements=all_statements)
