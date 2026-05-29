# -*- coding: utf-8 -*-
"""Re-run the Q28 confidentiality enforcement on upgrade.

post_init_hook only fires on a fresh install. On an existing install
(e.g. the dev DB where neon_hr 17.0.1.0.0 was already installed before
this enforcement existed) a version-bumped upgrade runs this script so
the auto-granted hr_user/hr_manager grants are stripped from non-HR
users. Idempotent — safe to re-run.
"""
from odoo import SUPERUSER_ID, api
from odoo.addons.neon_hr import _enforce_hr_confidentiality


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _enforce_hr_confidentiality(env)
