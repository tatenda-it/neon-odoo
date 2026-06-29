# -*- coding: utf-8 -*-
{
    "name": "Neon Commercial Intelligence - Shadow Layer (Phase 2B)",
    "version": "17.0.1.0.0",
    "category": "Sales/CRM",
    "summary": "Phase 2B intelligence SHADOW layer: rule-based shadow scoring, "
               "AI reason / deal risk / missing-info, and a review queue. "
               "Review-only - NO automatic actions.",
    "description": """
Phase 2B - Intelligence Shadow Layer (review mode only).

Adds, on top of 2A (neon_commercial_intel), a recommendation/review layer:
all AI/rule outputs land in a review queue (neon.shadow.recommendation) that a
human accepts or rejects. NOTHING acts automatically - turning approved
recommendations into tasks/records is Phase 2D, not here.

DATA-GATE WARNING (built ahead of the gate, by explicit request):
The scoring rules and thresholds are PLACEHOLDERS. They cannot be validated
until ~3-4 weeks of clean post-cutover live data exist. Treat shadow scores as
non-authoritative until tuned. Crons ship INACTIVE.

Genuinely functional now (no data needed): missing-info computation, the review
queue mechanics, the data-driven rule model. Everything else is scaffolding.

NOT included: any auto-action (2D), planning engines (2C), learning loops (2F),
ML. Does not modify Phase-1 logic. The live x_lead_score is left untouched -
shadow scores are written to a SEPARATE field.
""",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    "depends": [
        "neon_commercial_intel",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/neon_shadow_scoring_rule_data.xml",
        "data/neon_shadow_cron.xml",
        "views/neon_shadow_recommendation_views.xml",
        "views/neon_shadow_scoring_rule_views.xml",
        "views/crm_lead_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
