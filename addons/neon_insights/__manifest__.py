# -*- coding: utf-8 -*-
{
    "name": "Neon Feedback Insights",
    # WA-11 (B11) -- read-only client-feedback INSIGHTS over the post-event
    # corpus WA-10 builds (commercial.event.feedback). A served page at
    # /neon/insights (the neon_status pattern), manager-tier ONLY: three v1
    # views -- per-client satisfaction timeline, recent-feedback stream, and
    # sentiment aggregates (month buckets in Africa/Harare + recurring-
    # negative flags). NO new write paths; the access gate is enforced in the
    # collector (data layer), not just the menu. NO seed data ships -- prod
    # installs with honest empty-states and fills as events wrap; the
    # ~12 fixture rows live inside pwa11 only. AI digest = WA-11.1 (parked).
    "version": "17.0.1.0.0",
    "summary": "Read-only client-feedback insights (WA-11): a manager-tier "
               "served page at /neon/insights over the WA-10 corpus.",
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Neon/Reporting",
    "license": "LGPL-3",
    "depends": ["base", "web", "neon_core", "neon_jobs"],
    "data": [
        "views/neon_insights_templates.xml",
        "views/neon_insights_menu.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
