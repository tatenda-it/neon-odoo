# -*- coding: utf-8 -*-
"""
Migration to 17.0.1.8.1 — propagate the new neon_jobs_user →
account.group_account_invoice implication to existing users.

Same noupdate-trap pattern as 17.0.1.7.3: the implied_ids edge in
security.xml lives inside <data noupdate="1">, so Odoo will not apply
the edge on -u of an existing install. Writing the edge imperatively
via ORM .write() persists it to res_groups_implied_rel AND triggers
Odoo's auto-propagation: every current member of neon_jobs_user gains
account.group_account_invoice (Billing) automatically.

Idempotent — re-running the migration is a no-op once the edge is in
place.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    user_grp = env.ref("neon_jobs.group_neon_jobs_user", raise_if_not_found=False)
    billing = env.ref("account.group_account_invoice", raise_if_not_found=False)

    if not (user_grp and billing):
        _logger.warning(
            "neon_jobs 17.0.1.8.1: skipped — neon_jobs_user or "
            "account.group_account_invoice missing.",
        )
        return

    if billing in user_grp.implied_ids:
        _logger.info(
            "neon_jobs 17.0.1.8.1: implication edge already present "
            "(neon_jobs_user → account.group_account_invoice).",
        )
        return

    user_grp.write({"implied_ids": [(4, billing.id)]})
    _logger.info(
        "neon_jobs 17.0.1.8.1: added implication edge neon_jobs_user → "
        "account.group_account_invoice (Odoo auto-propagates to existing "
        "members of neon_jobs_user).",
    )
