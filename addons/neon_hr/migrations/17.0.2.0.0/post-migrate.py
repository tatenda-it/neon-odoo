# -*- coding: utf-8 -*-
"""R1b-1 upgrade: re-run the HR access enforcement so the newly
installed hr_holidays manager group is stripped from non-OD/MD/Admin
users (and OD/MD gets it). post_init_hook only fires on fresh install;
a version-bumped upgrade runs this. Idempotent."""
from odoo import SUPERUSER_ID, api
from odoo.addons.neon_hr import _enforce_hr_confidentiality


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _enforce_hr_confidentiality(env)
