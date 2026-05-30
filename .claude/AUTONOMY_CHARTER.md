# NEON BUILD — AUTONOMY CHARTER
*Standing decisions for the Claude Code build relay. Reduces gate round-trips by pre-deciding the recurring judgment calls. Lives at `.claude/AUTONOMY_CHARTER.md`; reference it at the top of every build prompt: "Charter applies."*
*Owner: Tatenda (ERP lead) · approves changes: Robin (MD). Version 1.0 · 30 May 2026.*

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

## 5. GIT & BRANCH DISCIPLINE (the debt-prevention rules)
*Added because parallel work has repeatedly generated reconciliation debt.*
- Each parallel track on its **own branch, own module** — no shared-file edits across concurrent sessions (`__manifest__.py`, `ir.model.access.csv`, `run_regression.sh` are the usual collision points).
- **Never rewrite a shared branch that carries another session's commit.** Flag it, leave the only copy intact, let the owning session relocate it.
- Prefer a clean commit on the proper branch over a surgical `checkout -- <path>` deploy artifact; when a surgical deploy is unavoidable, **log it as debt to reconcile before main-merge.**
- Before stacking a *new* parallel track on an already-multi-branch state, run a read-only branch-reconciliation diagnostic first.
- The **full combined regression** (all live modules together) runs at main-merge — that's the real integration gate; per-branch regression only partially cross-validates.

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
*Change log: v1.0 — initial charter, codifying decisions from the B1–B3 / R1a–R1b / B13 build cycle.*
