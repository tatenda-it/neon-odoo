# -*- coding: utf-8 -*-
"""
Migration to 17.0.3.5.0 — P4.M7 final trigger integration.

The trigger_config_scope_change data record is loaded with
noupdate="1", so updating its primary_role in the XML does not
propagate to existing installs. P4.M7 changes the role from
'sales' to 'lead_tech' per Robin's Q6 + the M5+M6 browser smoke
findings: the on-site Lead Tech reviews the scope change first;
Sales picks it up later from the review queue.

This migration only writes the new value when the existing row
still has the old default ('sales'), so a director who has
deliberately re-tuned the role (e.g. to 'manager') keeps their
customisation.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cfg = env.ref(
        "neon_jobs.trigger_config_scope_change",
        raise_if_not_found=False,
    )
    if not cfg:
        return
    if cfg.primary_role == "sales":
        cfg.primary_role = "lead_tech"
        _logger.info(
            "neon_jobs 17.0.3.5.0: trigger_config_scope_change "
            "primary_role 'sales' → 'lead_tech'."
        )
    else:
        _logger.info(
            "neon_jobs 17.0.3.5.0: trigger_config_scope_change "
            "primary_role is %r (already customised); leaving it.",
            cfg.primary_role,
        )
