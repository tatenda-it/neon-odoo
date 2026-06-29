# -*- coding: utf-8 -*-
{
    "name": "Neon Commercial Intelligence - Market Radar (Phase 2 / Radar MVP)",
    "version": "17.0.1.0.0",
    "category": "Sales/CRM",
    "summary": "Tender-alert ingestion hub: email + public-bulletin signals -> "
               "AI classify (async, INACTIVE) -> 2B review queue. No scraping, "
               "no auto-leads, no live calls until gated activation.",
    "description": """
Market Radar - Tender-Alert Ingestion Hub (MVP).

Realisation of brief s6.4 (Market Radar) feeding the competitor track (#10).
ADDITIVE, P0-safe, shadow-mode: every output is a proposal in the 2B review
queue. Crons ship INACTIVE; fit scores are PLACEHOLDERS (non-authoritative
until the data gate clears and weights are tuned).

Two ingestion adapters, one shared downstream:
  A) mail gateway (message_new -> RAW signal)  -- admin binds the alias/inbox.
  B) public-bulletin poller (parse a fetched string -> RAW signals) -- no live
     HTTP in this build; the fetch is a gated activation step.
Classify (async cron, INACTIVE) -> AI extract (provider-agnostic, see DECISION)
-> dedupe -> promote to neon.shadow.recommendation (market_signal / award ->
competitor_mention + a PROPOSED competitor-account-map row). Lead creation stays
the human Accept->Execute path (2B/2D); nothing here writes a crm.lead.

DEPLOY/ACTIVATION IS GATED (Gate 0 + cutover + written-AUP confirmation for eGP).
""",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    "depends": [
        "neon_commercial_intel_planning",   # -> 2B queue + 2A objects + 2C account map
        "neon_commercial_intel_execution",  # 2D: extend action_execute for market_signal -> lead
    ],
    # DECISION (spec/TASK reconcile): the TASK header says depends=[planning], but
    # its "NEW 2D EXECUTION BRANCH (required)" section + VERIFY both need the 2D
    # action_execute override and its neon_executed trace fields (defined in
    # neon_commercial_intel_execution). Implementing that branch REQUIRES depending
    # on execution, so it's added. The AI classify lane calls neon_ai_core's
    # existing orchestrator but imports it DEFENSIVELY at call time (try/except),
    # so it is not a hard dependency - classify gracefully no-ops if absent.
    "data": [
        "security/ir.model.access.csv",
        "data/neon_market_source_data.xml",
        "data/neon_radar_cron.xml",
        "views/neon_market_source_views.xml",
        "views/neon_market_signal_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
