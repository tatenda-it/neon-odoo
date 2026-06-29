# -*- coding: utf-8 -*-
"""17.0.1.5.0 — re-apply Rail v0 on upgrade (screen #5: CRM Pipeline).

post_init_hook only fires on a fresh install. On -u of an already-installed
neon_screens, the Rail v0 slot for screen #5 — CRM Pipeline claims slot 2 and
the raw CRM app (crm.crm_menu_root) demotes to its 40s home — must be applied
here. Runs AFTER the module's data files load, so menu_crm_pipeline_root already
exists. Idempotent (writes sequence/name only). NO crm.stage change."""
from odoo import SUPERUSER_ID, api
from odoo.addons.neon_screens.hooks import _apply_rail_v0


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _apply_rail_v0(env)
