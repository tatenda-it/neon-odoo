# -*- coding: utf-8 -*-
"""Phase 7a extension for Phase 7b M12. Wires the
candidate._notify_cert_verified hook into the existing M4
_check_candidate_state_advancement constrains + the M5
_m5_create_probationary_gate_log hook now fires
candidate._notify_probationary_gate_block.

Both hooks use hasattr() guards so this upgrade is safe
even when neon_onboarding is at an older version (no
notify methods yet) -- the call short-circuits to no-op.

No schema changes. Log-only migration.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info(
        "neon_training 17.0.8.4.0: M12 notification hooks "
        "wired into cert verification (M4 constrains) + "
        "probationary gate block (M5 helper). hasattr() "
        "guards ensure no-op when neon_onboarding < "
        "17.0.1.10.0 or absent. Phase 9 overrides these "
        "stubs for actual WhatsApp + email dispatch.")
