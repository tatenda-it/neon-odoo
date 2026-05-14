# -*- coding: utf-8 -*-
"""
Migration to 17.0.3.7.0 — P5.M1 sub-task A — Q18 crew model.

Post-migrate verification + final cleanup. The pre-migrate script
did the heavy lifting (column add, backfill, old-constraint drop);
this step just verifies the result and reports anomalies.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Crew = env["commercial.job.crew"].sudo()

    total = Crew.search_count([])
    null_partner = Crew.search_count([("partner_id", "=", False)])

    if null_partner:
        # Don't fail the upgrade — these rows would have been
        # untouchable by the new ORM contract anyway. Log loudly so
        # operators see them in the upgrade output.
        _logger.warning(
            "17.0.3.7.0 post-migrate: %d / %d commercial.job.crew "
            "rows have NULL partner_id and could not be backfilled. "
            "Inspect manually — they likely have a user_id pointing "
            "at a user with no partner_id, or a stale user_id.",
            null_partner, total,
        )
    else:
        _logger.info(
            "17.0.3.7.0 post-migrate: all %d commercial.job.crew "
            "rows have partner_id populated.", total,
        )

    # Verify no Crew Chief rows have NULL user_id — the new constraint
    # in code rejects this, but existing rows may slip through if a
    # Crew Chief flag was set before user_id was ever required to be
    # a registered user. Surface them as warnings; don't auto-clear.
    chiefless_user = Crew.search([
        ("is_crew_chief", "=", True),
        ("user_id", "=", False),
    ])
    if chiefless_user:
        _logger.warning(
            "17.0.3.7.0 post-migrate: %d Crew Chief rows have NULL "
            "user_id (P5.M1 requires user_id for Crew Chief). "
            "Records: %s. Reassign manually or create user accounts.",
            len(chiefless_user), chiefless_user.ids,
        )
