# -*- coding: utf-8 -*-
"""
P6.M1.3 — extend account.menu_finance (Accounting app root) to
Bookkeeper + Approver + the Odoo default Billing roles.

The Phase 2 P2.M7.8.1 cross-module gate replaces
account.menu_finance.groups_id with [neon_jobs_user,
neon_jobs_manager] on every -u. That gate is correct for ops users
but blocks pure finance roles (Bookkeeper, Approver) from reaching
the Accounting app at all, which hides the Configuration > Finance
submenu we wired in P6.M1.

This migration runs the same (4, id) ADD the XML data load
performs on fresh installs, ensuring existing-install upgrade
paths (17.0.6.0.2 -> 17.0.6.0.3) pick up the extension too.

Idempotent: (4, id) is a no-op when the group is already in the
menu's groups_id.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    menu = env.ref("account.menu_finance", raise_if_not_found=False)
    if not menu:
        _logger.warning(
            "P6.M1.3 post-migrate: account.menu_finance not found; "
            "skipping.")
        return

    refs = (
        "account.group_account_manager",
        "account.group_account_invoice",
        "neon_finance.group_neon_finance_bookkeeper",
        "neon_finance.group_neon_finance_approver",
    )

    add_ops = []
    added_names = []
    for xid in refs:
        g = env.ref(xid, raise_if_not_found=False)
        if not g:
            _logger.warning(
                "P6.M1.3 post-migrate: %s not found; skipping that "
                "edge.", xid)
            continue
        if g not in menu.groups_id:
            add_ops.append((4, g.id))
            added_names.append(g.name)

    if add_ops:
        menu.sudo().write({"groups_id": add_ops})
        _logger.info(
            "P6.M1.3 post-migrate: account.menu_finance extended "
            "with %s.", ", ".join(added_names))
    else:
        _logger.info(
            "P6.M1.3 post-migrate: account.menu_finance already "
            "grants all four finance / billing roles; no change.")
