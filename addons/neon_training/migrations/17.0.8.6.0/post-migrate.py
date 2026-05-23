# -*- coding: utf-8 -*-
"""Phase 7e M10 cross-module extension: gate engine 5th
condition (operating authority).

Schema changes:
* commercial_event_job_required_authority_rel M2M table
  (event_job to neon.lms.operating.authority). Created by
  Odoo's stock M2M auto-init.
* Two new methods in commercial.job.crew:
  - _m10_operating_authority_violations
  - _m10_create_authority_gate_logs
* Two new wiring lines in commercial.job.crew create + write
  hooks.

Defensive against Phase 7e not installed: env.get on
neon.lms.operating.authority + slide.channel.partner; no-op
when either is None.

Log-only migration.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info(
        "neon_training 17.0.8.6.0: gate engine 5th condition "
        "(operating authority) wired into commercial.job.crew "
        "create + write hooks. required_authority_ids M2M "
        "on commercial.event.job. fire_reason format: "
        "'operating_authority_missing:<authority_code>'.")
