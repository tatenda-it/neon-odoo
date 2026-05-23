# -*- coding: utf-8 -*-
"""neon_training 17.0.8.9.0 post-migrate.

Phase 7c M6 cross-module touch: 2 external-training
counters + drill-through actions added to the training
compliance dashboard. Pure compute on TransientModel; no
schema changes. Log-only migration -- no DB fixup needed.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info(
        "neon_training 17.0.8.9.0: 2 external-training "
        "counters (upcoming 30d / pending completion 7d) "
        "+ drill-through actions added to "
        "neon.training.dashboard. Defensive env.get "
        "pattern; no DB schema changes.")
