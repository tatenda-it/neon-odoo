# -*- coding: utf-8 -*-
{
    "name": "Neon Commercial Intelligence - Learning & Optimisation (Phase 2F)",
    "version": "17.0.1.0.0",
    "category": "Sales/CRM",
    "summary": "Phase 2F learning loops + structured post-event review feeding "
               "neon.learning.record. Hard data-gated; loops are inert stubs.",
    "description": """
Phase 2F - Learning & Optimisation (the compounding layer).

The HARDEST data-gated sub-phase: the 7 learning loops (win/loss, campaign,
partner, play, event, product-demand, competitor) need substantial real
outcome history to produce anything but noise. Built ahead of the gate by
request - the loop generators are INERT cron stubs that populate the 2A
neon.learning.record; they should not run until well after cutover.

Genuinely functional now: the structured post-event review form (§12) - a
real, usable model that captures outcomes which the loops will later learn
from. The loop crons are placeholders and ship INACTIVE. Also requires the #2
intel boards to be rebuilt on live data (separate, blocked-on-data) before the
loops mean anything. No Phase-1 logic modified.
""",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    "depends": [
        "neon_commercial_intel_planning",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/neon_learning_cron.xml",
        "views/neon_post_event_review_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
