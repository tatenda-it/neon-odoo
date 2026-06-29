# -*- coding: utf-8 -*-
{
    "name": "Neon Commercial Intelligence - Controlled Execution (Phase 2D)",
    "version": "17.0.1.0.0",
    "category": "Sales/CRM",
    "summary": "Phase 2D controlled execution: an ACCEPTED review-queue item can "
               "be turned into a task/activity or campaign approval - by explicit "
               "human action only, fully traceable. No automation.",
    "description": """
Phase 2D - Controlled Execution.

Adds an explicit 'Execute' step to ACCEPTED review-queue recommendations. This
is the first point where the system creates artifacts - and it remains entirely
human-driven: a person must Accept (2B) and then Execute (2D). Nothing fires on
its own; there is no cron here. Every execution is recorded with a link to the
artifact it created (audit trail, §24).

What it can create (conservative set): a mail.activity (To-Do) on the linked
lead for next_action / leak_alert / recycle / play_reco / account_target /
brief_item items; and an 'approved' flip on a proposed campaign. It never sends
messages, never edits pricing, never acts without the Accept+Execute sequence.

Built ahead of the data gate by request. No Phase-1 logic modified.
""",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    "depends": [
        "neon_commercial_intel_planning",
    ],
    "data": [
        "views/neon_shadow_recommendation_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
