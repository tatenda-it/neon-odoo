# -*- coding: utf-8 -*-
{
    "name": "Neon Dashboard",
    # Phase 8 era opener -- new central pivot model (neon.dashboard).
    # Per CLAUDE.md manifest versioning: 17.0.<phase>.<minor>.<patch>.
    "version": "17.0.8.0.0",
    "summary": "Phase 8A -- unified role-aware Director Dashboard "
               "framework + headline KPI strip + Jobs block. "
               "Frames the Phase 8B role variants (Sales / "
               "Bookkeeper / Lead Tech / Tech) without shipping "
               "them yet.",
    "description": """
Neon Dashboard (Phase 8A)
=========================

Director Dashboard plus the framework for Sales / Bookkeeper /
Lead Tech / Tech variants (Phase 8B). Single discriminator field
``dashboard_type`` on ``neon.dashboard`` switches between views;
zero new models in Phase 8B.

M1: framework + neon.dashboard + neon.dashboard.user.layout +
    default layouts + role-aware controller + "View as..." for
    superusers + view filter chip stubs + top-level menu.
M2: 7 headline KPI tiles -- cash on hand (USD via account.journal
    aggregation; ZWG total deferred to M6 alongside RBZ rate
    cron), AR overdue, jobs today, jobs this week, pipeline
    value, new leads, forecast vs target.
M3: Jobs block -- today + next 7 days, ordered by date then
    value, with status badges mapped from the 12-state event_job
    machine to the 5-bucket mockup palette.

Architecture pattern (matches P5.M10 Workshop + P6.M10 Cash Flow
precedent documented at reference_owl_dashboard_pattern.md):

* Virtual model with @api.model RPC entry points -- no /neon/...
  HTTP controllers.
* Inline-return server-action wrapper for the menu (no persisted
  ir.actions.client; direct URL bypass impossible).
* Three-layer enforcement: menu groups, server-action groups_id,
  RPC _check_dashboard_access guard.

Group strategy (locked at gate 1): reuse the five neon_core tier
meta-groups instead of inventing five new group_neon_dashboard_*
groups. Cuts user-grant maintenance to zero (neon_core already
cascades robin / munashe / tatenda / admin / lisa / evrill /
ranganai by login).
    """,
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Neon/Dashboard",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "web",
        # Tier meta-groups -- mandatory dependency, drives both
        # ``_default_dashboard_type_for_user`` and ``_is_superuser``
        # (no new dashboard groups created in this phase).
        "neon_core",
        # commercial.event.job + commercial.job for the Jobs block
        # and KPI tiles 3-4 (jobs today / week).
        "neon_jobs",
        # neon.finance.quote (pipeline tile) + account.move (AR
        # overdue tile) + account.journal (cash-on-hand source).
        "neon_finance",
        # crm.lead with neon_crm_extensions fields (new leads tile;
        # uses standard create_date, but the extension is the
        # canonical home for our lead model).
        "neon_crm_extensions",
        # Group reference parity -- the tier-3 sales-rep cascade
        # includes neon_training groups so leaving it in depends
        # keeps the registry deterministic on -i.
        "neon_training",
    ],
    "data": [
        # Security loads first so groups exist when ACL CSV is read.
        "security/neon_dashboard_security.xml",
        "security/ir.model.access.csv",
        # Default layouts seed (noupdate=1) -- per dashboard_type
        # widget list. Five records (one per type).
        "data/default_layouts.xml",
        # Views second-to-last so menu can resolve the client-
        # action wrapper.
        "views/neon_dashboard_views.xml",
        # Menu loads LAST so all action xmlids exist in registry.
        "views/neon_dashboard_menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            # OWL bundle -- mirrors cash_flow_dashboard structure
            # (js + xml + scss in one directory).
            "neon_dashboard/static/src/js/neon_dashboard/"
            "neon_dashboard.js",
            "neon_dashboard/static/src/js/neon_dashboard/"
            "neon_dashboard.xml",
            "neon_dashboard/static/src/js/neon_dashboard/"
            "neon_dashboard.scss",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
