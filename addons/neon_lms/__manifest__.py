# -*- coding: utf-8 -*-
{
    "name": "Neon LMS",
    "version": "17.0.1.1.0",
    "summary": "Internal LMS -- Coursera-style 7-track "
               "program with sub-certs + capstone. Phase 7e.",
    "description": """
Neon LMS (Phase 7e)
===================

Internal training program with 7 tracks (sub-courses), 17
modules, sub-cert + capstone issuance. Single slide.channel
(Odoo eLearning) backed by Neon-specific track + module
structure.

M1 (this version): track + module models + slide.channel
extension + ACLs + 7 track seeds + 17 module seeds.

Subsequent milestones:
* M2: operating authority model + 6 seeds
* M3: Foundations strict-gate enforcement helper
* M4-M6: quiz questions + practical scenarios + SOPs
* M7+: enrollment + completion + capstone workflow
""",
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Neon/Training",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "website_slides",
        "neon_core",
        "neon_training",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/neon_lms_program.xml",
        "data/neon_lms_tracks.xml",
        "data/neon_lms_modules.xml",
        # M2 -- authority + reverse mapping. Load AFTER
        # tracks so the M2M references resolve.
        "data/neon_lms_authorities.xml",
        "data/neon_lms_authority_mapping.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
