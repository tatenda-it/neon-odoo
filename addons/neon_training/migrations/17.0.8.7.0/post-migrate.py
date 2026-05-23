# -*- coding: utf-8 -*-
"""Phase 7e M11 cross-module extension: 4 LMS counters on
neon.training.dashboard + drill-through actions.

Schema changes: 0 (all 4 fields are non-stored computes).

Log-only migration.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info(
        "neon_training 17.0.8.7.0: 4 LMS counters added to "
        "dashboard ('LMS Progression' card group). "
        "Defensive env.get pattern -- counters return 0 / "
        "empty string when neon_lms is not installed. "
        "Drill-through actions return False for inert "
        "buttons in that case.")
