# -*- coding: utf-8 -*-
"""R3a upgrade: re-affirm HR access enforcement (defensive against the
documented neon_core noupdate=0 grant-wipe — see project memory
reference_neon_core_noupdate_grant_wipe) and ensure the R3a config
parameters exist. Idempotent."""
from odoo import SUPERUSER_ID, api
from odoo.addons.neon_hr import _enforce_hr_confidentiality


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _enforce_hr_confidentiality(env)
    icp = env["ir.config_parameter"].sudo()
    if not icp.get_param("neon_hr.licence_expiry_lead_days"):
        icp.set_param("neon_hr.licence_expiry_lead_days", "30")
    if not icp.get_param("neon_hr.competency_gate_mode"):
        icp.set_param("neon_hr.competency_gate_mode", "warn")
