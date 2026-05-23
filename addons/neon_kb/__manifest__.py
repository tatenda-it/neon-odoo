# -*- coding: utf-8 -*-
{
    "name": "Neon Knowledge Base",
    "version": "17.0.1.0.0",
    "summary": "Custom knowledge base -- searchable "
               "SOPs / procedures / troubleshooting. Phase "
               "7d. Generalises neon_lms's SOP model into a "
               "broader internal surface.",
    "description": """
Neon Knowledge Base (Phase 7d)
==============================

Standalone searchable KB for Neon SOPs, procedures,
troubleshooting. Distinct from neon_lms (internal training)
and neon_external_training (off-site training): this is
reference material for the running operation.

M1: category + tag models + 5 seed categories (Audio /
Lighting / Video / Safety / Admin) + tier ACLs.
M2+: article model + state machine + portal route +
cross-links to LMS.
""",
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Neon/Knowledge",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "portal",
        "neon_core",
    ],
    "data": [
        "security/neon_kb_security.xml",
        "security/ir.model.access.csv",
        "data/neon_kb_categories.xml",
        "views/neon_kb_category_views.xml",
        "views/neon_kb_tag_views.xml",
        "views/neon_kb_menu.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
