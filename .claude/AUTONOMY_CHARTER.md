# NEON BUILD — AUTONOMY CHARTER
*Standing decisions for the Claude Code build relay. Reduces gate round-trips by pre-deciding the recurring judgment calls. Lives at `.claude/AUTONOMY_CHARTER.md`; reference it at the top of every build prompt: "Charter applies."*
*Owner: Tatenda (ERP lead) · approves changes: Robin (MD). Version 1.1 · 1 June 2026.*

---

## 0. How to read this
Three tiers govern every decision in a build:
- **GREEN — decide and proceed.** Claude Code resolves these itself, inline, no gate. Just note what it did in the Gate report.
- **AMBER — decide, but surface at the gate.** Claude Code picks the charter-default and *proceeds*, but flags the choice in the Gate-1/Gate-2 report so a human can veto. No mid-flight pause.
- **RED — never decide alone. Hard stop, escalate to the human in chat.** No default, no "reasonable guess." These are the money/legal/people/safety calls.

When unsure which tier a decision is in, treat it as one tier *more* cautious than your instinct. The cost of an unnecessary flag is seconds; the cost of an unflagged wrong RED call is real.

---

## 1. RED — never decide alone (hard escalate)
These stop the build and go to the human in chat. No charter default exists on purpose.

1. **Money figures that touch real transactions** — statutory rates (PAYE/NSSA/AIDS levy/NEC), tax bands, commission %, wage/incentive amounts, penalty figures, FX rates. Build the mechanism; leave the number a flagged placeholder (`needs_finance_confirmation=True`). NEVER hard-code an unverified figure into a calculation that could run against real pay/invoices.
2. **Legal/contractual positions** — notice periods, leave entitlements/caps, anything that contradicts a signed contract (e.g. the 22-vs-72 accrual cap), employment-law rules. Flag for legal; do not pick.
3. **Who can see or do what** — RBAC grants/revokes, record-rule scope on sensitive data (salary, payroll, disciplinary, accidents, personal docs), group membership, override authority. The intent may be pre-approved; the *act* of changing who-sees-what on prod is a human sign-off every time.
4. **Destructive/irreversible prod ops** — deleting records, dropping columns, emptying data, force-pushes that rewrite shared history, anything `perm_unlink` would otherwise prevent. (Building *with* `perm_unlink=0` is GREEN; deleting is RED.)
5. **External spend** — provisioning paid API tiers, raising provider spend caps, anything that costs money. Surface the cost; the human funds it.
6. **Scope changes that alter business behaviour** — turning a flagged default into an enforced rule, changing an approval flow, auto-transitioning states that have operational meaning.

If a build *requires* a RED item to proceed, stop at the gate, state exactly what's needed and from whom (finance/legal/Robin/ops), and build everything around it as flagged-pending.

---

## 2. AMBER — decide the charter-default, flag at the gate
Proceed using the default below; report the choice so it can be vetoed.

1. **Model/architecture shape** — new model vs extend existing, where a field lives, M2O vs Selection. *Default:* extend the platform's existing model/pattern (hr.employee, hr.holidays, hr.contract, the existing Action Centre/alert mechanism, the Phase 8A encryption pattern) rather than reinventing. Reuse beats rebuild.
2. **Validator/guard strictness** — *Default:* HARD-reject anything that contradicts a Python-supplied fact; SOFT-warn on derived/narrative content the model is legitimately allowed to produce. (The B3 date-validator split is the template.)
3. **Commit splitting** — *Default:* split when a milestone exceeds ~1,800 LOC into sequential commits on the same branch; one concern per commit.
4. **Manifest version tier** — *Default:* major = new pivot model; minor = new fields/feature; patch = fix round or small additive script. Pick per the change; flag the bump.
5. **Config defaults for operational policy** (crew-call offsets, alert thresholds, accrual caps as *values*) — *Default:* implement as a configurable field seeded with a sensible default, `noupdate=1` so edits survive `-u`, and mark it pending the relevant owner's sign-off (amber banner). Never bake an operational policy as a constant.
6. **Idempotency / natural keys for loaders** — *Default:* use the existing SQL-unique constraint; reject ambiguous rows rather than guessing. Flag if real data might not satisfy it.

---

## 3. GREEN — decide and proceed, no gate
Just do these; report in the Gate summary.

1. **The whole build/test/deploy loop** — run git/docker/ssh/psql/python/pytest and all `.py`/`*smoke.py` scripts inline via the `.claude/settings.json` allow-list. Never paste a command for approval. If a needed command pattern isn't allow-listed, ADD it to `settings.json` in the same commit — don't hand over a list.
2. **Hetzner deploy through SQL-verify** (R4) — commit, push, pull, `-u`, asset flush, force-recreate, autonomously. **Pause only at SQL-verify** for the human walkthrough.
3. **Auto-commit on a clean Gate 2.**
4. **Reading anything** — prod DB (read-only), logs, code, schema, grep. Never ask permission to look.
5. **Defensive build hygiene** — `perm_unlink=0` on new models, record rules on sensitive models, typed exceptions over silent failures, lazy imports to dodge dependency cycles, batch-safe writes, fixtures that create their own data (never reuse shared records). These are expected, not decisions.
6. **Test/fixture/smoke fixes, baseline drift classification** — fix and proceed.

---

## 4. STANDING INVARIANTS (always true, every milestone)
- **Facts come from Python, never the LLM.** Quantities, dates, names, conflicts, figures — the model structures and narrates; Python supplies every fact. A generated artifact that contradicts or omits a known fact is rejected and quarantined.
- **One `-u` per prod DB at a time.** Builds may parallelize on separate modules/branches; **deploys serialize, always.** Whichever hits SQL-verify first deploys first.
- **Flagged-not-baked** for every RED-tier figure (§1.1/1.2): mechanism built, value a visible flagged placeholder.
- **No new prod data without a human.** Loaders ship with a dry-run that writes nothing + a sample fixture; the real load is a human-reviewed dry-run→execute step.
- **Surface blockers inside the gate**, under "⚠️ Decisions needed" — never as a mid-flight pause, never as a silent assumption.
- **No progress chatter.** Two outputs per milestone: Gate-1 design pause, Gate-2 report. Nothing between.
- **Sensitive records are auditable** — who/when/why on overrides, clearances, state changes; not silent boolean flips.
- **Report the locked names** (models/fields/interfaces) in every Gate-2 so the next milestone builds on reality, not assumptions.

---

## 5. PARALLEL BUILD ISOLATION (v1.1)
*Amendment to the Neon Build Autonomy Charter. Supersedes the original §5 "Git & branch discipline." Reason: three branch reconciliations in two days, every one caused by parallel build sessions sharing one working tree — not by any feature failing. This section makes the recovery discipline the default so there is no fourth.*
*Owner: Tatenda · approves changes: Robin · v1.1 · 30 May 2026.*

### 5.1 — One tree per session (hard rule)
Two build sessions MUST NOT operate on the same working tree at the same time. Parallel builds run in **separate `git worktree` trees**, one per session. The R3a recovery proved this is clean: an isolated worktree let R3a commit while B5's uncommitted work on the shared tree grew untouched.

- A session that needs the shared tree + container (for a browser gate or a `-u` deploy) **requests it explicitly**; it is handed over only when the holding session's tree is **porcelain-clean** (committed or deliberately stashed).
- Builds isolate by worktree; **deploys still serialize** — one `-u` per prod DB, whichever session reaches SQL-verify first.

### 5.2 — Never sweep uncommitted work (hard rule)
No session may **blind-auto-stash or auto-checkout away from uncommitted work** — its own or another session's. On encountering uncommitted changes when a tree-switch is needed, the session **STOPS and flags** to the relay; it never silently stashes or switches.

- This single rule would have prevented the R3a sweep *and* protected B5 in the reverse direction.
- A stash made deliberately (by the owning session, knowingly) is fine. An auto-stash triggered by a checkout the session didn't intend is forbidden.

### 5.3 — Verify fork-base at Gate 1 (hard rule)
Every build branch forks off **current `origin/main`**, and the session **reports its base SHA in the Gate-1 design pause** for confirmation. A build that discovers it is not based on current `origin/main` STOPS at Gate 1 and flags, before any work accumulates.

- The wrong-base fork (B4/B5 off the old b-line instead of reconciled `d92e71c`) is what triggered the entire third reconciliation. A one-line `git merge-base` check at Gate 1 catches it for free.

### 5.4 — Wire every smoke into the manifest at build time (hard rule)
Every new smoke (`*_smoke.py` + browser smoke) is added to `.claude/run_regression.sh` (SMOKES / BROWSER_SMOKES) **in its own commit, in the same milestone** that creates it.

- The phr_r3a `crew_ids` bug hid undetected until landing **because the smoke was never in any branch's regression manifest** until the reconcile branch wired it in. A smoke that isn't in the manifest is an untested test.

### 5.5 — Never merge a divergent branch wholesale (retained from v1.0)
Reconciliation lands work by **cherry-picking canonical SHAs onto an integration branch off main**, never `git merge`-ing a branch that carries duplicate commits. Patch-id divergence (same content, different SHA — the b9755ce / 2fbdb1e / 4fd323c class) means git will NOT auto-dedup; duplicates must be abandoned by hand. The full combined regression runs on the integration branch before the FF to main.

### 5.6 — RED-tier history operations (retained, reaffirmed)
Any history rewrite, force-push, or branch reconciliation is RED-tier: **diagnose (read-only) → propose plan → human reviews → execute to a hard pause before the irreversible step (push/FF) → human verifies the log + regression → human approves → push.** Keep a rollback anchor tag until post-push confirmation. This is the pattern all three reconciliations followed; it works — keep it.

### Standing reminder — the grant-wipe self-heal (hardening backlog, not a rule yet)
`-u neon_core`'s `noupdate=0` REPLACE wipes the OD/MD→hr_manager grant; it is only re-applied if `-u neon_hr` then fires and the migration runs (a *same-version* `-u` skips the migration, so the grant stays wiped on dev). This has bitten R1a, R2, and R3a. The durable fix is to make the neon_hr grant **self-heal on every `neon_core` upgrade** rather than depend on `-u neon_hr` ordering. Tracked for a hardening pass; not in scope of this amendment.

---

## 6. WHAT STAYS WITH THE HUMAN (the relay's job)
The charter makes Claude Code resolve *more*, not *everything*. These remain the human's, by design:
- Approving RED-tier decisions (§1).
- The SQL-verify walkthrough sign-off on each deploy.
- Sending prompts to Claude Code (the human is the relay).
- Deciding *what to build next* and *whether it's right for Neon* — the product judgment.
- Assigning people (HR Admin, leave approvers) and confirming figures (finance/legal).

The goal: the next ten milestones need far fewer round-trips because the recurring patterns are pre-decided here — while the handful of calls that genuinely need a person still get one.

---
*Change log:*
*v1.1 — §5 rewritten for worktree isolation after the B4/B5/R3a reconciliation cycle. §1–§4 (GREEN/AMBER/RED tiers, invariants) unchanged from v1.0.*
*v1.0 — initial charter, codifying decisions from the B1–B3 / R1a–R1b / B13 build cycle.*
