# -*- coding: utf-8 -*-
{
    "name": "Neon Commercial Intelligence (Phase 2A)",
    "version": "17.0.1.0.1",
    "category": "Sales/CRM",
    "summary": "Phase 2A data-structure layer: Event, Play, Competitor, "
               "Strategic Account Plan, Learning Record, partner intelligence, "
               "CRM lead intelligence fields, and configurable stage data-quality gates.",
    "description": """
Phase 2A - Data Structure & Control (additive only).

Adds the Phase 2 commercial objects and CRM intelligence fields with NO
modification to existing Phase-1 logic. Safe to cold-install.

Self-contained menu root (no forward/cross-module xmlid references).
Data load order: groups, access, root menu, seed data, then per-model views
(each defines its action before the submenu that references it).
Stage data-quality gates install inert: they enforce nothing until an admin
maps required fields per stage (Munashe sign-off gate).

NOT included (later sub-phases): scoring/AI logic (2B), planning engines (2C),
execution (2D), event-ops wiring (2E), learning loops (2F).
""",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    "depends": [
        "neon_core",
        "neon_crm_extensions",
        "crm",
        "utm",
        "contacts",
    ],
    "data": [
        # 1. Security groups FIRST (referenced by menus + access).
        "security/neon_ci_groups.xml",
        # 2. Access rights.
        "security/ir.model.access.csv",
        # 3. Root menu ONLY (no action refs) — parent before any child menu.
        "views/neon_ci_root_menu.xml",
        # 4. Seed data (models come from python; no external xmlid refs).
        "data/neon_play_data.xml",
        # 5. Per-model views — each file defines its action ABOVE its submenu.
        "views/neon_event_opportunity_views.xml",
        "views/neon_play_views.xml",
        "views/neon_competitor_views.xml",
        "views/neon_strategic_account_plan_views.xml",
        "views/neon_learning_record_views.xml",
        # 6. Inherited views (additive field injection — no new menus).
        "views/crm_lead_views.xml",
        "views/res_partner_views.xml",
        "views/crm_stage_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
