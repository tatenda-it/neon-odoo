# -*- coding: utf-8 -*-
"""
P6.M1.2 — grant Bookkeeper + Approver reach to the Accounting >
Configuration parent menu.

The .0.1 round added account.group_account_invoice (basic invoice
user, "Billing" in the Odoo UI) to Bookkeeper and Approver
implied_ids. That was the correct grant for native invoicing access,
but it does NOT include the implicit visibility on the
Configuration menu that Odoo gates with account.group_account_manager
(the full "Billing Administrator" scope). Without further work,
Kudzi/Robin/Munashe couldn't navigate to Configuration > Finance
even with Bookkeeper / Approver grants applied.

The fix is surgical: extend the Configuration parent's groups_id
to include our two finance roles directly, rather than implying
the broader account.group_account_manager (which would grant
journals / taxes / chart-of-accounts admin access we don't intend).

This migration runs the same write the XML data load does on
fresh installs, ensuring 17.0.6.0.1 -> 17.0.6.0.2 upgrade paths
also pick up the change.

Idempotent: (4, id) is no-op when the group is already in the
menu's groups_id.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    menu = env.ref(
        "account.menu_finance_configuration",
        raise_if_not_found=False)
    if not menu:
        _logger.warning(
            "P6.M1.2 post-migrate: account.menu_finance_configuration "
            "not found; skipping.")
        return

    bookkeeper = env.ref(
        "neon_finance.group_neon_finance_bookkeeper",
        raise_if_not_found=False)
    approver = env.ref(
        "neon_finance.group_neon_finance_approver",
        raise_if_not_found=False)

    add_ops = []
    if bookkeeper and bookkeeper not in menu.groups_id:
        add_ops.append((4, bookkeeper.id))
    if approver and approver not in menu.groups_id:
        add_ops.append((4, approver.id))

    if add_ops:
        menu.sudo().write({"groups_id": add_ops})
        names = [
            g.name for g in (bookkeeper, approver)
            if g and g in menu.groups_id]
        _logger.info(
            "P6.M1.2 post-migrate: account.menu_finance_configuration "
            "now reachable by %s.", ", ".join(names) or "(none)")
    else:
        _logger.info(
            "P6.M1.2 post-migrate: Configuration menu already grants "
            "Bookkeeper + Approver — no change.")
