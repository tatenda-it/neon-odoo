# -*- coding: utf-8 -*-
"""Neon Core -- RBAC meta-groups + post-init user assignment."""
import logging

_logger = logging.getLogger(__name__)


# Login-based tier assignment. Canonical users are mapped by
# login (not by base.user_admin xmlid which on prod resolves
# to a system superuser, not Robin). New tier members added
# post-install via Settings -> Users multi-select OR by
# extending this dict in a follow-up patch.
_TIER_ASSIGNMENTS = {
    "neon_core.group_neon_superuser": [
        "robin@neonhiring.co.zw",
        "munashe@neonhiring.co.zw",
        "tatenda@neonhiring.co.zw",
    ],
    "neon_core.group_neon_bookkeeper": [
        "admin@neonhiring.co.zw",  # Kudzaiishe
    ],
    "neon_core.group_neon_sales_rep": [
        "lisar@neonhiring.co.zw",
        "evrill@neonhiring.co.zw",
    ],
    "neon_core.group_neon_lead_tech": [
        # Lead Tech is a PERMANENT role but currently VACANT (no person
        # assigned). The previous holder was offboarded (user deactivated,
        # history preserved). When the role is filled, add the new hire's
        # login here -- nothing else changes (lead_tech_id default + dashboard
        # tier + finance cost-line rule all resolve via the group).
    ],
    # Crew assignments handled at user creation time (Phase 7b
    # onboarding). Too many to enumerate and crew users may
    # not exist yet at install time.
}


# Implied_ids that leaked onto base.group_user via Phase 1-2
# manual UI config -- they grant developer mode + template
# editing + pricing visibility to every internal user, which
# is wrong. Superuser meta-group re-adds them for tier 1 only.
_BASE_USER_LEAKS_TO_STRIP = [
    ("base.group_no_one", "Developer mode"),
    ("base.group_multi_currency", "Multi-currency picker"),
    ("product.group_product_pricelist",
     "Pricelist visibility"),
    ("mail.group_mail_template_editor",
     "Mail template editor"),
]


def _strip_base_user_leaks(env):
    """Remove the 4 unwanted implied_ids from base.group_user.
    Idempotent -- (3, id) defensive-remove is a no-op if the
    target is already absent.
    """
    base_user = env.ref(
        "base.group_user", raise_if_not_found=False)
    if not base_user:
        _logger.error(
            "neon_core: base.group_user not found; "
            "skipping cleanup.")
        return
    removed = []
    skipped = []
    for xmlid, label in _BASE_USER_LEAKS_TO_STRIP:
        target = env.ref(xmlid, raise_if_not_found=False)
        if not target:
            skipped.append(f"{xmlid} (not in registry)")
            continue
        if target not in base_user.implied_ids:
            skipped.append(
                f"{xmlid} ({label}: already absent)")
            continue
        base_user.sudo().write({
            "implied_ids": [(3, target.id)],
        })
        removed.append(f"{xmlid} ({label})")
        _logger.info(
            "neon_core: stripped implied_id %s (%s) from "
            "base.group_user.", xmlid, label)
    _logger.info(
        "neon_core cleanup summary -- removed=%d, skipped=%d. "
        "Removed: %s. Skipped: %s.",
        len(removed), len(skipped),
        ", ".join(removed) or "(none)",
        ", ".join(skipped) or "(none)")


def _assign_tier_users(env):
    """Assign canonical users to their meta-group by login
    lookup. Skips silently when a target user doesn't exist
    yet (e.g. a tier with no current person, like a vacant role).
    Logs each grant action.

    Reference: reference_odoo17_implied_ids_orm_vs_sql.md --
    raw SQL bypasses propagation; ORM write is mandatory for
    res.groups.users.
    """
    for group_xmlid, logins in _TIER_ASSIGNMENTS.items():
        group = env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            _logger.warning(
                "neon_core: meta-group %s not found in "
                "registry; skipping assignments.", group_xmlid)
            continue
        for login in logins:
            user = env["res.users"].search([
                ("login", "=", login),
                ("active", "=", True),
            ], limit=1)
            if not user:
                _logger.info(
                    "neon_core: user %s not present in this "
                    "DB; skipping assignment to %s.",
                    login, group_xmlid)
                continue
            if user in group.users:
                _logger.info(
                    "neon_core: %s already in %s; no-op.",
                    login, group_xmlid)
                continue
            group.sudo().write({"users": [(4, user.id)]})
            _logger.info(
                "neon_core: assigned %s to %s (implied chain "
                "propagated via ORM write).",
                login, group_xmlid)


def _reconcile_user_groups(env):
    """Strip the 4 unwanted groups from tier users whose
    meta-group does NOT legitimately imply them.

    Why this is needed even after _strip_base_user_leaks:
    Odoo's M2M res_groups_users_rel materialises each
    implication when a user is added to a group. Subsequently
    removing the implication from the source group does NOT
    cascade-remove existing rel rows. So pre-existing users
    who got the 4 groups via base.group_user keep them.

    Safety: only touches users who are in a Neon meta-group
    AND whose meta-group's trans_implied_ids does NOT include
    the unwanted group. System users (uid=1), test fixtures
    (p2m75_*), and users not in any Neon meta-group are left
    untouched.
    """
    meta_group_xmlids = list(_TIER_ASSIGNMENTS.keys()) + [
        "neon_core.group_neon_crew",
    ]
    meta_groups = []
    for xid in meta_group_xmlids:
        g = env.ref(xid, raise_if_not_found=False)
        if g:
            meta_groups.append(g)

    for unwanted_xid, label in _BASE_USER_LEAKS_TO_STRIP:
        unwanted_grp = env.ref(
            unwanted_xid, raise_if_not_found=False)
        if not unwanted_grp:
            continue
        stripped_count = 0
        for user in unwanted_grp.users:
            # Find user's Neon meta-group (if any).
            user_meta = None
            for mg in meta_groups:
                if user in mg.users:
                    user_meta = mg
                    break
            if not user_meta:
                continue  # Not in any Neon tier, leave alone.
            if unwanted_grp in user_meta.trans_implied_ids:
                continue  # Legitimately implied by tier.
            unwanted_grp.sudo().write({
                "users": [(3, user.id)],
            })
            stripped_count += 1
            _logger.info(
                "neon_core reconcile: removed %s (%s) from "
                "%s (tier=%s; not legitimately implied).",
                unwanted_xid, label, user.login,
                user_meta.name)
        if stripped_count:
            _logger.info(
                "neon_core reconcile: stripped %s from %d "
                "tier user(s).", unwanted_xid, stripped_count)


def _post_init_hook(env):
    """Fired on fresh -i. Three-step canonical RBAC state:
    (1) Strip the 4 leaked implied_ids from base.group_user
        registry so future user-creation cascades clean.
    (2) Assign canonical users to their meta-group; cascade
        adds the legitimate implied chain per tier.
    (3) Reconcile: strip the 4 unwanted groups from existing
        tier users whose meta-group doesn't legitimately imply
        them (because step 1 doesn't cascade-remove existing
        M2M rel rows).
    Migration script (migrations/17.0.1.0.0/post-migrate.py)
    mirrors this for the -u upgrade path.
    """
    _strip_base_user_leaks(env)
    _assign_tier_users(env)
    _reconcile_user_groups(env)
