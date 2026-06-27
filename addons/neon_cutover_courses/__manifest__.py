# -*- coding: utf-8 -*-
{
    "name": "Neon Cutover Courses",
    "version": "17.0.1.2.0",
    "summary": "1 July cutover onboarding courses seeded as website_slides "
               "data (Finance first; Sales pending verification).",
    "description": """
Neon Cutover Courses
====================

Seeds the cutover onboarding courses as **plain website_slides** content
(no neon_lms track/cert machinery, no neon_branded flag). Version-controlled,
source-of-truth course definitions so they exist on prod before the team logs
in for the 1 July cutover.

* Depends ONLY on `website_slides` -- installs and tests in isolation,
  independent of the neon_core/_jobs/_training chain.
* Content seeded with `noupdate="0"`: the module is the source of truth, so
  `-u` re-applies it and reverts stray UI edits (intended).
* Courses are seeded UNPUBLISHED (`is_published=False`); a director reviews
  and publishes after a gated deploy.

Currently ships: **Cutover -- Finance** (content walkthrough-verified against
live prod, 27 Jun 2026; see docs/CUTOVER_FINANCE_COURSE_VERIFIED.md).
Cutover -- Sales is deliberately NOT included until its content is verified.
""",
    "author": "Neon Events Elements",
    "category": "Neon/Training",
    "license": "LGPL-3",
    "depends": ["website_slides"],
    "data": [
        "data/cutover_finance_course.xml",
        "data/cutover_sales_course.xml",
        "data/cutover_director_course.xml",
    ],
    "installable": True,
    "application": False,
}
