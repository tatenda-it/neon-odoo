# -*- coding: utf-8 -*-
"""BANKING-SETUP post-migrate (corrective + idempotent).

Touches the EXISTING auto-created journals BNK1/CSH1 (no xml-id -> reached by
code in Python) and finishes the Undeposited Funds cash-routing. The two NEW
journals + accounts + the Banking menu are created by
data/banking_setup_data.xml (loads BEFORE this script).

Does:
  1. rename BNK1 "Bank" -> "CABS (USD) - Neon Events Elements", CSH1 -> "Petty Cash".
  2. ⚠️ ensure NO res.partner.bank is linked to BNK1/BNK2. Linking a company
     CABS account to a journal makes out_invoices default partner_bank_id to it,
     which routes the Register-Payment default journal by partner-bank match
     (a USD SCH- invoice would default to the ZWG journal -- regression). So the
     informational bank number is deliberately NOT attached.
  3. route the Undeposited Funds journal's payments to account 101406 (its own
     account) so a cash receipt LANDS in Undeposited Funds (Zoho "Deposit To:
     Undeposited") and the dashboard card reflects it -- instead of the shared
     company Outstanding Receipts (101403).

⚠️ Modifies EXISTING live journal rows -> on prod this is a hard gate (separate
GO). Idempotent: only writes when the value differs; safe to re-run.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

USD_BANK_NAME = "CABS (USD) - Neon Events Elements"
PETTY_CASH_NAME = "Petty Cash"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Journal = env["account.journal"]
    Account = env["account.account"]

    bnk1 = Journal.search([("code", "=", "BNK1")], limit=1)
    bnk2 = Journal.search([("code", "=", "BNK2")], limit=1)
    csh1 = Journal.search([("code", "=", "CSH1")], limit=1)
    undf = Journal.search([("code", "=", "CASH")], limit=1)

    # 1. renames
    if bnk1 and bnk1.name != USD_BANK_NAME:
        _logger.info("BANKING-SETUP: renaming BNK1 %r -> %r", bnk1.name, USD_BANK_NAME)
        bnk1.name = USD_BANK_NAME
    if csh1 and csh1.name != PETTY_CASH_NAME:
        _logger.info("BANKING-SETUP: renaming CSH1 %r -> %r", csh1.name, PETTY_CASH_NAME)
        csh1.name = PETTY_CASH_NAME

    # 2. ensure no bank-account link on the bank journals (preserve the SCH-
    #    default-journal behaviour). Corrective: unlink if a prior run linked it.
    for j in (bnk1, bnk2):
        if j and j.bank_account_id:
            _logger.info("BANKING-SETUP: unlinking bank_account from %s (SCH- default-journal safety)", j.code)
            j.bank_account_id = False

    # 3. Undeposited Funds cash-routing -> account 101406
    undf_acct = Account.search([("code", "=", "101406")], limit=1)
    if undf and undf_acct:
        if not undf_acct.reconcile:
            undf_acct.reconcile = True
        lines = undf.inbound_payment_method_line_ids | undf.outbound_payment_method_line_ids
        to_fix = lines.filtered(lambda l: l.payment_account_id != undf_acct)
        if to_fix:
            _logger.info("BANKING-SETUP: routing Undeposited Funds journal payments -> 101406")
            to_fix.write({"payment_account_id": undf_acct.id})

    _logger.info("BANKING-SETUP: done.")
