# Weekend Phase-2 + Cockpits — Review Handoff (for Tatenda)

**Branch:** `feature/weekend-phase2-cockpits-2026-06-28` (off `feat/wa6-equipment-face`).
**Status:** REVIEW ONLY. Nothing merges to main, no tags, no deploy. All built/verified
LOCAL SANDBOX (`neon_db`) only. Commits are logically grouped so each can be reviewed /
cherry-picked independently.

> **Gate reminder (do NOT bypass):** the whole stack is **Gate-0 held** — needs the prod
> git HEAD to pin a deploy base; post-cutover only. `neon_cockpits` depends on the per-rep
> dashboard (DRAFT: repo 11.10.0 vs live 11.6.2) + the 2B queue — **cannot deploy ahead of
> them**. Radar needs PRAZ written-AUP + an `neon_ai_core` API key before any live run
> (crons ship INACTIVE). The Ranganai `active=False` user-deactivation is a **prod-deploy-time
> step** (he is not in the sandbox DB).

## Modules & gate status

| Module | Purpose | Depends | Gate / status |
|--------|---------|---------|---------------|
| **neon_commercial_intel** (2A) | Phase-2 data layer: Event Opportunity, Play (8 seed), Competitor, Strategic Account Plan, Learning Record + crm.lead intel fields + partner-intel + §19 stage gates | crm, utm, contacts, neon_core, neon_crm_extensions | Gate-0; sandbox-verified clean (v17.0.1.0.1 — group ext-id fix applied) |
| **neon_commercial_intel_shadow** (2B) | Shadow review queue (`neon.shadow.recommendation`) + missing-info + data-driven shadow scoring; **x_lead_score never touched**; crons INACTIVE | 2A | Gate-0 + **DATA-GATE** (scores are PLACEHOLDERS until ~3–4 wks live data) |
| **neon_commercial_intel_planning** (2C) | Campaign/play/recycle/competitor-account-map proposals → queue; 3 crons INACTIVE | 2B | Gate-0 + DATA-GATE |
| **neon_commercial_intel_execution** (2D) | Accept→Execute: approved recs create To-Dos / approve campaigns; human-only, traceable | 2C | Gate-0 |
| **neon_commercial_intel_eventops** (2E) | Install-safe sales-side Event-Job bridge + gap view. **KNOWN-INCOMPLETE:** real `commercial.event.job` link + T-3 allocation view need live `neon_jobs` schema | 2A | Gate-0; bridge only |
| **neon_commercial_intel_learning** (2F) | Post-event review → learning records (7 loops); 2 crons INACTIVE | 2C | Gate-0 + DATA-GATE (needs more live history) |
| **neon_commercial_intel_radar** | Tender-alert ingestion hub (email + eGP public-poll → AI classify → dedupe → queue); **no scraping, no auto-lead**; AI lane is provider-agnostic (Groq default/Gemini fallback — NOT Claude/xAI); crons INACTIVE | 2C (+ ai_core soft, + 2D for the market_signal→lead execute branch) | Gate-0 + **PRAZ written-AUP** + AI key before any live run |
| **neon_cockpits** | Role-gated landings: Director / Finance(+HR toggle) / Sales / Technician. Menu group-gating + cross-module ACL; VAT from the single shared `tax_vat_15_5_sale` (not hard-coded); approvals via existing `neon.payment.confirm.wizard`; AI Planner surfaces the 2B queue; deferred surfaces flagged | neon_core, neon_crm_extensions, neon_finance, neon_jobs, neon_hr, neon_dashboard (DRAFT), 2B | Gate-0; **cannot deploy ahead of per-rep dashboard + 2B** |

## Ranganai offboarding (scoped, reviewed) — commit D
- Lead Tech **role/group kept** (permanent); only the **person** offboarded.
- `neon_core` `_TIER_ASSIGNMENTS`: login removed (role marked VACANT); `parse_crew.py` Ranganai **ACTIVE→FORMER** (`active=False`, name preserved as historical audit).
- All functional logic already group-driven (lead_tech default, dashboard tier, finance cost-line rule); only comments + live mail-templates neutralised.
- `CLAUDE.md §2` updated: Lead Tech permanent, currently VACANT, default `lead_tech_id` none.
- **Historical preserved on purpose:** `neon_migration` roster + dated `docs/` deploy logs keep his name (audit/history). Zero forward-looking/functional hits.
- **Prod step (not done here):** deactivate the `ranganai@neonhiring.co.zw` user record (he's not in the sandbox DB).

## Deliberately EXCLUDED from this branch
- `addons/neon_banking_labels/__manifest__.py` — intentionally HELD (local cold-install depends edit; flagged for Tatenda in PROGRESS.md).
- `.claude/settings.json`, `CLAUDE-1.md`, `CLAUDE-2.md`, `NEON_WORKING_SETUP.md` — local/session scratch, not Phase-2 work.

## Separate follow-ups (not in this branch)
- Clean **stage-config** fix: live `crm.stage` names/order differ from the canonical funnel (`New, Contacted, Qualifying, Proposal Sent, Negotiation, Payment Pending Verification, Closed Won, Lost`). Cockpit reads live stages (no hard-coding) and will reflect canonical names once fixed.
- Finance-course prod deploy (parked) + the repo-vs-live reconciliation (main is ~166 behind the live lineage) — both await the prod git HEAD.
