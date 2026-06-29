# -*- coding: utf-8 -*-
{
    "name": "Neon Cockpits (role-aware landings)",
    "version": "17.0.1.0.0",
    "category": "Neon/UX",
    "summary": "Role-gated 'My Cockpit' landings (Director / Finance+HR / Sales / "
               "Technician). Security-group gated nav; money rules from the single "
               "shared VAT record; approvals via the existing confirm path; AI "
               "Planner surfaces the existing 2B review queue. Additive.",
    "description": """
Role-aware Landing/Cockpit layer. ADDITIVE — no Phase-1 logic changed; reuses the
existing neon_core tier groups, the single shared VAT tax record, the existing
two-step payment-confirm wizard, and the 2B review queue. Each role sees only its
cockpit (menu group-gating + cross-module ACL), not a parallel engine.

COUPLING: depends on the per-rep dashboard (DRAFT) and the 2B queue (Gate-0 held)
- sandbox scaffolding, CANNOT deploy ahead of them. Deferred surfaces (Undeposited
Funds, restricted Directors SA tier) are shown as deferred with NO live figures.
""",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    "depends": [
        "neon_core",                       # tier groups (director/finance/sales/lead-tech)
        "neon_crm_extensions",             # crm + payment-confirm wizard + outstanding balance
        "neon_finance",                    # shared VAT tax record + approvals
        "neon_jobs",                       # event jobs (technician)
        "neon_hr",                         # People/HR surface (Finance<->HR toggle)
        "neon_dashboard",                  # per-rep performance (DRAFT coupling)
        "neon_commercial_intel_shadow",    # 2B review queue (AI Planner; Gate-0 coupling)
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/neon_cockpit_info_data.xml",
        "views/neon_cockpit_info_views.xml",
        "views/neon_cockpit_actions.xml",
        "views/neon_cockpit_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
