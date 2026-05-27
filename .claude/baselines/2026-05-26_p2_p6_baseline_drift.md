# Baseline drift — p2/p6 dev-DB failures (captured at Phase 8B M1-M3 close)

**Presumed baseline drift on the long-lived `neon_crm` dev DB as of
Phase 8B M1-M3 close (captured 2026-05-27).** NOT a regression from
Phase 8B work, per the evidence in the M1-M3 Gate 2 report:

- Phase 8B diff is entirely within `addons/neon_dashboard/` (+
  `.claude/` tests). The suites below test neon_jobs / neon_finance /
  partner state-machines + Phase 6 pricing — none touched.
- The only DB operations performed were `-u neon_dashboard`, an
  asset-attachment flush, and a container force-recreate — all of
  which alter `neon.dashboard.*` / asset rows only. The data these
  suites read is unchanged before/after Phase 8B.
- Signatures are setup/teardown crashes (drifted fixtures) and
  data-dependent computation mismatches, not assertion failures
  introduced by dashboard code.

Regression total at capture: **1807/1819** (12 failures across the 5
suites below). All Phase 8B + affected dashboard suites green (Python +
browser). Captured for future-regression diff comparison: any later run
can diff against this file to answer "is this failure new or old?".

---

## p2m2 — 7/11 (state-transition guards not blocking)

NO SUMMARY LINE in aggregate run (printed detail block, not the
`Total:` line the harness greps). T2 (4 FAILs) + T3a:

```
comm: won->lost (invalid)        -> lost        expected blocked  ACTUAL: success
op:   planning->live (skip)      -> live        expected blocked  ACTUAL: success
op:   pre_event->planning (back) -> planning    expected blocked  ACTUAL: success
fin:  quoted->fully_paid (skip)  -> fully_paid  expected blocked  ACTUAL: success
T2  Status transitions: 7/11 pass (4 FAILs)
T3a Archive without reason blocks: FAIL (should have raised UserError)
```
Root area: commercial/event-job/finance state-machine `@api.constrains`
guards not firing on this DB. Untouched by Phase 8B.

## p2m4 — crash (partner unlink blocked by accounting)

```
odoo.exceptions.UserError: The partner cannot be deleted because it is
used in Accounting
```
Deterministic data drift: a test partner is referenced by accumulated
`account.move` rows, so teardown unlink raises. Untouched by Phase 8B.

## p2m5 — crash (AccessError on soft-hold-extend wizard)

```
odoo.exceptions.AccessError: You are not allowed to create 'Extend Soft
Hold on a Commercial Job' (commercial.job.soft_hold.extend.wizard)
records.
```
Group/permission state on the dev DB. Untouched by Phase 8B.

## p2m7_7 — 6/8 (T36, T38 FAIL)

```
T36: FAIL
T38: FAIL
Total: 6/8 passed
```

## p6m3 — 18/28 (pricing day-multiplier mismatches)

```
T708-T713 FAIL, T717 FAIL (err: UserError x2), T722 FAIL
  days=3 expected=0.80 actual=1.00 FAIL
  days=8 expected=0.70 actual=1.00 FAIL
```
Phase 6 pricing engine: day-multiplier brackets returning 1.00 instead
of configured discounts — `day.multiplier` / `pricing.rule` seed data
drift on the dev DB. Untouched by Phase 8B.

---

## Triage

Tracked in `carryover_phase_9_kickoff.md`. Re-evaluate when the dev DB
gets a refresh cycle during Phase 9 production hardening — several of
these likely resolve when fixtures are rebuilt from clean seed.
