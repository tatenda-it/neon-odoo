# -*- coding: utf-8 -*-
"""Phase 7b M4 cross-module touch: candidate_id Many2one
added to neon.training.certification.

The field is nullable + ondelete=set null + no default, so
Odoo's stock column-add path handles the schema change.
No backfill needed -- existing certs stay candidate_id=NULL
until a candidate is explicitly linked.

Migration body is informational only; the actual column
add is performed by Odoo's ORM during module load.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        "SELECT COUNT(*) FROM neon_training_certification")
    count = cr.fetchone()[0]
    _logger.info(
        "neon_training 17.0.8.1.0: candidate_id Many2one "
        "added to neon.training.certification for Phase 7b "
        "M4 onboarding integration. Field is nullable "
        "(ondelete=set null); no backfill required. Existing "
        "%d cert records remain candidate_id=NULL until "
        "linked explicitly.", count)
