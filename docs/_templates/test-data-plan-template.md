# Test Data Plan Template

> Standing pattern for every sub-phase schema sketch. Copy this section verbatim into each new sketch under §X "Test Data Plan" and populate the sub-phase-specific tables.

## Purpose

Two distinct data layers, distinct lifecycles:

| Layer | Purpose | Lifecycle | Password |
|---|---|---|---|
| **Seed data** | Production-flavoured content that ships with the module — base records every install should have | `noupdate=False` in `data/*.xml`. Survives upgrades. Migrates to prod. | N/A |
| **Test fixtures** | Deterministic per-tier users + records for smoke tests + manual UAT | `.claude/<phase>_<milestone>_smoke.py` seed scripts. Local-only. **Never ships to prod.** | `test123` (Phase 7a convention) |

Confusing these two is a common build error — seed data ends up cluttered with test usernames, OR test fixtures get committed to `data/` and ship to prod. The plan documents exactly which records go where.

## §A — Seed data (production-flavoured)

For each seed record set, capture:

| Record set | Model | Count | Source XML file | Variability |
|---|---|---|---|---|
| `<name>` | `<model>` | `<count>` | `data/<file>.xml` | low / medium / high |

**Variability** means: how much customization should production expect to make?

- **Low**: facts of the world (e.g., country list). `noupdate=True` is fine.
- **Medium**: reasonable defaults that may evolve as the business does. `noupdate=False` so future module upgrades can add new records.
- **High**: Neon-specific opinions Robin may revise. `noupdate=False` mandatory so prod edits survive but new records can still be added in module upgrades.

Seed data principles:

- Every record has a stable xmlid (`<module>_<descriptor>`)
- Use `noupdate=False` unless the record should be immutable post-install
- Variability HIGH records: prefer `noupdate=False` so prod edits survive but new records can be added in module upgrades
- Variability LOW records: `noupdate=True` is fine (e.g., enum-like reference data)
- Cross-module references via xmlid only (never hardcoded IDs)

## §B — Test fixtures (per-tier user matrix)

For each tier in the sub-phase ACL, capture:

| Tier | Fixture login | Password | Groups | Records owned / seen | Smoke test ref |
|---|---|---|---|---|---|
| `<tier>` | `<prefix>_<tier>` | `test123` | `<groups list>` | `<records>` | `.claude/<phase>_<milestone>_smoke.py` |

Test fixture principles:

- All passwords = `test123` (Phase 7a convention; baked into seed users since `ed2da64`)
- Logins follow `<phase><milestone>_<tier>` pattern (e.g., `p7b_m1_train_admin`)
- Fixtures created via ORM with `(4, group_id)` syntax — **NEVER raw SQL** (see `reference_odoo17_implied_ids_orm_vs_sql.md`)
- Each fixture's smoke test referenced by relative path
- After milestone close, fixtures are NOT torn down — they persist across milestones in the same sub-phase so later milestones can build on them
- BUT: fixtures from one sub-phase don't carry into the next (each sub-phase starts fresh — clear separation at the manifest version-era boundary)
- Get-or-create pattern: `setUp` blocks search for the login first; create only if missing. Idempotent across regression cycles.

## §C — Test scenario coverage

For each user-facing workflow in the sub-phase, identify the representative test scenario:

| Workflow | Scenario | Fixture used | Expected outcome |
|---|---|---|---|
| `<workflow>` | `<scenario description>` | `<fixture login>` | `<observable result>` |

Scenarios should cover:

- **Happy path per tier** — each tier's primary use case completes successfully
- **ACL boundaries** — tier X cannot do Y (record rule + group access)
- **State machine transitions** — each state visited at least once
- **Override / bypass paths** — e.g., admin skip, force-* helpers
- **Error cases** — missing required field, invalid state transition, FK violation, idempotency on retry
- **Cross-tier interaction** — actions by tier A trigger visible effects for tier B (notifications, gate fires, etc.)

## §D — Cleanup + drift detection

How to keep test data from contaminating prod:

| Concern | Mitigation |
|---|---|
| Test fixtures accidentally committed to `data/*.xml` | Pre-commit check: grep for `test123` in `data/*.xml` rejects commit |
| Seed data accidentally placed in test fixture file | Smoke test asserts the seed record exists by xmlid (so removing it from `data/` breaks the test) |
| Drift between dev seed and prod data | Phase 11 cutover plan includes seed-vs-prod diff audit |
| Test fixture leaks into prod via mid-test `env.cr.commit()` | Convention: smoke tests use `env.cr.savepoint()` + trailing `env.cr.rollback()`. Pre-commit check rejects `env.cr.commit()` in smoke files. Exception: seed-installation smokes (M1 fixture creation) that legitimately persist users across cycles — these are gated by a `_get_or_create` pattern (find-by-login first; create only if missing) and explicitly labelled |
| Test fixture login collisions across sub-phases | Logins prefixed by sub-phase (`p7b_*`, `p7e_*`); collision check at start of each smoke run via search-by-login |

## §E — Sub-phase-specific notes

Free-form section for anything not captured above. Likely includes:

- **Special test data**: e.g., a `res.partner` record needed for cert attachment tests; an external venue for cross-competency observation event_jobs; a backdated invoice for finance integration smokes
- **External dependencies**: e.g., a cron-triggered seed for testing scheduled jobs; an external API mock for Phase 9 WhatsApp send testing
- **Production seed coordination**: which seeds need Robin's review before deploy; cross-module xmlid dependencies
- **Performance budgets**: e.g., "Who can do X" wizard must return in <500ms with 50 users
- **Test environment quirks**: known issues with local Odoo's `transient.cleanup` cron, browser headless mode behaviour, etc.

---

End of template. Every sub-phase sketch should include this section, populated with sub-phase-specific content.

## Pre-flight checklist for the build phase

Before the first milestone of any sub-phase build, verify the populated Test Data Plan answers:

- [ ] §A: every seed file path matches the manifest's `data:` list ordering
- [ ] §B: every fixture login is unique within the sub-phase + doesn't collide with prior sub-phases
- [ ] §B: every fixture's groups list matches the ACL CSV rows that exist (no fictional groups)
- [ ] §C: every state in the state machine appears in at least one scenario
- [ ] §C: every override / bypass path has a scenario
- [ ] §D: pre-commit checks are wired in `.claude/run_regression.sh` or a pre-commit hook
- [ ] §E: any cron-dependent or external-dependency tests have an explicit deterministic-mode strategy (e.g., manual cron trigger via `env.ref(...).method_direct_trigger()`)

If any item is unchecked, the gate-1 plan for milestone 1 must surface the gap before code starts.
