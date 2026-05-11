# -*- coding: utf-8 -*-
"""
Migration to 17.0.1.2.0 — re-apply crm.stage flag updates.

The XML data file crm_stage_data.xml uses <function> calls. When the
module first lands on a DB at this version, those calls fire during the
initial XML load. But on plain -u upgrades from 17.0.1.1.x — where the
data file was registered as noupdate=1 on its first pass — the function
calls are skipped. This post-migrate runs once, idempotently, to make
sure both flags are set.

Idempotent: re-running on a DB where the flags are already True is a no-op.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def _tick(env, field, primary_name, fallback_sequence):
    Stage = env["crm.stage"]
    stage = Stage.search([("name", "=", primary_name)], limit=1)
    matched_via = "name"
    if not stage:
        stage = Stage.search([("sequence", "=", fallback_sequence)], limit=1)
        matched_via = "sequence"
    if not stage:
        _logger.warning(
            "neon_jobs 17.0.1.2.0 migrate: no crm.stage found for %s "
            "(name=%r, sequence=%s). Skipping.",
            field, primary_name, fallback_sequence,
        )
        return
    if stage[field]:
        _logger.info(
            "neon_jobs 17.0.1.2.0 migrate: %s already True on crm.stage "
            "%r (id=%s); no-op.",
            field, stage.name, stage.id,
        )
        return
    stage.write({field: True})
    _logger.info(
        "neon_jobs 17.0.1.2.0 migrate: set %s=True on crm.stage %r "
        "(id=%s, matched via %s).",
        field, stage.name, stage.id, matched_via,
    )


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    _tick(env, "is_proposal_stage", "Quote Sent", 4)
    _tick(env, "is_confirmation_stage", "Confirmed", 7)
