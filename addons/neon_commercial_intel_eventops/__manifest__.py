# -*- coding: utf-8 -*-
{
    "name": "Neon Commercial Intelligence - Event Ops Bridge (Phase 2E)",
    "version": "17.0.1.0.0",
    "category": "Sales/CRM",
    "summary": "Phase 2E sales->ops bridge: visibility of confirmed deals not yet "
               "turned into Event Jobs. Install-safe (crm.lead only).",
    "description": """
Phase 2E - Event Operations Foundation (bridge half).

IMPORTANT SCOPE NOTE: The operational Event Job + equipment register already
EXIST and are deployed in neon_jobs (commercial.event.job, neon.equipment.*) -
do NOT rebuild them. The genuine 2E gaps are (1) visibility of confirmed deals
not yet converted to Event Jobs, and (2) the T-3 jobs-missing-allocation view.

This module ships the INSTALL-SAFE half only: the crm.lead-side conversion-gap
visibility, using crm.lead + new fields - it does NOT touch commercial.event.job
internals. The second half (real link to commercial.event.job + T-3 allocation
dashboard) needs the live neon_jobs schema and is left as a documented
completion step for Claude Code (see README) - guessing those field names would
ship install failures. NOT data-gated; the bridge half is usable now.

No Phase-1 logic modified.
""",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    "depends": [
        "neon_commercial_intel",
    ],
    "data": [
        "views/crm_lead_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
