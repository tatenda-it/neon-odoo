# -*- coding: utf-8 -*-
"""B11 / PRE-WA-0 -- ai-core extraction data-integrity guard (POST).

Re-asserts the pre-migrate snapshot AFTER neon_dashboard has reloaded
with the models now owned by neon_ai_core. Verifies:
  * row counts unchanged for all 3 moving tables;
  * every snapshotted write.log row still exists with the SAME id +
    status + confirmation_token (per-record identity, not just count).

Any discrepancy raises -> the whole `-i neon_ai_core -u neon_dashboard`
upgrade transaction rolls back (fail-safe). On success, the holding
tables are dropped.
"""
import logging

_logger = logging.getLogger(__name__)

MOVING = {
    "neon_finance_ai_chat_write_log": "write.log",
    "neon_finance_ai_chat_session": "session",
    "neon_finance_ai_chat_message": "message",
}


def migrate(cr, version):
    cr.execute("SELECT to_regclass('neon_ai_core_mig_counts')")
    if cr.fetchone()[0] is None:
        _logger.warning(
            "B11 post-migrate: no baseline table found -- "
            "pre-migrate did not run? Skipping integrity verify.")
        return

    errors = []

    # 1) Row-count preservation.
    cr.execute("SELECT tbl, n FROM neon_ai_core_mig_counts")
    baseline = dict(cr.fetchall())
    for tbl, n_before in baseline.items():
        cr.execute("SELECT count(*) FROM %s" % tbl)
        n_after = cr.fetchone()[0]
        if n_after != n_before:
            errors.append(
                "%s row count %s -> %s" % (tbl, n_before, n_after))
        else:
            _logger.info(
                "B11 post-migrate OK: %s = %s rows (unchanged).",
                tbl, n_after)

    # 2) write.log per-record identity preservation.
    cr.execute("SELECT to_regclass('neon_ai_core_mig_writelog')")
    if cr.fetchone()[0] is not None:
        cr.execute(
            "SELECT s.id FROM neon_ai_core_mig_writelog s "
            "LEFT JOIN neon_finance_ai_chat_write_log w "
            "  ON w.id = s.id "
            " AND w.status = s.status "
            " AND COALESCE(w.confirmation_token, '') "
            "     = COALESCE(s.confirmation_token, '') "
            "WHERE w.id IS NULL"
        )
        drift = [r[0] for r in cr.fetchall()]
        if drift:
            errors.append(
                "write.log per-record identity drift on ids %s" % drift)
        else:
            cr.execute("SELECT count(*) FROM neon_ai_core_mig_writelog")
            _logger.info(
                "B11 post-migrate OK: write.log per-record identity "
                "preserved (%s rows, id+status+token intact).",
                cr.fetchone()[0])

    if errors:
        raise Exception(
            "B11 ai-core extraction INTEGRITY FAILURE -- aborting "
            "upgrade (transaction rolls back): " + " | ".join(errors))

    # Success -- clean up holding tables.
    cr.execute("DROP TABLE IF EXISTS neon_ai_core_mig_counts")
    cr.execute("DROP TABLE IF EXISTS neon_ai_core_mig_writelog")
    _logger.info(
        "B11 post-migrate: all moving-model integrity checks PASSED; "
        "holding tables dropped.")
