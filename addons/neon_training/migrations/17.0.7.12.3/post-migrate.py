# -*- coding: utf-8 -*-
"""
P7a pre-deploy fix #2 post-migrate (21 May 2026).

Two actions, run together so install/upgrade state is
deterministic:

1. Clear menu_neon_training_root.groups_id (the D-path menu
   XML change is groups="" but Odoo's loader leaves the
   stale ir_ui_menu_group_rel rows in place on -u; this
   script forces the clear via SQL).

2. Grant group_neon_training_admin to base.user_admin
   (data-file approach via <record id="base.user_admin" ...>
   is silently skipped because base.user_admin was created
   with noupdate=True in the base module; ORM write via the
   post-migrate is the reliable path).

POST-FINDING-#3 FIX (21 May 2026): action 2 originally used
raw SQL INSERT into res_groups_users_rel, which bypasses
Odoo's `res.groups.users` write hook that fires implied_ids
propagation. The result: Robin landed in training_admin only,
NOT in the implied training_signoff + training_user that he
should have inherited from training_admin.implied_ids. The
ORM `write({"users": [(4, id)]})` triggers propagation; the
raw SQL did not. See reference_odoo17_implied_ids_orm_vs_sql
.md for the broader pattern.

Idempotent: both actions are safe to re-run.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Apply the two-layer admin-visibility fix.

    Args:
      cr:      database cursor
      version: installed version we're upgrading FROM. None on
               fresh install (-i).
    """
    # Action 1: clear menu_neon_training_root.groups_id (upgrade
    # path only -- fresh install via the menu XML's groups=""
    # writes the empty state correctly).
    if version:
        cr.execute(
            "SELECT res_id FROM ir_model_data "
            "WHERE module = 'neon_training' "
            "  AND name   = 'menu_neon_training_root' "
            "  AND model  = 'ir.ui.menu' "
            "LIMIT 1"
        )
        row = cr.fetchone()
        if row:
            cr.execute(
                "DELETE FROM ir_ui_menu_group_rel "
                "WHERE menu_id = %s",
                (row[0],))

    # Action 2: grant group_neon_training_admin to
    # base.user_admin via the ORM so implied_ids propagation
    # cascades to training_signoff + training_user. Raw SQL
    # INSERT was the original implementation but it bypassed
    # the propagation hook (finding #3).
    env = api.Environment(cr, SUPERUSER_ID, {})
    admin = env.ref("base.user_admin", raise_if_not_found=False)
    grp = env.ref(
        "neon_training.group_neon_training_admin",
        raise_if_not_found=False)
    if admin and grp:
        # The (4, id) operator is idempotent: adds the link if
        # missing, no-op if present. The write hook on
        # res.groups.users fires implied_ids propagation, so
        # admin lands in training_admin + training_signoff +
        # training_user in one call.
        grp.write({"users": [(4, admin.id)]})
