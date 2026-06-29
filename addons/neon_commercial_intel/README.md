# neon_commercial_intel — Phase 2A (standalone, additive)

Drafted in the chat/advisory layer for **Tatenda to review and commit** under the
gated propose→confirm→execute pipeline. Built standalone so it ports onto whatever
base Gate 0 confirms.

## What it adds (additive only — no Phase-1 logic modified)
- **New models:** `neon.event.opportunity` (§7.2, pursuit-stage — distinct from the
  operational `commercial.event.job`), `neon.play` (§7.4 + 8 seed plays),
  `neon.competitor` (§7.5), `neon.strategic.account.plan` (§7.6),
  `neon.learning.record` (§11 skeleton, populated in 2F).
- **`res.partner`** partner-intelligence fields (§7.3), `neon_`-prefixed.
- **`crm.lead`** intelligence fields (§7.1): event type/sector, strategic value,
  score confidence, competitor (structured), play used, margin estimate +
  commercial quality, learning note, outcome taxonomy, next-best-action.
- **§19 data-quality gates:** config-driven, on `crm.stage`. **Installs INERT** —
  enforces nothing until a manager turns on `neon_gate_active` for a stage and
  selects required fields. (Munashe sign-off gate.)
- **Event Opportunity Graph (§6.3):** m2o links across the objects above.

## P0-safe (cold-install) design
- Module declares its **own top-level menu root** (`menu_neon_ci_root`); it does
  **not** hang under another module's menu xmlid → no forward reference to an
  xmlid that loads later (the menu load-order bug class).
- Manifest `data` order: groups → access → root menu → seed data → per-model
  views. Each per-model view file defines its `action` **before** the submenu
  that references it. Verified: actions-before-menus, parents-from-root-file.
- No dependency on the `neon_training`/`neon_hr` P0 fix landing first.

## Before committing (Tatenda)
1. **Base:** commit onto **prod's actual HEAD** (Gate 0 STEP D), not `origin/main`.
2. **Depends present?** Confirm `neon_core`, `neon_crm_extensions`, `crm`, `utm`,
   `contacts` exist on the chosen base. (Trim/adjust if naming differs on live.)
3. **Fresh-install test** on a scratch DB → confirm cold install is clean.
4. **Phase-1 regression** (Gate 0 STEP E checklist) → green.
5. **Inherited-view xpaths** assume stock form view ids: `crm.crm_lead_view_form`,
   `base.view_partner_form`, `crm.crm_stage_form`. If any are overridden on live,
   re-point the xpath. (Low risk, but verify against the live views.)

## Verification the sandbox cannot do (flag for live check)
- `noupdate` layout propagation on already-installed DBs (the play seed + groups
  use `noupdate="1"`).
- Real-data shape of the §19 gate once stages are mapped.
- Visual render of the injected notebook pages.

## Explicitly NOT in this module (later sub-phases)
Scoring/AI compute (2B), planning engines (2C), execution (2D), event-ops wiring
(2E), learning loops/crons (2F). No automated outbound. No ML.
