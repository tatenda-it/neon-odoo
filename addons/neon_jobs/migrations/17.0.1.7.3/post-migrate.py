# -*- coding: utf-8 -*-
"""
Migration to 17.0.1.7.3 — install the implied_ids edges that
P2.M7.7's security.xml edit couldn't.

Bug discovered during P2.M7.7 browser smoke setup: the implied_ids
field added in security.xml never landed because the group records
live inside <data noupdate="1">. Odoo skips updates to noupdate
records on -u; only the initial install applies them. P2.M7.7's
migration script propagated the implied groups to EXISTING users by
explicit grant, which masked the missing edge — but new users created
afterward did not auto-inherit the implication.

This migration sets the edges via ORM .write() on the source group,
which (a) persists them to res_groups_implied_rel and (b) triggers
Odoo's standard propagation: every existing user in the source group
gains the implied group automatically.

Idempotent — writing an already-implied edge is a no-op.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    user_grp = env.ref("neon_jobs.group_neon_jobs_user", raise_if_not_found=False)
    manager_grp = env.ref("neon_jobs.group_neon_jobs_manager", raise_if_not_found=False)
    salesman = env.ref("sales_team.group_sale_salesman_all_leads", raise_if_not_found=False)
    sale_mgr = env.ref("sales_team.group_sale_manager", raise_if_not_found=False)
    billing = env.ref("account.group_account_invoice", raise_if_not_found=False)

    def _ensure_edge(source, implied, label):
        if not (source and implied):
            _logger.warning(
                "neon_jobs 17.0.1.7.3: skipped %s — source or implied "
                "group missing.", label,
            )
            return
        if implied in source.implied_ids:
            _logger.info(
                "neon_jobs 17.0.1.7.3: implication edge already present "
                "for %s → %s.", source.name, label,
            )
            return
        source.write({"implied_ids": [(4, implied.id)]})
        _logger.info(
            "neon_jobs 17.0.1.7.3: added implication edge %s → %s "
            "(Odoo auto-propagates to existing users in %s).",
            source.name, label, source.name,
        )

    _ensure_edge(user_grp, salesman,
                 "sales_team.group_sale_salesman_all_leads")
    _ensure_edge(manager_grp, sale_mgr,
                 "sales_team.group_sale_manager")
    _ensure_edge(manager_grp, billing,
                 "account.group_account_invoice")
