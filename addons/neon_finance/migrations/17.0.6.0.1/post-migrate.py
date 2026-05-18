# -*- coding: utf-8 -*-
"""
P6.M1 — write implied_ids edges that the .0.0 install missed.

security/security.xml wraps the four neon_finance group records in
<data noupdate="1">. That means `-u neon_finance` SILENTLY IGNORES
any change to the implied_ids field once the group record exists.
The codebase pattern (documented at the top of
addons/neon_jobs/security/security.xml) is: every time an
implied_ids edge is added or removed, ship a migration that writes
the change explicitly.

This migration backfills the Billing Administrator implication on
Bookkeeper and Approver — added during the P6.M1 pre-commit
browser-smoke round when we discovered that without
account.group_account_invoice, the Accounting > Configuration menu
stayed hidden and the Finance submenu was unreachable.

The Sales group is checked too: we explicitly REMOVE the edge if
it ever got added (defensive, current state already correct), per
the P6.M1 spec that sales reps create quotes but do not work the
invoicing UI.

Idempotent: (4, id) is no-op when already present; (3, id) is no-op
when absent.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    billing_admin = env.ref(
        "account.group_account_invoice", raise_if_not_found=False)
    if not billing_admin:
        _logger.warning(
            "P6.M1.1 post-migrate: account.group_account_invoice "
            "missing; cannot wire billing_admin edges. Skipping.")
        return

    for xid in (
        "neon_finance.group_neon_finance_bookkeeper",
        "neon_finance.group_neon_finance_approver",
    ):
        g = env.ref(xid, raise_if_not_found=False)
        if not g:
            _logger.warning(
                "P6.M1.1 post-migrate: %s missing; skip.", xid)
            continue
        if billing_admin in g.implied_ids:
            _logger.info(
                "P6.M1.1 post-migrate: %s already implies "
                "billing_admin.", xid)
            continue
        g.sudo().write({
            "implied_ids": [(4, billing_admin.id)],
        })
        _logger.info(
            "P6.M1.1 post-migrate: %s now implies "
            "account.group_account_invoice.", xid)

    sales = env.ref(
        "neon_finance.group_neon_finance_sales",
        raise_if_not_found=False)
    if sales and billing_admin in sales.implied_ids:
        sales.sudo().write({
            "implied_ids": [(3, billing_admin.id)],
        })
        _logger.info(
            "P6.M1.1 post-migrate: removed billing_admin from "
            "group_neon_finance_sales (sales does not run "
            "the invoicing UI per P6.M1 spec).")
