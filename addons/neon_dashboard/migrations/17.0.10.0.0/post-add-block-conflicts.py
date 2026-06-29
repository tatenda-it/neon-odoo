# -*- coding: utf-8 -*-
"""P-B2 migration -- add block_conflicts widget to existing layouts.

The default_layouts.xml record is loaded with noupdate=1 to preserve
user customisations on -u. That same noupdate flag means my edit
adding `block_conflicts` to the lead_tech seed does NOT propagate
automatically. This migration:

1. Inserts a `block_conflicts` line into the lead_tech default seed
   (so future first-time lead_tech users get the panel).
2. Inserts a `block_conflicts` user_layout row into every EXISTING
   lead_tech user's layout (so existing lead-tech / director users see
   the panel without manual Edit-Layout interaction).

Both inserts are idempotent: if the row already exists, skip.
"""
import logging


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Fresh install -- nothing to migrate.
        return

    # --- 1. Seed-layout line for lead_tech default ---
    cr.execute("""
        SELECT dl.id
        FROM neon_dashboard_default_layout dl
        WHERE dl.dashboard_type = 'lead_tech'
        LIMIT 1
    """)
    seed = cr.fetchone()
    if seed:
        seed_id = seed[0]
        cr.execute("""
            SELECT 1 FROM neon_dashboard_default_layout_line
            WHERE default_layout_id = %s AND widget_key = 'block_conflicts'
            LIMIT 1
        """, (seed_id,))
        if not cr.fetchone():
            cr.execute("""
                INSERT INTO neon_dashboard_default_layout_line
                    (default_layout_id, widget_key, visible,
                     order_index, size)
                VALUES (%s, 'block_conflicts', TRUE, 14, 'large')
            """, (seed_id,))
            _logger.info(
                "P-B2 migration: added block_conflicts to lead_tech "
                "default_layout seed (id=%s)", seed_id)

    # --- 2. Per-user layout backfill for existing lead_tech users ---
    cr.execute("""
        SELECT d.id AS dashboard_id
        FROM neon_dashboard d
        WHERE d.dashboard_type = 'lead_tech'
          AND NOT EXISTS (
            SELECT 1 FROM neon_dashboard_user_layout ul
            WHERE ul.dashboard_id = d.id
              AND ul.widget_key = 'block_conflicts'
          )
    """)
    targets = [row[0] for row in cr.fetchall()]
    for dashboard_id in targets:
        cr.execute("""
            INSERT INTO neon_dashboard_user_layout
                (dashboard_id, widget_key, visible,
                 order_index, size, create_uid, create_date,
                 write_uid, write_date)
            VALUES (%s, 'block_conflicts', TRUE, 14, 'large',
                    1, NOW(), 1, NOW())
        """, (dashboard_id,))
    if targets:
        _logger.info(
            "P-B2 migration: added block_conflicts to %d existing "
            "lead_tech user_layouts (dashboard_ids=%s).",
            len(targets), targets[:8])
