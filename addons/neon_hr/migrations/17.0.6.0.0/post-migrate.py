# -*- coding: utf-8 -*-
"""P-HR-R3b C4 -- post-migrate for neon_hr 17.0.6.0.0.

Two idempotent operations:
  1. Re-fire _enforce_hr_confidentiality to defend against the
     documented neon_core noupdate=0 grant-wipe class. The
     post_init_hook only runs on -i (not -u), so a -u after a
     neon_core reload that wiped the OD/MD -> hr_manager cascade
     leaves HR access broken; this re-applies idempotently.
  2. Mark all neon.hr.overtime (TOIL) records active=False.
     TOIL is retired per OD/MD (overtime is incentive-covered).
     Data is PRESERVED (perm_unlink=0 + active=False, not unlink)
     for audit; reversible by setting active=True manually.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1. Re-fire HR confidentiality + superuser grants.
    from odoo.addons.neon_hr import _enforce_hr_confidentiality
    _enforce_hr_confidentiality(env)

    # 2. Retire TOIL records (active=False; data preserved).
    Overtime = env["neon.hr.overtime"].sudo()
    active = Overtime.with_context(active_test=False).search(
        [("active", "=", True)])
    if active:
        active.write({"active": False})
