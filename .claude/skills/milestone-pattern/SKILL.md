---
name: milestone-pattern
description: Standard procedural flow for building, testing, and committing a Phase 6 (or later) milestone in the neon-odoo repo. Invoke this when starting a new milestone (e.g. "starting P6.M7") to get the full 16-step build flow, discovery checklist, ⚠️ DECISION marker conventions, and gate-protocol details. Standing project rules are in CLAUDE.md and always-loaded; this skill is the executable checklist.
---

# Milestone Pattern

Procedural skill for executing a neon-odoo milestone end-to-end.

Invoke at the start of every milestone. The project CLAUDE.md is 
always loaded and contains the standing invariants; this skill 
contains the procedural checklist + gate protocols.

## ⚠️ DECISION marker conventions

When a mid-build judgment call doesn't warrant a hard pause:
1. Inline comment at the decision point in code
2. Listed in gate 2 diff summary

**Warrants a marker**:
- Choosing between two valid implementations when spec is silent
- Resolving an unstated constraint discovered mid-build
- Deviating from spec because spec was wrong about Odoo
- Adding a field/option not in spec because spec needs it
- Choosing on_delete behavior when spec is silent

**Doesn't need a marker** (just pick and document inline):
- Field ordering in views
- Selection option ordering
- Method names (within Odoo convention)
- Sequence numbers for ir.sequence
- Migration style choices

## Discovery checklist (before gate 1)

Before any code, discovery must cover:

1. Read current state of the module being touched (manifest version, 
   existing models, ACLs)
2. Read any model being extended via `_inherit`
3. Verify schema assumptions in the spec — does claimed field X 
   actually exist? what's its type? where does it live?
4. Check sequence and test-fixture state on the local DB
5. Identify cross-module integration points
6. Verify forward-references in the spec (fields declared for models 
   not yet built)
7. Browser smoke prerequisites (chromium, fixtures present)
8. Carry-over: any polish items from prior milestones this milestone 
   should close?

Report ALL findings at gate 1. Spec-vs-reality mismatches are the 
MOST important finding — flag explicitly.

## Standard build flow (16 steps)

After gate 1 approval:

1. Bump manifest version per the convention (see CLAUDE.md)
2. Build models, sequences, ACLs, record rules, views, migrations 
   in dependency order
3. Write `p<N>_smoke.py` (Python tests)
4. Write `p<N>_browser_smoke.py` (autonomous browser, depth principle)
5. Add to `BROWSER_SMOKES` in `.claude/run_regression.sh`
6. Local `-u neon_finance` (or relevant module)
7. **Force-recreate odoo container** (critical — May 18 2026 lock)
8. Run Python smoke standalone → expect ALL PASS
9. Full regression cycle 1 → expect baseline + new tests stable
10. Full regression cycle 2 on SAME DB → user_ids unchanged 
    (validates fixture stability)
11. Autonomous browser smoke gate → all suites PASS
12. Compose gate 2 diff summary with ⚠️ DECISION markers
13. **GATE 2** — await commit approval
14. After approval: commit with meaningful message
15. Post-commit: JSON-RPC probe drift check (8/8 PASS expected)
16. Update `project_phase6_status.md` with milestone result + any 
    new polish items

## Migration patterns

Migrations fire on version bump. Required when:
- Security records with `noupdate=1` change
- Stored computed fields need explicit recompute on existing data
- Cross-module records need group additions

Use `skip_finance_notification=True` context flag to suppress alert 
dispatch during bulk migration. Pattern: idempotent (`(4, id)` adds), 
defensive (no-op when already in target state).

## Diagnostic pattern on hard stop

When stopping mid-build:
1. STOP — don't apply fixes
2. Identify root cause via RPC inspection / file reading / SQL
3. Report symptom verbatim + evidence + 3 fix options ranked by 
   trade-off
4. AWAIT direction before applying any fix

This pattern caught 4 real bugs in P6.M1 that would otherwise have 
shipped (wrong XML id, app root narrowing, menu parent gating, 
bookkeeper minimal-role).

## Browser smoke depth in practice

Per scenario, for each user tier:
- Login
- Assert app launcher state (expected apps visible/hidden)
- Navigate to relevant menus
- For each menu marked visible: CLICK in, assert content
- For each menu marked hidden: assert NOT in load_menus + direct 
  URL returns access error + direct RPC returns AccessError
- Logout

The negative case (menu hidden) needs RPC verification, not just UI 
verification, because "menu not visible" can be confused with "user 
didn't navigate there."

## Schema Sketch §6 caveat (added P6.M6)

The Schema Sketch §6 contains write()-based dispatch patterns. Odoo 
compute chains bypass write(). For M7-M11 work referencing similar 
dispatch in §6 of the Schema Sketch: verify dispatch mechanism during 
design pause. Don't assume write() will fire.

## Commit message convention

`feat(p6.m<N>): <short summary> — <key feature> + <other key feature>`

Examples from history:
- `feat(p6.m1): pricing rules + day multipliers + conversion rate table foundation`
- `feat(p6.m4): approval workflow + pricing_status honesty fix — universal OD/MD approval per Q14 (config-flag relaxation reserved)`
- `feat(p6.m6): budget tracking enhancements — variance-based alerts with idempotency + configurable thresholds + over-budget banner`

Fix rounds within a milestone use `fix(p6.m<N>): <description>`.
