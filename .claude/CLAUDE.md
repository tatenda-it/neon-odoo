# Neon-Odoo Project Context

This file is auto-loaded into every Claude Code prompt for the neon-odoo 
repo. It captures invariants that apply across all milestones. For 
milestone-specific procedural steps, see 
`.claude/skills/milestone-pattern/SKILL.md`.

## Project basics

- Repo: neon-odoo (custom Odoo 17 addons for Neon Events Elements)
- Currently in Phase 6 (Finance Module full rebuild)
- Main developer: Tatenda Loyd (Sales Rep + Developer)
- Production server: Hetzner, crm.neonhiring.com
- Phase 5 LIVE; Phase 6 local-only until P6.M12 deploy

## Who's who & roles

- **Munashe Goneso** — Managing Director (MD).
- **Robin Goneso** — Operations Director (OD). Munashe and Robin have
  **equal system permissions** (family business; Goneso is the shared
  surname).
- **Tatenda Ngairongwe** (`tatenda@neonhiring.co.zw`, GitHub `tatenda-it`)
  — Sales Rep + Developer; drives the build. No finance responsibilities.
- **Kudzaiishe** — Bookkeeper, login `admin@neonhiring.co.zw` (her work
  address, NOT the Odoo superuser account; that drift was cleaned in
  P6.M12). Only dual-role user in prod (Bookkeeper + HR Admin).
- **Lisa, Evrill** — Sales Representatives (Lisa has no workshop authority).
- **Lead Tech — POSITION ABOLISHED company-wide (Robin, 2026-07-02).**
  Decisions that went to Lead Tech now route to **Robin (Operations)**.
  Previous holder `ranganai@neonhiring.co.zw` was offboarded 2026-07-02
  (user 13 deactivated, Lead-Tech/Training groups stripped, WhatsApp
  bot.user 7 deactivated, hr.employee 14 archived, EVT-000001 lead_tech
  cleared, neon_core grant-map entry emptied; ALL history preserved —
  wages/job-history/authored docs stay archived per the append-only
  discipline). System echoes of the role (lead_tech_id field, Event Jobs
  LEAD TECH column, "Set Lead Tech" create-activity, `crew_leader` WA role
  concept, dashboard tier + cost-line record rule keyed on the group) are
  a NAMED BACKLOG ITEM to retire/repoint in a future pass — needs its own
  GATE-0. Crew Chief stays a per-event role (`is_crew_chief` flag),
  unrelated to the abolished standing role.

## Two-station collaboration & git rhythm

This repo is worked from **two equal stations — Tatenda's and Robin's**.
Both commit and deploy to production the same way; the Autonomy amendment's
gates apply equally to whoever is driving. The remote is the single source
of truth.

- **`git pull` when you sit down**; **`git push` when you stand up**
  (before stepping away).
- **Deploy to prod ONE AT A TIME.** Only one station deploys at any moment.
  Before deploying: pull latest, confirm the other person isn't mid-deploy
  (a quick "deploying now" between the two humans suffices), deploy, and let
  it finish completely before the other station starts. The per-action
  gates stop *bad* changes; this rule stops *two good changes colliding* —
  both are required.
- **Prefer separate feature branches** so the two stations aren't editing
  the same files at once; merge to main when ready.
- Commits are authored as **`tatenda-it`** even when the AI session is
  logged in under a different Anthropic account — the Anthropic login pays
  for the tool; the git identity is whose name lands on history.

## Two-gate approval pattern

Every milestone has exactly two human approval gates:

1. **Design pause** (after discovery, before code)
2. **Commit approval** (after all tests pass)

Between gates: autonomous execution. Mid-build judgment → ⚠️ DECISION 
markers in code + diff summary. No mid-build pauses except hard stops.

**Hard stops**: Python test failure, browser smoke failure, discovery 
reveals invalid design assumption, schema redesign needed. On hard stop: 
STOP → diagnose → report symptom + root cause + 3 fix options → await 
direction.

## Within-gate autonomy

The two-gate model defines WHERE Tatenda's approval is required:
- Gate 1: Design review before code. Required.
- Gate 2: Build complete report. Required if anything non-routine 
  surfaced. AUTO-COMMIT if clean.

Between gates, Claude Code operates autonomously. Do not ask 
"should I proceed" or "ready to commit?" at every checkpoint.

### What "auto-commit" means at Gate 2

When the gate-2 report would say:
- Build matches gate-1 plan (no scope creep)
- All planned tests PASS
- JSON-RPC probe drift unchanged
- Any new ⚠️ DECISIONS surfaced ARE defensible build-time 
  adaptations (not architectural pivots)
- Known-noise regressions unchanged from baseline

Then: commit per gate-1's locked commit message + push + report 
outcome. No "awaiting commit approval" pause.

### What PAUSES Gate 2 (gate fires, Tatenda must respond)

- Any planned test FAILS
- A ⚠️ DECISION is genuinely architectural (e.g. data-model 
  reshape, RBAC change, new dependency)
- JSON-RPC probe drift surfaces ANY regression
- LOC budget overshoots gate-1 estimate by >30%
- Scope creep detected (work done that wasn't in gate-1 plan)
- Pre-existing test moves from passing to failing
- Any deploy-blocking finding

When any of these fire, surface and wait. Otherwise: commit + 
report + move on.

### Within a milestone (between gates 1 and 2)

Routine operational decisions are Claude Code's call:
- Which file order to write models in
- Whether to refactor a helper while you're touching it
- Running additional ad-hoc tests for confidence
- Picking field types within the gate-1 spec
- Selector strategies for browser smoke
- XML namespace ordering
- Variable naming
- Whether to use a list or dict comprehension

Do not ask Tatenda for permission on these. Decide and proceed. 
Surface decisions in the gate-2 report retrospectively.

### Across milestones

When M_N gate-2 closes cleanly with auto-commit, the next 
milestone's gate-1 prompt is Tatenda's responsibility to draft 
and send. Claude Code does NOT auto-start M_{N+1}. Each 
milestone begins with an explicit Tatenda prompt.

This boundary is hard. No "shall I start M2?" — wait for the 
M2 prompt.

### Process change rationale

Through Phase 6's 11 functional milestones, Tatenda's gate-2 
response was "approved, commit" 11/11 times when the build was 
clean. The "may I commit" question added friction without 
adding signal. Phase 7a forward: trust gate-1 approval, commit 
autonomously on clean gate-2, only pause when something real 
surfaces.

Source: Tatenda direction 20 May 2026, after P7a.M1 gate-2 
showed clean results and the "awaiting commit approval" 
question added no value.

## Audit-trail discipline

ALL Phase 6 financial models use append-only ACLs: `perm_unlink = 0` 
for every group on every financial model. Corrections via new records 
with later effective_date or cancelled state, never deletion.

Models under this rule: pricing.rule, pricing.bracket, day.multiplier, 
conversion.rate, quote, quote.line, payment.term, cost.line, approval, 
plus future payment + invoice models.

## Browser smoke depth principle

For every menu the smoke verifies as visible: assert visible, click into 
the action, assert at least one piece of content (row count, cell value, 
form opens, badge state). Menu-visibility alone catches ~75% of bugs; 
depth principle catches ~100%.

## Test fixtures

The 8 p2m75_* users are persistent via get-or-create:
- p2m75_sales, p2m75_mgr, p2m75_lead, p2m75_crew, p2m75_other
- p2m75_t20 (throwaway slot from T20 constraint test)
- p2m75_book (Bookkeeper), p2m75_approver (Approver) — added P6.M2/M4

Password `test123` baked into seed. user_ids stable across regression 
cycles. NEVER touch res_users.unlink in setup. Manual UI group grants 
do NOT survive setUp (baseline enforcement). To add a new role for 
testing, ADD a fixture — don't mutate existing ones.

## Manifest versioning

`17.0.<phase>.<minor>.<patch>`

- **Phase era (major)**: new phase OR new central pivot model
- **Minor**: engine wiring, extensions, new layers
- **Patch**: fix rounds within a milestone

## Odoo 17 gotchas

### Routing
`/odoo` and `/odoo/action-...` fall through to website 404. Use `/web` 
and `/web#action=<numeric_id>`.

### Instance methods via RPC
`ir.ui.menu.load_web_menus(self, debug)` is NOT `@api.model`. `call_kw` 
requires `args=[[], False]` (empty recordset + debug flag).

### Security records with `noupdate=1`
Don't propagate `implied_ids` changes on existing installs via `-u` 
alone. Required pattern: migration script with 
`write({'implied_ids': [(4, id)]})` PLUS manifest version bump. Use 
`(4, id)` idempotent add, `(3, id)` defensive remove.

### Odoo account group XML id labels lie
- `account.group_account_invoice` has LABEL "Billing" (basic user)
- `account.group_account_manager` has LABEL "Billing Administrator"
- `account.group_account_user` has LABEL "Accountant"

Never match XML ids by label. Always verify via `res.groups` search.

### Cross-module menu coordination
When module A narrows a shared menu via `(6, 0, [...])` REPLACE, module 
B extending the same menu must use `(4, ref(...))` ADD. Load order must 
respect dependencies (B depends on A).

### Compute chains bypass write()
Stored-computed-field updates do NOT fire `model.write()`. If you need 
behavior on compute update: put it INSIDE the compute method, not in 
write(). Use direct SQL read of prior stored value for change detection 
(avoids ORM cache recursion).

### SQL underscore is a wildcard
`LIKE 'p2m7_'` matches both `'p2m7_'` AND `'p2m75_'`. Use Python 
`startswith()` or Odoo `=like` with escape for prefix cleanup.

### sudo() in computed reads
When a compute on an operational model (event_job, etc.) reads finance-
side models (quote, cost.line, etc.), operational-tier users may lack 
ACL on the finance model. Use `record.sudo()` inside the compute. 
Scopes escalation to that single read; preserves requesting user 
identity.

## Cross-module ACL pattern

When a finance role needs read access on an operational model (e.g. 
Bookkeeper reading event_job for P&L tab), add a row to 
`addons/neon_finance/security/ir.model.access.csv` for the cross-module 
model. `perm_unlink=0` always.

## When the spec is wrong

If the Schema Sketch or design pause spec contains an assumption about 
Odoo that turns out to be wrong (write() firing on stored-compute, etc.), 
THE IMPLEMENTATION TAKES PRECEDENCE. Document with ⚠️ marker:
- What the spec said
- What Odoo actually does
- The corrected mechanism

Don't bend the implementation to match a wrong spec. Bend the spec.

## Anti-patterns (do NOT do)

- Auto-approve action stubs without ⚠️ marker
- Skipping the design pause to "save time"
- Modifying res.users records on every smoke run
- Granting permissions via implied_ids without migration script
- Using `(6, 0, [...])` REPLACE on shared menus that other modules extend
- Reading finance-side models from operational paths without sudo()
- Tests asserting against implementation output (must assert against spec)
- Force-recreating containers without `-u <module>` first
- Committing without browser smoke verification

## Polish backlog discipline

When a real issue surfaces that's not blocking the current milestone:
1. Mark with ⚠️ in the diff summary
2. Add to `project_phase6_status.md` polish backlog with severity 
   (LOW/MEDIUM/HIGH), milestone that surfaced it, fix description, 
   and target timing

No hidden technical debt — every "I'll fix that later" becomes a named 
backlog item.

## Build ritual (self-managed — surface to the human ONLY at the marked gates)

### Gates
- GATE-0 (discovery): before any plan, read the real code/data — never design from memory. Report findings.
- GATE-1 (scope): plan = files touched + data-model changes + test list + migration (if any) + manifest bumps.
  ⛔ HUMAN GATE — wait for approval before building.
- BUILD: build exactly to the approved plan. Flag (don't silently add) anything outside scope.
- GATE-2 (report): footprint table, new-suite results, FULL regression vs the baseline file (any new
  failure = stop), the ⚠️ decisions made during build.
  ⛔ HUMAN GATE — wait for approval before commit/deploy.

### Hard rules (non-negotiable, encode in every build)
- Gate on XML ids via has_group(), NEVER numeric group ids (install-order drift).
- All writes run as the real acting user (resolved phone→bot.user→res.users); bare sudo poisons actor_id.
- New WA intents must be added to wa_payload.INTENTS or encode raises.
- Advisory locks: fresh namespace per feature, never reuse.
- Tests must exercise the REAL dispatch path (command→list→pick→receive→tap), never synthesised payloads
  alone. A handler isn't a feature until something reaches it.
- Tight command parsers: equals/startswith on a small set, never substring; include a false-positive test.

### Deploy ritual
- Sequence: commit (report sha) → prod git pull → [migration? dry-run on prod first, print row list,
  ⛔ HUMAN GATE on the rows] → -u <modules> (one process) → ONE force-recreate.
- The force-recreate is the real switch (module-level Python is in-worker memory; -u alone serves stale).
  Confirm uptime reset — a swallowed recreate looks deployed but isn't.
- Never two force-recreates simultaneously.
- Bump every module whose .py changed, even registry-only (version checks must read true).
- Post-deploy: report versions + ledger deltas for the human's independent read-only verification.

### Record-keeping
- After each milestone: append to the journal (what/why/sha/versions), update MEMORY.md (keep under size
  limit — trim oldest detail, keep decisions), update the status board honestly (in-verification ≠ done;
  done only after the real-phone/real-path proof passes).
- Test fixtures: [TEST-*] name prefix, only test handsets, teardown after proof, ledger back to baseline.

## Autonomy amendment (supersedes earlier gate behaviour where they conflict)

DEFAULT = DECIDE, LOG, PROCEED. Do not ask the human anything that is not a HARD GATE below.
For every judgment call (scope cuts, naming, vocabulary, test depth, version bumps, file layout,
pattern choices), decide it yourself using: (1) precedent in this repo and its memory files,
(2) the established patterns (list-then-pick, tight parsers, two-factor, real-path tests),
(3) the safest reversible option. Record each decision in a DECISIONS section of the next report.
Decisions are surfaced for visibility, not approval — proceed without waiting.

This collapses the former GATE-1 and GATE-2 pauses: plan → build → test → commit → deploy → verify
runs end-to-end unattended when the SAFE-DEPLOY criteria hold:
- no migration touching existing rows
- nothing sent to any real (non-test) phone; only [TEST-*] fixtures and the approved test handsets
- no money-adjacent behaviour
- zero new regression failures vs the baseline file
- footprint within the scoped modules; any cross-module registry touch handled per the deploy ritual
  (-u all changed modules + ONE force-recreate, uptime confirmed)
Post-deploy, report versions + ledger deltas for read-only verification; an anomaly = stop + surface.

⛔ HARD GATES — the ONLY things that wait for human approval:
1. MIGRATIONS that modify existing live rows → present the exact pre-apply row list, wait.
2. REAL-PHONE / EXTERNAL SENDS → anything that messages a non-test phone (real crew, clients,
   broadcasts), submits to Meta, or changes templates → wait.
3. MONEY → anything that could move, promise, quote, or display money over WhatsApp → wait
   (standing rule: this is walled off; surfacing it is itself exceptional).
4. IRREVERSIBLE / DESTRUCTIVE → deleting non-[TEST-*] data, force-push, history rewrites,
   merging to main, dropping columns/tables → wait.
5. NEW ACCESS POWER → granting any role/group a capability class it did not already hold
   (a new face for an existing holder = decide; letting a NEW class of user act = gate).
Everything not listed is yours to decide.

When a hard gate is reached: present it in one compact block (what / why / exact blast radius /
recommendation), then HOLD only on that item — continue any queued work that doesn't depend on it.

## Prod writes & post-deploy verification (supersedes the earlier ssh-only post-deploy rule)

Prod writes via ANY surface (ssh, JSON-RPC, API) follow the same rules as deploys: [TEST-*] fixtures
and approved teardowns are within autonomy; anything touching non-test live rows is hard gate 1/4
regardless of transport. Post-deploy verification: do NOT ssh or JSON-RPC prod for read-only checks —
report what should be verified (versions, fields, ledger deltas, expected states) and the assistant
verifies via the browser. SSH/RPC to prod is for deploy actions and approved fixture/teardown work only.
