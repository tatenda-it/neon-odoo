# -*- coding: utf-8 -*-
"""17.0.1.4.0 — re-apply Rail v0 on upgrade (screen #4: Finance Control).

post_init_hook only fires on a fresh install. On -u of an already-installed
neon_screens, the Rail v0 slot for screen #4 — Finance Control claims slot 7
and the raw Accounting app (account.menu_finance) demotes to its 40s home —
must be applied here. Runs AFTER the module's data files load, so
menu_finance_control_root already exists. Idempotent (writes sequence/name)."""
from odoo import SUPERUSER_ID, api
from odoo.addons.neon_screens.hooks import _apply_rail_v0


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _apply_rail_v0(env)
