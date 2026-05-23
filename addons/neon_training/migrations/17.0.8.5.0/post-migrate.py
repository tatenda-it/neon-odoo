# -*- coding: utf-8 -*-
"""Phase 7e M9 cross-module extension: 8 LMS-issued cert
types + 'system' sign_off_authority enum value.

Schema changes:
* No column changes -- 8 new cert type records seeded via
  neon_training_data.xml (noupdate=1, append-only).
* sign_off_authority Selection gains 'system' value
  (Python-level enum extension via _SIGN_OFF_AUTHORITIES
  in models/neon_training_certification_type.py).

Log-only migration. The 8 new cert types are referenced by
Phase 7e neon.lms.track.sub_cert_type_id + neon program
channel's neon_capstone_cert_type_id (M9 also updates those
LMS data files).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT name FROM neon_training_certification_type
        WHERE code IN (
            'neon_foundations_safety', 'neon_audio',
            'neon_lighting', 'neon_video_led',
            'neon_workflow_ops', 'neon_client_ready',
            'neon_rigging', 'neon_technical'
        )
    """)
    rows = cr.fetchall()
    _logger.info(
        "neon_training 17.0.8.5.0: 8 LMS cert types now in "
        "registry (M9 Phase 7e seed extension): %s. The "
        "'system' sign_off_authority enum value added to "
        "_SIGN_OFF_AUTHORITIES list -- M7 cert routing "
        "(_resolve_verify_authority_partners) returns empty "
        "for system-issued certs (no human verifier; LMS "
        "auto-issues via sudo).",
        [r[0] for r in rows])
