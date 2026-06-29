# -*- coding: utf-8 -*-
{
    "name": "Neon Commercial Intelligence - Planning Layer (Phase 2C)",
    "version": "17.0.1.0.0",
    "category": "Sales/CRM",
    "summary": "Phase 2C planning layer: campaign proposals, play recommendation, "
               "recycle review, product-demand review, competitor account map, "
               "monthly planning pack. Propose-only into the 2B review queue.",
    "description": """
Phase 2C - Planning Layer (propose-only).

Generates planning PROPOSALS that land in the 2B review queue for human
approval. Nothing acts automatically - approved proposals become artifacts only
in 2D. Built ahead of the data gate by request: the generators run on
PLACEHOLDER heuristics and produce meaningful output only once post-cutover live
data exists. Crons ship INACTIVE.

Adds: competitor account map (structural, usable now), campaign planning fields
on utm.campaign + a manual proposal action, play-recommendation action, and
inert recycle / product-demand / monthly-pack cron stubs. Reuses the 2B review
queue (extends its recommendation types). No Phase-1 logic modified.
""",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    "depends": [
        "neon_commercial_intel_shadow",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/neon_planning_cron.xml",
        "views/neon_competitor_account_map_views.xml",
        "views/utm_campaign_views.xml",
        "views/crm_lead_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
