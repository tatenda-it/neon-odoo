# -*- coding: utf-8 -*-
"""R2 upgrade: re-affirm the HR access enforcement. Defensive against
the documented neon_core noupdate=0 grant-wipe (see project memory
reference_neon_core_noupdate_grant_wipe) — re-applies the OD/MD
hr_manager / hr_holidays_manager grant + strips privileged HR groups
from non-OD/MD/Admin. Idempotent."""
from odoo import SUPERUSER_ID, api
from odoo.addons.neon_hr import _enforce_hr_confidentiality


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _enforce_hr_confidentiality(env)
