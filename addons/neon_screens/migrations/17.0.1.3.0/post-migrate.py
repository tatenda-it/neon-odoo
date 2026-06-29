# -*- coding: utf-8 -*-
"""17.0.1.3.0 — re-apply Rail v0 on upgrade (screen #3: Event Jobs).

post_init_hook only fires on a fresh install. On -u of an already-installed
neon_screens, the Rail v0 slot for screen #3 — Event Jobs claims slot 4 — must
be applied here. Runs AFTER the module's data files load, so
menu_event_jobs_root already exists. Idempotent (writes sequence/name only)."""
from odoo import SUPERUSER_ID, api
from odoo.addons.neon_screens.hooks import _apply_rail_v0


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _apply_rail_v0(env)
