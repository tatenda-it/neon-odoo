# -*- coding: utf-8 -*-
"""neon_training 17.0.8.8.0 post-migrate.

Phase 7c M4 cross-module touch: adds external_booking_id
M2O on neon.training.certification pointing at
neon.external.training.booking.

Field is nullable + ondelete=set null. No backfill needed
-- existing certs predate Phase 7c and are unrelated to
external bookings. The Phase 7c M4 workflow populates the
field at cert creation; manual writes are allowed for
admin reconciliation (e.g., back-linking a cert created
before this field shipped).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info(
        "neon_training 17.0.8.8.0: external_booking_id "
        "field added to neon.training.certification for "
        "Phase 7c M4 auto-cert issuance. Field is nullable "
        "(ondelete=set null); no backfill needed.")
