# -*- coding: utf-8 -*-
{
    "name": "Neon LMS",
    "version": "17.0.1.7.0",
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
        # M5 -- scenario completion record rule (learner
        # scoped to own records).
        "security/neon_lms_scenario_rules.xml",
        # M7 -- enrollment + completion record rules ("own
        # row" pattern, 4th instance in codebase).
        "security/neon_lms_enrollment_rules.xml",
        "data/neon_lms_program.xml",
        "data/neon_lms_tracks.xml",
        "data/neon_lms_modules.xml",
        # M2 -- authority + reverse mapping. Load AFTER
        # tracks so the M2M references resolve.
        "data/neon_lms_authorities.xml",
        "data/neon_lms_authority_mapping.xml",
        # M9 -- cert_type wiring. Load LAST so tracks +
        # channel exist; cross-module refs to
        # neon_training cert types resolve via depends order.
        "data/neon_lms_cert_type_wiring.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
