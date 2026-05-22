# -*- coding: utf-8 -*-
"""Add base.group_system + base.group_erp_manager to
group_neon_superuser.implied_ids.

Surfaced via post-deploy Chrome verification: Robin sees 11
apps after initial neon_core deploy but Settings missing.
group_no_one (Technical Features / developer mode) is NOT the
same as group_system (Administration / Settings menu access).
group_erp_manager (Access Rights) needed to manage users +
groups directly.

ORM (4, id) write per reference_odoo17_implied_ids_orm_vs_sql.md
-- raw SQL bypasses Odoo's implication-propagation hook.
Idempotent: (4, id) add of present id is a no-op.

Affects superuser tier ONLY. Bookkeeper / Sales Rep / Lead
Tech / Crew tiers stay unchanged -- Settings access stays
restricted to managerial superusers.
"""
import logging

_logger = logging.getLogger(__name__)


_ADDITIONS = [
    "base.group_system",
    "base.group_erp_manager",
]


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    superuser_group = env.ref(
        "neon_core.group_neon_superuser",
        raise_if_not_found=False)
    if not superuser_group:
        _logger.error(
            "neon_core 17.0.1.0.1 migration: superuser meta-group "
            "not found; aborting.")
        return

    for xmlid in _ADDITIONS:
        grp = env.ref(xmlid, raise_if_not_found=False)
        if not grp:
            _logger.warning(
                "neon_core 17.0.1.0.1: %s not in registry; skip.",
                xmlid)
            continue
        if grp in superuser_group.implied_ids:
            _logger.info(
                "neon_core 17.0.1.0.1: %s already in "
                "group_neon_superuser.implied_ids; no-op.", xmlid)
            continue
        superuser_group.sudo().write({
            "implied_ids": [(4, grp.id)],
        })
        _logger.info(
            "neon_core 17.0.1.0.1: added %s to "
            "group_neon_superuser.implied_ids (cascade triggers "
            "membership propagation to all 3 superuser members).",
            xmlid)
