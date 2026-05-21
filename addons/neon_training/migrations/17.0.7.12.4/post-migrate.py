# -*- coding: utf-8 -*-
"""
P7a pre-deploy fix #3 post-migrate (21 May 2026).

Catch-up migration for DBs that already ran the 17.0.7.12.3
post-migrate with the raw-SQL bug. Those DBs have
base.user_admin in group_neon_training_admin but missing the
implied training_signoff + training_user (propagation never
fired because raw SQL bypassed the ORM hook).

This migration re-runs the ORM write so the implied_ids
chain propagates the existing training_admin membership down
to training_signoff + training_user. Idempotent: write (4, id)
is a no-op when admin is already in training_admin, and the
propagation hook fires regardless, populating the chain.

Fresh installs do NOT need this migration -- the corrected
17.0.7.12.3 post-migrate handles it. This file fires only on
-u from 17.0.7.12.3 to 17.0.7.12.4.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Re-run the admin group grant via ORM so implied_ids
    propagation lands. Safe on any DB state: ORM (4, id) is
    idempotent and the write hook always re-evaluates the
    implied chain.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    admin = env.ref("base.user_admin", raise_if_not_found=False)
    grp = env.ref(
        "neon_training.group_neon_training_admin",
        raise_if_not_found=False)
    if admin and grp:
        grp.write({"users": [(4, admin.id)]})
