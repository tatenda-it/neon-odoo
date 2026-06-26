# -*- coding: utf-8 -*-
"""BANKING FRONT-DOOR (#3): demote + relabel the neon_finance "Banking" launcher
to "Reconciliation".

That menu record (neon_finance.menu_neon_banking_root) is noupdate=1 (it lives in
banking_setup_data.xml's <odoo noupdate="1">), so a data-file override is silently
skipped on existing installs -- the documented pattern is a migration write().
Cosmetic config only: ONLY name + sequence change; the menu's action (the
journal-cards kanban) is left untouched, so behaviour is unchanged. Idempotent.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    menu = env.ref("neon_finance.menu_neon_banking_root", raise_if_not_found=False)
    if menu and (menu.name != "Reconciliation" or menu.sequence != 32):
        menu.write({"name": "Reconciliation", "sequence": 32})
