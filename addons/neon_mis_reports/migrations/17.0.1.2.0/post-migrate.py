# -*- coding: utf-8 -*-
"""On upgrade to 17.0.1.2.0: apply the per-currency report variants (the
post_init_hook only runs on a fresh -i). Idempotent -- sets the USD target +
renames the three base instances and ensures their ZWG siblings exist."""
from odoo import SUPERUSER_ID, api
from odoo.addons.neon_mis_reports import _apply_currency_variants


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _apply_currency_variants(env)
