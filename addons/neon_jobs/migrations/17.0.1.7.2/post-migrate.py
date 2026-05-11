# -*- coding: utf-8 -*-
"""
Migration to 17.0.1.7.2 — propagate Sales/Billing implications.

P2.M7.7 adds new implied_ids edges:
  - group_neon_jobs_user → sales_team.group_sale_salesman_all_leads
  - group_neon_jobs_manager → sales_team.group_sale_manager
                            + account.group_account_invoice

Adding implied_ids on a group via XML does NOT retroactively grant the
implied group to existing users — Odoo only applies the implication to
users granted the source group AFTER the edge exists. This migration
walks existing users in each source group and explicitly writes the
implied groups so the chain holds for everyone, not just new users.

Idempotent — re-running is a no-op for users that already carry the
implied group.
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

    def _propagate(source, implied, label):
        if not (source and implied):
            _logger.warning(
                "neon_jobs 17.0.1.7.2: skipped %s — source or implied "
                "group missing.", label,
            )
            return
        users = env["res.users"].search([("groups_id", "in", source.id)])
        added = 0
        for user in users:
            if implied not in user.groups_id:
                user.write({"groups_id": [(4, implied.id)]})
                added += 1
        _logger.info(
            "neon_jobs 17.0.1.7.2: propagated %s — added to %d of %d "
            "users in %s.",
            label, added, len(users), source.name,
        )

    _propagate(user_grp, salesman,
               "salesman_all_leads (via neon_jobs_user)")
    _propagate(manager_grp, sale_mgr,
               "sale_manager (via neon_jobs_manager)")
    _propagate(manager_grp, billing,
               "account.group_account_invoice (via neon_jobs_manager)")
