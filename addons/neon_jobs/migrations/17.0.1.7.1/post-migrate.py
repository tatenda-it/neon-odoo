# -*- coding: utf-8 -*-
"""
Migration to 17.0.1.7.1 — post-migrate: dismantle the implication
leak and explicitly assign neon_jobs_user to plain internal users.

P2.M1's post_init_hook added base.group_user → group_neon_jobs_user
as an implied edge. Every internal user, including Crew Members and
Crew Leaders created later, auto-inherited the User tier. P2.M7.6
removes the implication going forward AND cleans up DBs that already
applied it.

Steps (idempotent):
1. Drop the implied_ids edge from base.group_user → neon_jobs_user.
2. For each user that currently has neon_jobs_user AND ALSO has
   neon_jobs_crew or neon_jobs_crew_leader: strip neon_jobs_user.
   They retain their tier. (Managers are unaffected — Manager still
   implies User via security.xml, intentionally.)
3. For each internal user (base.group_user) with NO neon tier at
   all: add neon_jobs_user explicitly so sales reps keep their
   access after step 1 retracts the implication for new users.
4. Log a warning for any internal user with Sales-menu visibility
   but no neon tier — flags a configuration drift for the admin.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    internal_grp = env.ref("base.group_user")
    user_grp = env.ref("neon_jobs.group_neon_jobs_user")
    manager_grp = env.ref("neon_jobs.group_neon_jobs_manager")
    crew_grp = env.ref("neon_jobs.group_neon_jobs_crew")
    leader_grp = env.ref("neon_jobs.group_neon_jobs_crew_leader")

    # === Step 1: drop the implication edge ===
    if user_grp in internal_grp.implied_ids:
        internal_grp.write({"implied_ids": [(3, user_grp.id)]})
        _logger.info(
            "neon_jobs 17.0.1.7.1: dropped implied edge "
            "base.group_user → group_neon_jobs_user."
        )

    # === Step 2: strip leaked user-tier from crew / crew_leader users ===
    leaked = env["res.users"].search([
        ("groups_id", "in", user_grp.id),
        "|",
        ("groups_id", "in", crew_grp.id),
        ("groups_id", "in", leader_grp.id),
    ])
    for user in leaked:
        # Manager genuinely implies user via security.xml — don't strip
        # those; they're entitled to user-tier.
        if manager_grp in user.groups_id:
            continue
        user.write({"groups_id": [(3, user_grp.id)]})
        _logger.info(
            "neon_jobs 17.0.1.7.1: stripped neon_jobs_user from %s "
            "(crew/crew_leader user).",
            user.login,
        )

    # === Step 3: explicit grant to plain internal users ===
    candidates = env["res.users"].search([
        ("groups_id", "in", internal_grp.id),
    ])
    for user in candidates:
        groups = user.groups_id
        has_neon = (
            user_grp in groups
            or manager_grp in groups
            or crew_grp in groups
            or leader_grp in groups
        )
        if has_neon:
            continue
        user.write({"groups_id": [(4, user_grp.id)]})
        _logger.info(
            "neon_jobs 17.0.1.7.1: added neon_jobs_user explicitly to %s "
            "(internal user with no prior neon tier).",
            user.login,
        )

    # === Step 4: warn on Sales-menu access without a neon tier ===
    sale_menu = env.ref("sale.sale_menu_root", raise_if_not_found=False)
    if sale_menu:
        for user in env["res.users"].search([("share", "=", False)]):
            visible_menus = user.sudo()._get_menus_root() if hasattr(
                user, "_get_menus_root"
            ) else env["ir.ui.menu"].with_user(user).search([
                ("id", "=", sale_menu.id),
            ])
            sees_sale = sale_menu in visible_menus
            has_any_neon = bool(
                set([user_grp.id, manager_grp.id, crew_grp.id, leader_grp.id])
                & set(user.groups_id.ids)
            )
            if sees_sale and not has_any_neon:
                _logger.warning(
                    "neon_jobs 17.0.1.7.1: user %s has Sales-menu access "
                    "but no neon tier group. Verify after upgrade.",
                    user.login,
                )
