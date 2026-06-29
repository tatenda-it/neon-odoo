# neon_commercial_intel_shadow — Phase 2B (standalone, additive)

Depends on **2A** (`neon_commercial_intel`). Built in the chat layer for Tatenda
to review + commit under the gated pipeline. **Built ahead of the data gate by
explicit request — carries known rework risk.**

## Shadow-mode discipline (the point of 2B)
Every rule/AI output lands in a **review queue** (`neon.shadow.recommendation`)
that a human Accepts or Rejects. **Accept records the decision only — it does NOT
create tasks or act on the system.** Turning accepted items into tasks/records is
Phase 2D, deliberately not built here. The live `x_lead_score` is never touched —
shadow scores go to a separate `neon_shadow_score` field.

## What's genuinely functional now (no live data needed)
- **Review queue** mechanics (accept/reject, traceable rationale, state).
- **Missing-info** computation on `crm.lead` (rule-based field-completeness).
- **Data-driven scoring rule model** (`neon.shadow.scoring.rule`) + evaluator +
  manual "Recompute Shadow Score" button.

## What's scaffolding / placeholder (WILL need rework post-data-gate)
- **Seeded scoring rules** are PLACEHOLDERS (weights/thresholds illustrative).
  They cannot be validated until ~3–4 weeks of clean post-cutover data exist.
- **Confidence bucketing** thresholds are placeholders.
- **Cron stubs** (daily brief, leak watch) ship **INACTIVE** and only create
  review items. The leak watcher MUST be reconciled with the existing #3/#5
  dashboard drafts before activating — do not duplicate their logic.

## P0-safe / additive
- No new menu root: hangs under 2A's `menu_neon_ci_root` / `menu_neon_ci_config`
  (backward refs — 2A loads first via `depends`).
- All view-arch `groups=` fully qualified (`neon_commercial_intel.group_...`).
- Reuses 2A's security groups. No Phase-1 logic modified.
- Crons inactive; nothing auto-acts.

## Before committing (Tatenda)
1. **2A must be deployed first** (2B depends on it). 2A is itself still held
   behind Gate 0 — so 2B cannot deploy until 2A does.
2. Commit onto prod's actual HEAD (same Gate 0 rule as 2A).
3. Fresh-install test (2A + 2B) on a scratch DB; Phase-1 regression green.
4. Leave all crons inactive and all shadow scores treated as non-authoritative
   until the data gate clears and rules are tuned.

## Sandbox verification target
Install on top of the sandbox 2A; confirm: Review Queue + Shadow Scoring Rules
menus appear, lead form shows the shadow block + Recompute button, rescore writes
shadow fields + drops a review-queue item, crons present but inactive.
