# -*- coding: utf-8 -*-
{
    "name": "Neon Dashboard",
    # Phase 8 era opener -- new central pivot model (neon.dashboard).
    # Per CLAUDE.md manifest versioning: 17.0.<phase>.<minor>.<patch>.
    # 8.10/8.11/8.12 = Phase 8B Sales / Bookkeeper / Lead Tech variants.
    # 8.13 = Phase 8B M4 Edit Layout (per-user hide/reorder).
    # 8.13.1 = Phase 8B M5 brand-separator polish + phase close.
    # 8.14.0 = P9.M9.2 dashboard Jobs-block venue pin + modal map
    # (first Dialog-service consumer in neon_dashboard; reuses the
    # M9.2 NeonVenueMapView from neon_jobs).
    # 8.15.0 = P12.M1 AI Sales Copilot — chat session + message
    # audit models, tool registry + 9 READ tools, Groq tool-calling
    # adapter, chat orchestrator, /neon/ai_chat HTTP endpoints, OWL
    # chat panel mounted on director + sales variants.
    # 8.16.0 = P12.M1.1 multi-variant chat (Bookkeeper + Lead Tech)
    # + 5 new READ tools + 4 hotfixes (dedup, history pruning,
    # thinking-dots, variant-scoped tool advertisement).
    # 8.17.0 = P12.M1.1.1 UI header role label per variant +
    # 4xx outgoing-body capture (request_body_snapshot) +
    # 14-schema audit (all clean).
    # 9.0.0  = P12.M2 AI Copilot WRITE tools (log_lead, move_stage,
    # update_deal_value, post_chatter_note) with two-phase commit
    # (propose -> confirm card -> execute) + write.log audit model
    # + /neon/ai_chat/confirm,cancel endpoints + variant-persistence
    # fix (D33). Minor-major bump: first milestone where the LLM
    # can change prod data.
    # 10.0.0 = P-B2 Equipment Conflicts panel on Operations variant.
    # New block_conflicts widget + conflicts_block server payload
    # reading from neon.equipment.conflict (the new pivot model
    # added in neon_jobs 17.0.5.0.0). Read-only panel; engine runs
    # are triggered server-side.
    # 17.0.11.0.0 = P-HR-R3b C1 -- HR role-lens RBAC + KPI compute
    # (new 'hr' value in _DASHBOARD_TYPES; _is_hr_user gate at
    # the View-As resolver + defence-in-depth in _compute_kpi_hr).
    "version": "17.0.11.0.0",
    "summary": "Phase 8A Director Dashboard + Phase 8B role variants "
               "(Sales / Bookkeeper / Lead Tech) on the shared "
               "neon.dashboard framework -- per-variant KPI strips, "
               "filter chips, blocks, variant-aware AI Insights, "
               "MD-peek selector, and per-user Edit Layout "
               "(hide/reorder + apply-to-all + reset).",
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
        # M6 -- ir.config_parameter seed rows for ZiG-USD rate
        # management (manual override only -- no scraping, see
        # project_zig_usd_rate_manual_only memory).
        "data/zig_rate_config.xml",
        # M9 -- weekly digest cron + mail.template. Cron loads
        # noupdate=1 so manual UI tweaks survive -u; mail.template
        # likewise.
        "data/ir_cron_data.xml",
        "data/weekly_digest_mail_template.xml",
        # M11 -- AI provider seed (Groq + Rule-based) MUST load
        # before the AI cron so the ir.cron's model_id resolves +
        # before the views that reference action xmlids.
        "data/ai_provider_seed.xml",
        "data/ai_insights_cron.xml",
        # M10 -- snapshot report + 3 SHARED partials (kpis / jobs /
        # ar_aging). MUST load before weekly_digest_report so the
        # partial xmlids exist when the M9 digest t-calls them.
        "report/snapshot_report.xml",
        # M9 -- QWeb report (ir.actions.report + template). Loads
        # before the digest log view + menu so the report record
        # exists when the binding_type=report wires it onto the
        # log's print menu. Refactored at M10 to t-call the shared
        # partials from snapshot_report.xml above.
        "report/weekly_digest_report.xml",
        # Views second-to-last so menu can resolve the client-
        # action wrapper.
        "views/neon_dashboard_views.xml",
        # M5 -- target model tree + form views. Load before menu.
        "views/neon_dashboard_target_views.xml",
        # M9 -- digest log list + form. Load before menu.
        "views/neon_dashboard_digest_log_views.xml",
        # M11 -- AI provider + insight history views. Load
        # before the menu so the action xmlids resolve.
        "views/neon_dashboard_ai_views.xml",
        # M6 -- ZiG-USD rate wizard form. Load before menu.
        "wizards/neon_dashboard_zig_rate_wizard_views.xml",
        # M9 -- Send Weekly Digest wizard form. Load before menu.
        "wizards/neon_dashboard_send_digest_wizard_views.xml",
        # Menu loads LAST so all action xmlids exist in registry.
        # M5 adds Settings -> Neon -> Dashboard Targets here.
        # M9 adds Send Weekly Digest + Digest History here.
        "views/neon_dashboard_menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            # OWL bundle -- mirrors cash_flow_dashboard structure
            # (js + xml + scss in one directory).
            # P9.M9.2 -- venue map dialog component must load BEFORE
            # neon_dashboard.js (which imports NeonVenueMapDialog).
            "neon_dashboard/static/src/js/neon_venue_map_dialog/"
            "neon_venue_map_dialog.js",
            "neon_dashboard/static/src/js/neon_venue_map_dialog/"
            "neon_venue_map_dialog.xml",
            "neon_dashboard/static/src/js/neon_venue_map_dialog/"
            "neon_venue_map_dialog.scss",
            "neon_dashboard/static/src/js/neon_dashboard/"
            "neon_dashboard.js",
            "neon_dashboard/static/src/js/neon_dashboard/"
            "neon_dashboard.xml",
            "neon_dashboard/static/src/js/neon_dashboard/"
            "neon_dashboard.scss",
            # P12.M1 -- AI Sales Copilot chat panel.
            # P12.M2 -- confirmation_card MUST load BEFORE ai_chat.js
            # (ai_chat.js imports NeonAiConfirmationCard).
            "neon_dashboard/static/src/js/ai_chat/confirmation_card.js",
            "neon_dashboard/static/src/js/ai_chat/confirmation_card.xml",
            "neon_dashboard/static/src/js/ai_chat/ai_chat.js",
            "neon_dashboard/static/src/js/ai_chat/ai_chat.xml",
            "neon_dashboard/static/src/js/ai_chat/ai_chat.scss",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
