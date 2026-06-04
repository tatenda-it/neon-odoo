# -*- coding: utf-8 -*-
"""B11 / PRE-WA-0 -- ai-core extraction data-integrity guard (PRE).

The chat audit + two-phase write models (neon.finance.ai.chat.session /
.message / .write.log) change definition-ownership from neon_dashboard
to neon_ai_core in this upgrade. Model _name is preserved, so the
underlying tables are NOT renamed/copied/dropped and rows survive
automatically -- but per LOCKED DECISION 4/5 we snapshot row counts AND
the write.log per-record identity here, then re-assert in post-migrate.
Any drift aborts the upgrade transaction (self-rollback).

Runs on -u neon_dashboard (17.0.11.0.0 -> 17.0.11.1.0). In the combined
`-i neon_ai_core -u neon_dashboard` command neon_ai_core installs first
(dependency order), so by the time this runs the models are already
core-owned and the tables are intact -- exactly the state we snapshot.
"""
import logging

_logger = logging.getLogger(__name__)

# table -> human label. Fixed dict (NOT user input) -- safe to format
# into SQL identifiers below.
MOVING = {
    "neon_finance_ai_chat_write_log": "write.log",
    "neon_finance_ai_chat_session": "session",
    "neon_finance_ai_chat_message": "message",
}


def migrate(cr, version):
    cr.execute(
        "CREATE TABLE IF NOT EXISTS neon_ai_core_mig_counts "
        "(tbl text PRIMARY KEY, n bigint)"
    )
    cr.execute("DELETE FROM neon_ai_core_mig_counts")
    for tbl in MOVING:
        cr.execute("SELECT to_regclass(%s)", (tbl,))
        if cr.fetchone()[0] is None:
            _logger.warning(
                "B11 pre-migrate: table %s absent -- skipping baseline.",
                tbl)
            continue
        cr.execute("SELECT count(*) FROM %s" % tbl)
        n = cr.fetchone()[0]
        cr.execute(
            "INSERT INTO neon_ai_core_mig_counts(tbl, n) VALUES (%s, %s)",
            (tbl, n))
        _logger.info("B11 pre-migrate baseline: %s = %s rows", tbl, n)

    # Per-record write.log identity snapshot (counts alone are too weak
    # at low row numbers -- LOCKED DECISION per-record check).
    cr.execute("DROP TABLE IF EXISTS neon_ai_core_mig_writelog")
    cr.execute("SELECT to_regclass('neon_finance_ai_chat_write_log')")
    if cr.fetchone()[0] is not None:
        cr.execute(
            "CREATE TABLE neon_ai_core_mig_writelog AS "
            "SELECT id, create_date, status, confirmation_token "
            "FROM neon_finance_ai_chat_write_log"
        )
        cr.execute("SELECT count(*) FROM neon_ai_core_mig_writelog")
        _logger.info(
            "B11 pre-migrate: captured %s write.log identity rows.",
            cr.fetchone()[0])
