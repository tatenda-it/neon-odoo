# -*- coding: utf-8 -*-
"""Strip 4 unwanted implied_ids from base.group_user +
re-assign meta-group tier users. Runs on `-u neon_core` from
version <17.0.1.0.0 to 17.0.1.0.0.

On fresh `-i`, _post_init_hook (in __init__.py) does both
operations. This migration is the upgrade path mirror so
re-running `-u neon_core` after manual UI tinkering re-
asserts the canonical state.

Idempotent: re-running is safe -- (3, id) remove of an absent
id silently succeeds; (4, id) add of present user is a no-op.

Reference: reference_odoo17_implied_ids_orm_vs_sql.md.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    from odoo.addons.neon_core import (
        _strip_base_user_leaks,
        _assign_tier_users,
        _reconcile_user_groups,
    )
    env = api.Environment(cr, SUPERUSER_ID, {})
    _logger.info(
        "neon_core migration: applying canonical RBAC state "
        "(upgrade path).")
    _strip_base_user_leaks(env)
    _assign_tier_users(env)
    _reconcile_user_groups(env)
