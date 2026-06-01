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

**Update 2026-05-28 (P9.M9.2 close):** p6m1 added (same family —
conversion_rate fixture unique-key violation accumulated since
capture). p9m1_1_drop_pin T9111 was a stale literal-version
assertion; fixed in-place to drop the hard-coded `"17.0.4.2.0"`
match. Otherwise drift set unchanged.

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

## p6m1 — NO SUMMARY (UniqueViolation on conversion_rate fixture, 2026-05-28)

Surfaced during P9.M9.2 regression on 2026-05-28; not present at the
2026-05-26 baseline capture but same family — accumulated fixture
rows in the long-lived dev DB violating a unique index:

```
psycopg2.errors.UniqueViolation: duplicate key value violates unique
  constraint "neon_finance_conversion_rate_unique_effective_date"
DETAIL:  Key (effective_date)=(2026-05-18) already exists.
```

Setup-time crash; no assertions reached. Untouched by P9.M9.2 (which
only edits `neon_dashboard` + `neon_jobs/static/src/js/venue_map`).
Same triage trigger as the other p2/p6 entries — fixture cleanup
debt that will resolve on next dev-DB rebuild.

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

---

## Update 2026-05-29 (P-HR-R1a close) — regression 2056/2073

Five suites NEW vs the 2026-05-26 set surfaced during the P-HR-R1a
(neon_hr) regression. NONE are neon_hr functional regressions — root
causes below. Captured so the next run can diff cleanly.

### p4m2 — 7/9 (T170, T178) + p4m8 — 9/10 (T240)
Action Centre trigger-config COUNT tests assert exactly 16
(`len(configs) == 16`, selection == 16 values). The shared registry
has since grown to **18** by two legitimate module extensions:
- `load_window_missing` — **B-B2** (already in the working tree, comment-
  tagged "P-B2"; B2 added the trigger + config but did not update these
  count tests). This alone makes the count 17 → the tests were ALREADY
  red before neon_hr.
- `contract_expiry_30days` — **P-HR-R1a** (neon_hr reuses the Action
  Centre per spec via `selection_add`, +1 → 18).
These are stale exact-count assertions, not functional failures. Fix at
B2/neon_hr merge: change `== 16` to `base16.issubset(got)` + `>= 16`
(assert the 16 neon_jobs triggers are present, allow module extensions).
Not edited here to avoid colliding with the parallel B2 session.

### p2m7 — 16/17 (T2)
"All 5 dashboard counts compute to 0 on empty DB" — the long-lived dev
DB is not empty: `gate_issues_count=1`, `cash_flow_count=2` from data
accumulated since the 2026-05-26 capture (p12/b1/regression commits).
Same family as p2m2/p2m4 (data-dependent computation drift). neon_hr's
browser smoke briefly added to `needs_attention_count` via committed
cron items; that is now cleaned at smoke setup-start, so neon_hr no
longer contributes (verified: after cleanup, the two non-zero counts
are unrelated to HR).

### pb1_datamodel — 29/30 (T-B1-28)
`low_stock_threshold < 0` not rejected by the SQL CHECK on
`neon.equipment.category` — B1 constraint/fixture drift on the dev DB.
Untouched by neon_hr (equipment, not HR).

### p9m1_venue_geocode — crash
`ValidationError: The selected Room does not belong to the selected
Venue` in `commercial_job._check_room_belongs_to_venue` — venue/room
fixture drift (b1/p9). Untouched by neon_hr.

---

## Update 2026-05-30 (P-HR-R1b close)

### pb2_conflict — 34/35 (T-B2-40)
Stale literal version assertion: T-B2-40 expects `neon_jobs 17.0.5.0.0`
but B13 bumped neon_jobs to **17.0.6.0.0**. B2/B13-owned smoke (same
class as p4m2/p4m8 count assertions + phr_* version assertions). Not a
functional failure; B2/B13 to update the literal.

## Update 2026-06-01 (B4 + B5 + R3a reconciliation onto main)

### p2m7 — 16/17 (T2 dashboard "all counts 0 on empty DB")
`commercial.job.dashboard` 5-tile counts read `[3, 0, 3, 0, 5]` on
the dev DB; T2 expects all zeros because it presumes an empty DB.
Long-lived dev DB has pre-existing job / crew / cash-flow fixtures
from earlier smoke runs polluting the global state — same class as
the other p2/p6 baselined items. NOT introduced by B4 / B5 / R3a:
* B4 / B5 add NEW models (subhire / reconciliation) — don't touch
  `commercial.job.dashboard` compute methods.
* R3a inherits `commercial.job.crew` to add gate fields but the
  dashboard counts read `crew_assignment_ids` filtered by state =
  this output is unchanged.
On a fresh DB this passes. Surfaced post-reconciliation because the
reconcile-branch dev DB has been hit by every milestone fixture in
sequence (B1 → B2 → B3 → B14 → R1a → R1b → R2 → B4 → B5 → R3a). Same
remediation as the other p2/p6 baselined items: fresh-DB re-init when
fixture pollution becomes blocking.

### Dev-environment artifacts (NOT failures — future triage)
1. **Stale bind mount** — the dev container auto-restarted mid-run and
   returned on a stale Docker Desktop mount; every neon module failed
   to load (`Unmet dependencies` / `KeyError: 'neon.*'`). Fix: full
   `docker compose down && up` (not just `--force-recreate`). Any run
   with mass `KeyError` on neon models is this, not real failures.
2. **Superuser hr-grant wipe** — `neon_core_groups.xml` (noupdate="0",
   `(6,0,[...])` REPLACE) on a neon_core reload wipes the
   hr.group_hr_manager / hr_holidays_manager that neon_hr's
   `_enforce_hr_confidentiality` grants to group_neon_superuser.
   Symptom: phr_r1a/phr_r1b_1 fail with superuser AccessError on
   hr.employee. The neon_hr migration re-applies it on each version
   bump; latent risk if neon_core reloads without a neon_hr upgrade.
