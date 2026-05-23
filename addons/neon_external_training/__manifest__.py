# -*- coding: utf-8 -*-
{
    "name": "Neon External Training",
    "version": "17.0.1.0.0",
    "summary": "External (off-site) training bookings -- "
               "manufacturer / regulator courses crew attend "
               "outside the internal LMS.",
    "description": """
Neon External Training (Phase 7c)
=================================

Tracks off-site training Robin sends crew to (manufacturer
courses, driver licensing, fire safety at venues). Distinct
from the internal LMS (Phase 7e) which covers in-house
training tracks.

M1: vendor model + 5 seed vendors + tier ACLs.
M2+: booking model + state machine + approval workflow +
auto-cert issuance on completion (cross-module to Phase 7a
neon.training.certification).
""",
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Neon/Training",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "neon_core",
        "neon_training",
    ],
    "data": [
        "security/neon_external_training_security.xml",
        "security/ir.model.access.csv",
        "data/neon_external_training_vendors.xml",
        "views/neon_external_training_vendor_views.xml",
        "views/neon_external_training_menu.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
