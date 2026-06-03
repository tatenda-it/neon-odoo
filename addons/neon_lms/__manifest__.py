# -*- coding: utf-8 -*-
{
    "name": "Neon LMS",
    # P7k (17.0.2.1.1): lesson-render fix -- the 237 lessons were
    # imported as slide_category='document'/'pdf' with no pdf payload,
    # so the player hung on "Loading..." (embed_code raises on a
    # file-less pdf). One-shot transform script (scripts/migrate_p7k_
    # slide_render.py, admin-run, NOT in data/) flips them to 'article'
    # so html_content renders; html preserved byte-for-byte. Plus the
    # invented lime accent (#c8f36b) retired from the LMS branding +
    # quiz SCSS -> white on grape surfaces, grape on light (gate badge
    # -> white pill + grape text/border; quiz CTA -> grape bar). No
    # model change; patch bump.
    # P7i (17.0.2.0.0): learner-facing review-quiz surface + the
    # neon.lms.quiz.attempt pivot model -- the missing "M10 attempts
    # model" that writes module.completion.quiz_score and so FEEDS the
    # existing module -> track -> sub-cert -> capstone workflow. Major
    # bump: new central pivot model. Layered on P7h (1.17.0) per the
    # P7g(1.16)->P7h(1.17)->P7i(2.0.0) lineage.
    # P7h (17.0.1.17.0): dedicated Neon LMS footer on /slides* pages.
    # P7g (17.0.1.16.0): course-page branding layer -- Neon hero + track
    # cards + capstone band on the course landing (scoped QWeb + SCSS),
    # plus the one-shot publish/visibility/responsible/orphan-cleanup
    # config applied via migration.
    "version": "17.0.2.1.1",
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
        # P7i -- quiz-attempt own-row rules (learner sees/creates
        # only their own attempts + responses).
        "security/neon_lms_quiz_attempt_rules.xml",
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
        # LMS Admin Polish M1 -- Bulk Quiz Import wizard +
        # LMS admin menu root + Tools submenu.
        "views/neon_lms_quiz_import_wizard_views.xml",
        "views/neon_lms_menu.xml",
        # LMS Admin Polish M2 -- module form/tree + 4-tab
        # notebook + inline quiz/scenario editing + Modules
        # menuitem. Loads AFTER neon_lms_menu.xml so the
        # menuitem can target menu_neon_lms_root.
        "views/neon_lms_module_views.xml",
        # LMS Admin Polish M3 -- slide.slide form override
        # adding LMS badge + autosave indicator + explicit
        # html widget on description.
        "views/neon_lms_slide_views.xml",
        # LMS Admin Polish M4 -- standalone question form +
        # tree views with header-button templates + Set
        # Default Points action.
        "views/neon_lms_quiz_views.xml",
        # P7g -- branded course landing (hero + track cards + capstone),
        # inherits website_slides.course_main; scoped to neon_branded.
        "views/neon_lms_branding_templates.xml",
        # P7h -- dedicated Neon LMS footer on /slides* pages only
        # (conditional swap; global footer untouched elsewhere).
        "views/neon_lms_footer_templates.xml",
        # P7i -- quiz-attempt admin views + menu.
        "views/neon_lms_quiz_attempt_views.xml",
        # P7i -- learner-facing review-quiz website templates +
        # course-page CTA (inherits website_slides.course_main).
        "views/neon_lms_quiz_templates.xml",
        # P7j (item 2) -- remove the "Useful Links" column from the
        # GLOBAL footer (inherits website.footer_custom; reversible).
        "views/neon_lms_global_footer.xml",
    ],
    "assets": {
        "web.assets_backend": [
            # LMS Admin Polish M3 -- autosave indicator JS.
            "neon_lms/static/src/js/lms_slide_autosave.js",
        ],
        # P7g -- course-page branding styles (scoped under .o_neon_lms_*;
        # @font-face Fraunces; fonts + logo served as static, not bundled).
        # P7i -- review-quiz styling (separate file; scoped under
        # .o_neon_lms_quizwrap so no other website page is touched).
        "web.assets_frontend": [
            "neon_lms/static/src/scss/neon_lms_branding.scss",
            "neon_lms/static/src/scss/neon_lms_quiz.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
