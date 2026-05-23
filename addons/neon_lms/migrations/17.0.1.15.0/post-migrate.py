# -*- coding: utf-8 -*-
"""neon_lms 17.0.1.15.0 post-migrate.

Phase 7d M5 cross-module touch: adds kb_article_ids M2M
reverse pointer on neon.lms.sop pointing at
neon.kb.article via the shared join table
neon_kb_article_sop_rel.

The join table itself is created by the neon_kb side
(neon_kb owns the forward M2M definition; neon_lms
mirrors via the same relation name + swapped column
names). Log-only migration; no schema changes here.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info(
        "neon_lms 17.0.1.15.0: kb_article_ids M2M added "
        "to neon.lms.sop for Phase 7d M5 cross-link. Join "
        "table neon_kb_article_sop_rel is created by the "
        "neon_kb side; no schema change here.")
