# -*- coding: utf-8 -*-
"""neon_kb 17.0.1.4.0 post-migrate.

Phase 7d M5 ensures the 3 M2M join tables exist with the
right FK constraints. Same idempotent pattern as Phase 7c
M4 applied to M2M (reference_odoo17_forward_string_m2o_fk
.md).

Tables:
  neon_kb_article_cert_type_rel
    (article_id, cert_type_id)
    FKs: article_id -> neon_kb_article(id) ON DELETE CASCADE
         cert_type_id -> neon_training_certification_type(id)
                         ON DELETE CASCADE
  neon_kb_article_sop_rel
    (article_id, sop_id)
    FKs: article_id -> neon_kb_article(id) ON DELETE CASCADE
         sop_id -> neon_lms_sop(id) ON DELETE CASCADE
  neon_kb_article_module_rel
    (article_id, module_id)
    FKs: article_id -> neon_kb_article(id) ON DELETE CASCADE
         module_id -> neon_lms_module(id) ON DELETE CASCADE

Odoo normally creates these automatically at table-init
time, but the forward-string reference pattern (kb depends
on lms + training; the table-init pass during the standalone
'install neon_kb' phase may not yet have those comodels in
the registry depending on install ordering). This migration
fills any gap idempotently.

Phase 11 candidate: generic register_m2m_join helper
covering all 3 in one call.
"""
import logging

_logger = logging.getLogger(__name__)


_TABLES = [
    (
        "neon_kb_article_cert_type_rel",
        "article_id", "cert_type_id",
        "neon_kb_article", "neon_training_certification_type",
    ),
    (
        "neon_kb_article_sop_rel",
        "article_id", "sop_id",
        "neon_kb_article", "neon_lms_sop",
    ),
    (
        "neon_kb_article_module_rel",
        "article_id", "module_id",
        "neon_kb_article", "neon_lms_module",
    ),
]


def _table_exists(cr, table):
    cr.execute("""
        SELECT 1 FROM information_schema.tables
         WHERE table_name = %s
    """, [table])
    return bool(cr.fetchone())


def _has_fk(cr, table, fk_name):
    cr.execute("""
        SELECT 1 FROM pg_constraint
         WHERE conname = %s
    """, [fk_name])
    return bool(cr.fetchone())


def migrate(cr, version):
    for (tbl, col_a, col_b,
         ref_a_tbl, ref_b_tbl) in _TABLES:
        if not _table_exists(cr, tbl):
            cr.execute("""
                CREATE TABLE "%s" (
                    "%s" INTEGER NOT NULL,
                    "%s" INTEGER NOT NULL,
                    PRIMARY KEY ("%s", "%s")
                )
            """ % (tbl, col_a, col_b, col_a, col_b))
            _logger.info(
                "neon_kb 17.0.1.4.0: created M2M join "
                "table %s.", tbl)
        # FK on column A
        fk_a = "%s_%s_fkey" % (tbl, col_a)
        if not _has_fk(cr, tbl, fk_a):
            cr.execute("""
                ALTER TABLE "%s"
                  ADD CONSTRAINT "%s"
                  FOREIGN KEY ("%s")
                  REFERENCES "%s"(id)
                  ON DELETE CASCADE
            """ % (tbl, fk_a, col_a, ref_a_tbl))
            _logger.info(
                "neon_kb 17.0.1.4.0: added FK %s.", fk_a)
        # FK on column B
        fk_b = "%s_%s_fkey" % (tbl, col_b)
        if not _has_fk(cr, tbl, fk_b):
            cr.execute("""
                ALTER TABLE "%s"
                  ADD CONSTRAINT "%s"
                  FOREIGN KEY ("%s")
                  REFERENCES "%s"(id)
                  ON DELETE CASCADE
            """ % (tbl, fk_b, col_b, ref_b_tbl))
            _logger.info(
                "neon_kb 17.0.1.4.0: added FK %s.", fk_b)
