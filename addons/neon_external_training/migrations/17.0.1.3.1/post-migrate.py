# -*- coding: utf-8 -*-
"""neon_external_training 17.0.1.3.0 post-migrate.

When neon_training 17.0.8.8.0 added external_booking_id
to neon.training.certification, the comodel
neon.external.training.booking was NOT yet in the
registry (neon_external_training depends on
neon_training, so neon_training loads FIRST). The result:
the column was created but the SQL-level FK constraint
was not (Odoo silently skips FK creation for unknown
comodel_name forward-string references).

This migration adds the FK constraint explicitly on every
-i / -u of neon_external_training, idempotently. Future
fresh-install order (neon_training -> neon_external_
training, both via -i) lands here and provisions the FK
correctly. Existing installs that upgraded neon_training
alone (e.g., the Phase 7c M4 atomic B1 commit) also get
the FK on the subsequent neon_external_training -u.

Phase 11 amendment candidate filed: a generic
register_forward_fk helper that any sub-phase touching a
cross-module Many2one can call once.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT 1
          FROM pg_constraint
         WHERE conrelid = 'neon_training_certification'::regclass
           AND contype = 'f'
           AND conname =
               'neon_training_certification_external_booking_id_fkey'
    """)
    if cr.fetchone():
        _logger.info(
            "neon_external_training 17.0.1.3.0: FK on "
            "neon.training.certification.external_booking_id "
            "already exists; no-op.")
        return
    cr.execute("""
        ALTER TABLE neon_training_certification
          ADD CONSTRAINT
            neon_training_certification_external_booking_id_fkey
          FOREIGN KEY (external_booking_id)
          REFERENCES neon_external_training_booking(id)
          ON DELETE SET NULL
    """)
    _logger.info(
        "neon_external_training 17.0.1.3.0: added missing "
        "FK constraint "
        "neon_training_certification_external_booking_id_fkey "
        "with ON DELETE SET NULL.")
