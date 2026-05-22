# -*- coding: utf-8 -*-
"""Phase 7a dashboard extension for Phase 7b M11. Adds 2
onboarding counters (candidates_in_cert_collection +
candidates_in_probationary) with defensive env.get lookup
for neon.onboarding.candidate.

No schema changes -- both fields are non-stored computes.
Migration is log-only for deploy correlation.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info(
        "neon_training 17.0.8.3.0: 2 onboarding counters "
        "added to dashboard form view ("
        "candidates_in_cert_collection + "
        "candidates_in_probationary). Defensive env.get "
        "lookup means counters return 0 if neon_onboarding "
        "is not installed -- no install-order requirement. "
        "Drill-through actions return False (inert button) "
        "in that case.")
