# -*- coding: utf-8 -*-
"""neon_training 17.0.8.10.0 post-migrate.

Phase 7d M6 cross-module touch: 2 KB counters
(kb_articles_published / kb_articles_recent_30d) +
drill-through actions added to the training compliance
dashboard. Pure compute on TransientModel; no schema
changes. Log-only migration.

5th cross-module extension of this dashboard model
(LMS / Onboarding / External Training / KB all share
the defensive env.get pattern).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info(
        "neon_training 17.0.8.10.0: 2 KB counters "
        "(published + new_30d) + drill-through actions "
        "added to neon.training.dashboard. Defensive "
        "env.get pattern; no DB schema changes.")
