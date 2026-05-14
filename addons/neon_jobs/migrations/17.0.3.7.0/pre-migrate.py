# -*- coding: utf-8 -*-
"""
Migration to 17.0.3.7.0 — P5.M1 sub-task A — Q18 crew model.

commercial.job.crew now carries a required partner_id and an
optional user_id. Before the ORM upgrade processes the new
_sql_constraints, we need to:

  1. Add the partner_id column (if not already present) so the
     backfill SQL has somewhere to write.
  2. Backfill partner_id from user_id.partner_id on every existing
     row, so the new UNIQUE (job_id, partner_id) constraint can
     be applied without NULL-or-duplicate surprises.
  3. Drop the old UNIQUE (job_id, user_id) constraint. The ORM
     will track that the constraint key changed from
     "unique_user_per_job" to "unique_partner_per_job"; doing the
     drop here pre-emptively avoids any case where the ORM
     reconciler trips on the column being not-yet-NULL-populated.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # 1) Add partner_id column nullable. ORM will tighten metadata
    #    in step 2 (module load); we just need the column to exist
    #    so backfill can target it.
    cr.execute("""
        ALTER TABLE commercial_job_crew
        ADD COLUMN IF NOT EXISTS partner_id INTEGER
    """)

    # 2) Backfill from user_id.partner_id. Skip rows already
    #    populated (re-runs are no-ops).
    cr.execute("""
        UPDATE commercial_job_crew cjc
        SET partner_id = u.partner_id
        FROM res_users u
        WHERE cjc.user_id = u.id
        AND cjc.partner_id IS NULL
        AND u.partner_id IS NOT NULL
    """)
    backfilled = cr.rowcount
    _logger.info(
        "17.0.3.7.0 pre-migrate: backfilled partner_id on %d "
        "commercial.job.crew rows.", backfilled,
    )

    # 3) Drop the old UNIQUE constraint. The new one is created by
    #    the ORM later in this upgrade run, after the column is
    #    populated.
    cr.execute("""
        ALTER TABLE commercial_job_crew
        DROP CONSTRAINT IF EXISTS commercial_job_crew_unique_user_per_job
    """)
    _logger.info(
        "17.0.3.7.0 pre-migrate: dropped legacy "
        "commercial_job_crew_unique_user_per_job constraint."
    )

    # 4) Sanity check — surface any rows that couldn't be backfilled.
    #    These would be crew records whose user_id either points at a
    #    deleted user or a user without a partner_id, which
    #    shouldn't happen in practice. We leave them with NULL
    #    partner_id (the post-migrate verifies and reports); the
    #    module's required=True will be enforced at the ORM layer
    #    going forward.
    cr.execute("""
        SELECT COUNT(*) FROM commercial_job_crew WHERE partner_id IS NULL
    """)
    remaining = cr.fetchone()[0]
    if remaining:
        _logger.warning(
            "17.0.3.7.0 pre-migrate: %d commercial.job.crew rows "
            "still have NULL partner_id after backfill — investigate "
            "via the post-migrate report.", remaining,
        )
