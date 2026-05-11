# -*- coding: utf-8 -*-
"""
Migration to 17.0.1.7.1 — pre-migrate: portal crew test users.

P2.M7 created some crew test users on base.group_portal for security
isolation testing. P2.M7.6 D3 reclassifies all crew users as
internal-tier (base.group_user + neon_jobs_crew) — the realistic
production shape, and avoids portal-vs-backend routing confusion
in browser smoke.

This pre-migrate runs before the security XML reload so the user
group memberships are updated cleanly. The post-migrate then strips
the auto-implication leak.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

_PORTAL_CREW_LOGINS = (
    "p2m7_crew_only",
    "p2m7_fresh",
    "p2m75_crew",
    "p2m75_other",
    "p2m75_t20",
)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    portal_grp = env.ref("base.group_portal", raise_if_not_found=False)
    internal_grp = env.ref("base.group_user", raise_if_not_found=False)
    if not (portal_grp and internal_grp):
        _logger.warning(
            "neon_jobs 17.0.1.7.1 pre-migrate: base groups missing; skipping."
        )
        return
    users = env["res.users"].search([("login", "in", list(_PORTAL_CREW_LOGINS))])
    for user in users:
        if portal_grp not in user.groups_id:
            continue
        user.write({
            "groups_id": [(3, portal_grp.id), (4, internal_grp.id)],
        })
        _logger.info(
            "neon_jobs 17.0.1.7.1 pre-migrate: %s — portal removed, "
            "internal added (crew group preserved).",
            user.login,
        )
