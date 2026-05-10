# -*- coding: utf-8 -*-
"""
Migration to 17.0.1.1.0 — wire base.group_user → group_neon_jobs_user.

The XML loader cannot update base.group_user because its
ir_model_data row carries noupdate=true from the base module.
Apply the implication imperatively so every internal user
gains Operations access on upgrade.
"""


def migrate(cr, version):
    if not version:
        return
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    env.ref("base.group_user").write({
        "implied_ids": [(4, env.ref("neon_jobs.group_neon_jobs_user").id)],
    })
