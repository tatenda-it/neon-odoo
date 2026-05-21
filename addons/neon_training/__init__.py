# -*- coding: utf-8 -*-
from . import models
from . import wizard


def _post_init_hook(env):
    """P7a pre-deploy fix #2 (21 May 2026): grant
    group_neon_training_admin to base.user_admin on fresh
    install. Mirrors the post-migrate action; migrations only
    fire on -u, so fresh installs (-i) need this hook to
    provision admin's training-tier access. Required for the
    Training root menu to appear in the apps switcher (Odoo's
    _filter_visible_menus rule: a parent with no action and
    only groups_id-gated children is hidden if no child is
    visible to the user; base.user_admin must hold at least
    one training-tier group).

    Idempotent via the (4, id) operator -- adding an already
    -present group is a no-op.
    """
    admin = env.ref("base.user_admin", raise_if_not_found=False)
    grp = env.ref(
        "neon_training.group_neon_training_admin",
        raise_if_not_found=False)
    if admin and grp:
        grp.sudo().write({"users": [(4, admin.id)]})
