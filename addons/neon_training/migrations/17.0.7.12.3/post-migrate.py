# -*- coding: utf-8 -*-
"""
P7a pre-deploy fix #2 post-migrate (21 May 2026).

Two actions, run together so install/upgrade state is
deterministic:

1. Clear menu_neon_training_root.groups_id (the D-path menu
   XML change is groups="" but Odoo's loader leaves the
   stale ir_ui_menu_group_rel rows in place on -u; this
   script forces the clear).

2. Grant group_neon_training_admin to base.user_admin (the
   data-file approach via <record id="base.user_admin" ...>
   is silently skipped because base.user_admin was created
   with noupdate=True in the base module, so cross-module
   XML updates to its groups_id don't land. A direct ORM
   write via the post-migrate hook is the reliable path).

Idempotent: both actions are safe to run multiple times.
The script fires on every -u from a prior installed version;
fresh installs skip the menu clear (no stale rows) but still
need the group grant -- the grant runs unconditionally.
"""


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
    # base.user_admin. Required for the canonical admin user
    # (Robin per Neon's deploy) to see the Training app in the
    # apps switcher (_filter_visible_menus requires at least
    # one visible child of the root, and all children carry
    # groups_id).
    cr.execute(
        "SELECT res_id FROM ir_model_data "
        "WHERE module = 'base' AND name = 'user_admin' "
        "LIMIT 1"
    )
    admin_row = cr.fetchone()
    cr.execute(
        "SELECT res_id FROM ir_model_data "
        "WHERE module = 'neon_training' "
        "  AND name   = 'group_neon_training_admin' "
        "LIMIT 1"
    )
    group_row = cr.fetchone()
    if admin_row and group_row:
        admin_id = admin_row[0]
        group_id = group_row[0]
        # Idempotent INSERT: ON CONFLICT DO NOTHING handles the
        # re-run case cleanly.
        cr.execute(
            "INSERT INTO res_groups_users_rel (uid, gid) "
            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (admin_id, group_id))
