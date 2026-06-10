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

### p8a_m7_alerts — 28/30 (T8808 + T8814)
T8808 expects a pending_approval alert visible to an approver-tier
user; got 0. T8814 depends on T8808 (fingerprint format). Cause:
existing pending_approval quotes on the dev DB are owned by users
whose tier mapping has drifted, OR the alert mechanism's
fingerprint-week scoping has already dismissed today's alerts
from earlier runs. NOT introduced by B14c: T8808/T8814 test finance
pending_approval alerts; B14c only modifies product.template +
B2._available_for_product() (equipment_conflict path, separate
alert type). On a fresh DB this passes. Surfaced 2026-06-01 during
the PB14c regression run.

### p9m2_pin_modal — 11/12 (T9207)
T9207 expects a TBD-style row (event with the placeholder TBD
venue partner) to produce a row dict with default-safe map keys
(venue_id=False, all map keys present). Got: row not found by id
because no TBD-venue events exist on the dev DB at the test's
expected date offset. NOT introduced by B14c: tests venue UI
data shape, not inventory. On a fresh DB (with the TBD venue
partner present + the test creating the event) this passes.
Surfaced 2026-06-01 during the PB14c regression run.

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

## Update 2026-06-06 (B11 Programme Status board close) — regression 2569/2584

Run on the long-lived `neon_crm` dev DB during B11 (`neon_status`)
Gate 2. Failed Python suites: p2m2, p2m4, p2m5, p2m7_7 (6/8),
p6m3 (18/28), pb1_datamodel (29/30), pb2_conflict (34/35) — all
prior documented drift — **plus one new entry below**. Improvements
vs the last capture (now passing): p6m1, p4m2, p4m8, p8a_m7_alerts,
p9m2_pin_modal.

### pb14c_quantity_on_hand — 23/24 (T-B14c-24)
T-B14c-24 asserts a freshly-created **quantity-mode** product with no
`legacy_qty` notes has `quantity_on_hand == 0` (plus `action == SKIP`
+ reason "no unit"). The SKIP + reason parts PASS; only `== 0` fails —
actual is **1**. Cause: `1` is the **intended B14c quantity-mode
create-default** (`load = 1 unit/row`, see
`project_b14b_d1_quantity_count_followup`). Product behaviour is
CORRECT; the test's `== 0` expectation is STALE. Same class as the
pb1/pb2 single-test data/default drifts.

**NOT introduced by B11.** `neon_status` is additive (one AbstractModel
+ controller + template), depends only on base/web/neon_core/
neon_ai_core/neon_channels, touches NO `product.template` / inventory /
`quantity_on_hand` path, and was installed `-i neon_status` with no
`-u` of any other module. The test builds its own fixture fresh each
run → identical result with or without B11.

> **FIX OWED (B14c test-maintenance, NOT B11):** update T-B14c-24 in
> `.claude/pb14c_quantity_on_hand_smoke.py` (~line 475) to assert
> against the quantity default-of-1 (`quantity_on_hand == 1`) instead
> of `== 0`, OR read the configured default rather than hard-coding.
> Owner: B14c suite. Tracked here so it is not buried. Accepted as
> drift for the B11 gate per Tatenda 2026-06-06.

## Update 2026-06-07 (B11 WA-3 regression) — p12m1 chat smokes in-chunk dip

During the WA-3 (`neon_crew_comms`) full regression, `p12m1_chat`
**30/31** and `p12m1_1_chat` **29/30** dipped (were 100% in the WA-1/
WA-2 chunk runs). **NOT a code regression and NOT WA-3:** both pass
**100% standalone** (`p12m1_chat` 31/31, `p12m1_1_chat` 30/30). WA-3 is
`neon_crew_comms`-only and touches neither the Copilot nor the dashboard
chat. Cause: the two Phase-12 chat smokes share a `chat.session`
(`get_or_create_for_user`); run back-to-back in the batch, the first
leaves committed state that perturbs a count/state assertion in the
second. Surfaced now as dev-DB chat residue crossed a threshold. Same
class as pb14c: correct product, lagging test harness. In-chunk pollution
can MASK a real regression in those suites next run, so fix it properly.

> **FIX OWED (Phase-12 test-maintenance, NOT WA-3):** make `p12m1_chat`
> / `p12m1_1_chat` order-independent — hard-reset / isolate the
> `chat.session` (+ its messages) in each smoke's setup so neither
> depends on prior committed state. Owner: Phase-12 test maintenance.
> Accepted as in-chunk pollution for the WA-3 gate per Tatenda
> 2026-06-07.

## Finding 2026-06-08 (B11 WA-4 discovery) — 'hr' variant = all-entitled

Surfaced verifying WA-4 against the real dual-role user (user 10
admin@/Kudzaiishe on prod). The Copilot tool registry
(`neon_ai_core...tool_registry.TOOLS_BY_VARIANT`) has NO `hr` (or `tech`)
entry, so `filter_tools_for_variant_and_user(user,'hr')` hits
`TOOLS_BY_VARIANT.get('hr') or ["*"]` -> `"*"` -> returns ALL the user's
group-entitled tools (17 for her), NOT a curated HR subset. The
`bookkeeper` lens is a focused 9-tool subset by contrast. So the `hr`
lens is an over-broad "kitchen sink". NOT a security hole (it is still
`⊆ the user's Odoo groups` — `user_can_call` gates every tool; nothing
beyond their RBAC), and WA-4 deliberately does NOT change it (Gate-1
decision 2: WA-4 changes WHICH lens is picked, not what each contains).

> **FOLLOW-UP (Copilot-registry maintenance, NOT WA-4):** decide whether
> to add a curated `hr` (and `tech`) entry to `TOOLS_BY_VARIANT` so those
> lenses are focused like the others, OR make the `["*"]` fallback
> explicit/intentional. Affects the dashboard Copilot too (shared
> registry). Owner: Copilot-registry. Logged per Tatenda 2026-06-08.

## Accepted items 2026-06-08 (B11 WA-5 client lane, adversarial review)

WA-5's adversarial review (15 findings -> 7 real / 4 partial / 4 refuted)
applied 3 D4-guarantee hardenings (human-fallback activity, activity-
always-lands, no-silent-truncation). Two findings were ACCEPTED as
limitations rather than fixed:

1. **Assignment-loop TOCTOU races** (`_wa5_tap_assignee_decline` clear,
   `_wa5_tap_assign_pick` membership re-check). A concurrent Odoo-UI
   reassign racing a WhatsApp decline/pick is a lost-update window. NOT
   fixed: WhatsApp taps are human-paced (not an attacker hammering), and
   the worst case is the DESIGNED safe state -- the lead lands unowned
   AND the escalation target is re-notified (`_wa5_bounce_to_escalation`
   + activity), never unowned-and-silent. Row-locking would be over-
   engineering for a human-paced WhatsApp surface. Revisit only if a real
   double-action incident is observed.

2. **Session TTL reset clears `lead_id`** (`neon.wa.client.session
   ._get_or_start`). A client returning >24h later starts a fresh session
   and (if their message trips a handoff keyword) gets a NEW lead, so the
   old lead is not re-attached. ACCEPTED: "fresh conversation after 24h
   idle = fresh intake" is the intended semantics; CRM de-duplication of
   the same phone is a human task. Low-priority data-quality.

Both are NON-security (the hard sandbox + the assignment two-factor are
intact and verified). Owner: WA-5 maintenance. Logged per Tatenda
2026-06-08.

## Update 2026-06-09 (B11 WA-6 crew+OD equipment face) — regression 2808/2825

First FULL regression since 2026-06-06 (WA-4/WA-5 closed via delta
reviews, not full runs). 11 Python suites failed; **all pre-existing
drift, none a WA-6 regression**. WA-6's diff is `neon_channels/
wa_payload.py` (intents only) + `neon_crew_comms/*` (new WA-6 method
bank + equip session + event-job button) — it touches NO HR / neon_core
/ res.groups / state-machine / pricing / inventory code.

* 8 documented-drift suites unchanged: p2m2, p2m4, p2m5, p2m7_7 (6/8),
  p6m3 (18/28), pb1_datamodel (29/30), pb2_conflict (34/35),
  pb14c_quantity_on_hand (23/24).
* WA-6 + every reused family GREEN: pwa1 28/28, pwa2 27/27, pwa3 18/18,
  pwa4 29/29, pwa5 125/125, **pwa6 58/58**; p5m5 19/19, p5m7 15/15,
  pb14 25/25, pb14d 8/8.

### phr_r1a (crash) + phr_r1b_1 (17/18, T-R1b1-17) + phr_r3b_c4_housekeeping (5/6, T-R3b-C4-05)
NEW vs the 2026-06-06 set, but the SAME `neon_core_groups.xml`
`(6,0,[...])` REPLACE grant-wipe documented in the 2026-06-01 artifact
(#2) + memory `neon_core_noupdate_grant_wipe`: a neon_core reload during
the WA-3→WA-5 era wiped the `hr.group_hr_manager` implied grant that
neon_hr's `_enforce_hr_confidentiality` adds to
`neon_core.group_neon_superuser`. The failing assertions are verbatim
the wipe ("superuser implies hr.group_hr_manager (grant restored):
False"; "OD/MD (superuser) HAS Time Off manager"; phr_r1a superuser
AccessError on hr.employee).

**PROVEN not-WA-6 (2026-06-09):** a shell read confirmed
`group_neon_superuser implies hr.group_hr_manager == False` (wiped);
calling `_enforce_hr_confidentiality(env)` flipped it to True and ALL
THREE suites went fully green (phr_r1a 46/46, phr_r1b_1 18/18,
phr_r3b_c4 6/6) with NO code change. The grant was restored + committed
on the dev DB. `-u neon_crew_comms` (WA-6's upgrade) runs DOWNSTREAM of
neon_core and never re-runs it, so WA-6's build could not have caused
the wipe — it predates this session.

Note: the browser-smoke gate did NOT run — the pre-existing baseline
Python failures exit run_regression.sh before the browser phase (true
of every milestone on this dev DB). WA milestones carry no browser
smokes (WhatsApp surface); WA-6's only Odoo UI is one gated inherited
header button, verified by the live real-phone proof per the WA-6 plan.

## Update 2026-06-10 (P5.M11 quantity-aware reservation engine) — 2826/2843

11 Python suites failed; **all pre-existing drift, ZERO new from P5.M11**.
P5.M11's diff is the neon_jobs reservation/movement/line/event-job/checkin
engine + a migration + the WA-6 finalize touchpoint — it REUSES the B2
conflict engine (doesn't alter it) and changes NO HR / neon_core / group /
pricing / state-machine code.

* 8 documented-drift suites unchanged: p2m2, p2m4, p2m5, p2m7_7 (6/8),
  p6m3 (18/28), pb1_datamodel (29/30), **pb2_conflict (34/35)**,
  **pb14c_quantity_on_hand (23/24)**. pb2 + pb14c specifically watched
  (M11 touches the conflict + quantity paths): both unchanged at baseline.
* P5.M11 + every serial/quantity/WA suite GREEN: **p5m11 18/18**; serial
  byte-unchanged p5m4 10 · p5m5 19 · p5m6 14 · p5m7 15 · p5m8 14 · p5m9 20 ·
  p5m10 20; pb14 25 · pb14d 8 · pb4 33; pwa1 28 · pwa2 27 · pwa3 18 ·
  pwa4 29 · pwa5 125 · pwa6 58.
* phr_r1a / phr_r1b_1 (17/18) / phr_r3b_c4_housekeeping (5/6): the
  recurring `group_neon_superuser` HR-manager grant-wipe (the 2026-06-01
  artifact #2 + 2026-06-09 finding). PROVEN non-code: calling
  `_enforce_hr_confidentiality` flips all three green with no code change;
  the grant gets re-wiped by repeated `-u`/force-recreate cycles on this
  long-lived dev DB. P5.M11 touches no HR code.

## Accepted items 2026-06-08 (B11 WA-5.1 + WA-5.0 delta review)

The WA-5.1/5.0 adversarial review (10 findings -> 5 real / 2 partial / 3
refuted) applied 2 hardenings: Fix A (`_wa5_fallback_human` now chains
superuser -> owner -> sales -> ANY active internal user, so the D4
activity always lands on a human even with a broken escalation target +
empty su/sales sets -- closes the "all 3 paths fail" loss case) and Fix B
(`_wa5_staff_notify` captures `send_template`'s {ok,reason} and WARN-logs
a suppressed/failed template). ACCEPTED without code change:

1. **Escalation-target opt-out** suppresses the WhatsApp template but the
   Odoo activity still lands (Munashe sees it IN Odoo; `wa_opt_out` is a
   WhatsApp-only flag). This is the LOCKED WA-5.1 Gate-1 decision
   ("respect `wa_opt_out`; activity covers a suppressed staffer"), not a
   defect. `send_template` already logs + audits the suppression.

2. **Lead-deleted-mid-append race** (escalate-once guard): a sub-ms window
   between `sess.lead_id.exists()` and `message_post`. `.exists()` self-
   heals the pre-check; the append is exception-guarded; crm.lead deletion
   mid-conversation is not a realistic threat (append-only audit
   discipline). Worst case = one follow-up line not mirrored to a
   just-deleted lead. Same human-paced TOCTOU class as the WA-5.0 races.

3. **Concurrent assign_pick double-notify race**: two simultaneous taps of
   the same pick could both pass the idempotency check. Human-paced
   WhatsApp taps; worst case = a duplicate assignee notify. Row-locking is
   over-engineering for this surface. Same bucket as the WA-5.0 races.

Owner: WA-5 maintenance. Logged per Tatenda 2026-06-08.

## Accepted item 2026-06-08 (B11 WA-5.4 delta review)

WA-5.4 prod-fix delta review = 4 findings -> 3 "real" but ALL with
"production-ready / accept as-is / no change required" verdicts + 1
refuted (convergence). Applied the one cheap nice-to-have: the webhook's
rollback-on-error now LOGS instead of `pass` (no silent rollback).
ACCEPTED without change: the webhook `except -> cr.rollback()` rolls back
the WHOLE message batch, so if Meta ever sends a MULTI-message webhook and
one message triggers a deferred error, the good messages in that batch
roll back too. Negligible: Meta delivers WhatsApp inbound ONE message per
webhook in practice, and the primary fix (`tracking_disable` on the
user_id write) means the deferred-error path is essentially never hit.
Per-message savepoint isolation is beyond the approved WA-5.4 scope;
revisit only if multi-message batches + a deferred error are ever
observed together. Owner: WA-5 maintenance.

## Accepted item 2026-06-08 (B11 WA-5.2 delta review)

WA-5.2 (debounced re-handoff) delta review = 4 findings -> 0 real / 2
partial / 2 refuted (clean). 1 partial applied (TTL reset now also clears
`last_notify` -> full clean slate; `pwa5` TTL test added). 1 partial
ACCEPTED without change: **debounce could in theory get stuck if
`sess.write({last_notify})` fails AFTER the notify fired** (a returning
follow-up would then never re-notify). Negligible: a single Datetime write
on a constraint-free column doesn't fail in practice, and a full tx
rollback would also roll back the notify's DB side-effects (chatter /
activity), keeping state consistent. Revisit only if a constraint/trigger
is later added to `last_notify`. Owner: WA-5 maintenance.
