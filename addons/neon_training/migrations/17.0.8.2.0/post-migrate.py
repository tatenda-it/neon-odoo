# -*- coding: utf-8 -*-
"""Phase 7a extension for Phase 7b M5 -- adds fire_reason Char
to neon.training.assignment_gate_log + the M5 probationary
hook in commercial.job.crew.

Schema changes:
* assignment_gate_log.fire_reason: nullable Char column
  added by Odoo's stock column-add path. Existing M9 / M10 /
  M11 fire entries remain fire_reason=NULL (correct semantics
  -- they pre-date the discriminator).

No data backfill needed. Log-only migration.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        "SELECT COUNT(*) FROM neon_training_assignment_gate_log")
    count = cr.fetchone()[0]
    _logger.info(
        "neon_training 17.0.8.2.0: fire_reason Char added to "
        "neon.training.assignment_gate_log. %d existing gate "
        "log entries retain fire_reason=NULL (M9/M10/M11 "
        "fires pre-date the M5 discriminator). Probationary "
        "hook in commercial.job.crew create/write fires on "
        "candidate.state='probationary' AND crew.role != "
        "'runner'. neon_onboarding model lookup is "
        "defensive (env.get) so this upgrade is safe whether "
        "neon_onboarding is installed or not.", count)
