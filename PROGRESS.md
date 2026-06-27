# Neon ERP — Progress Log & Open Issues

Working record between deploys. The polished programme narrative lives on the live board (`/neon/status`); this file is the working log — what was done, what was decided, what's open, and known issues to review with Tatenda. When something here is resolved or deployed, fold it into the board and tidy this file.

---

## Session — 27 June 2026 (Robin, chat/advisory + Claude Code)

### Done (all LOCAL, nothing pushed; branch `feat/wa6-equipment-face`, ahead 3 of origin)

- **`neon_base` cold-install shim committed** (`fafd203`). Pre-declares `neon_core.group_neon_superuser` via post_init_hook so it loads before `neon_jobs`, breaking the circular group dependency on a cold install. Verified unmasked on a true cold install. Includes the one-line `neon_jobs` depends wiring (inseparable from the shim). **Not on prod.** Prod deploy is a separate gated GO with load-order audit + on-prod smoke.
- **`neon_training` typo fix committed** (`87a8b77`). `validity_months` → `default_validity_months` on the Safety cert category (value 24). Flagged in the commit body for checking against main/prod's deploy path — it's a latent cold-install bug.
- **System map committed** (`062e15e`) at `docs/NEON_ERP_MAP.md` — full module/dependency/cold-install reference, prod module-state verified via browser ORM check.

### Held / not committed (intentional)

- `addons/neon_banking_labels/__manifest__.py` — the `neon_finance` + `neon_core` depends edit needed for local cold install. Left uncommitted and flagged for Tatenda.

### Decisions taken

- **Cold-install circular dependency → fixed via "Option 3" (`neon_base` shim)**, not by deleting the 16 superuser ACL/view references. Rationale: deleting access references on a static "it's redundant via implied_ids" reading risks the role-separation model; the shim preserves every grant exactly as written. Low-regret.
- **Cold-install hardening of `neon_training` (and any further latent cold bugs) deferred to Tatenda / a joint audit** — not patched ad hoc solo. The local sandbox is unblocked via local-only seeding that touches no committed source.
- **Sales-enablement / onboarding work reframed** as the adoption half of Phase 11 cutover, not a separate programme. (See below.)

### Verified facts

- **All 28 tracked `neon_*` modules are `installed` on prod** (browser ORM `ir.module.module` state check, 27 Jun). `neon_base` is the only module not on prod.

---

## Open issues — for review with Tatenda

1. **Banking modules: "DEV ONLY, no prod" commit tags vs actual `installed` state on prod.** The banking Builds (`neon_banking_labels`, `neon_banking_statement`, `neon_bank_import`, `neon_mis_reports`, `neon_weekly_budget`) and UI-shell modules are tagged DEV-ONLY in commit history but are `installed` on prod. Either deployed-after-tagging (stale history), installed-but-not-exposed, or an unintended deploy. **"What we think we deployed" and "what's installed" have diverged in the record.** Needs a reconcile.
2. **The `/neon/status` board narrative has drifted from prod reality.** It doesn't track the banking modules as a live track (they're live), and doesn't yet include the sales-enablement/onboarding work. Board narrative is hardcoded Python constants in `neon_status` — updating it is a code change + gated deploy.
3. **`neon_training` carries cold-install debt** beyond the one typo fixed: a menu load-order forward-reference (wizard view at manifest pos 25 references `menu_neon_training_root` defined at pos 26). Masked on warm upgrades; breaks cold installs / disaster recovery / clean rebuilds. Worth a proper cold-install hardening pass on the module.
4. **`neon_crew_comms` manifest version (17.0.1.21.4) lags its actual WA-12/13 feature set** — version-bump audit before its next deploy.
5. **Prod chart of accounts not confirmed.** The dev sandbox uses the generic v17 chart; prod uses whatever was applied at original install. Confirm before any tax/VAT/fiscal-bridge work.
6. **Future build — "logistics confirmed before quote sent" system gate + AI reminder.** Make confirming and adding the LOGISTICS line a real gate in the quote flow (a quote can't be sent without logistics confirmed), backed by an AI reminder bot that tracks and nudges. Currently a discipline that's sometimes missed; wanted as enforced. Separate `neon_finance` / AI build, scoped later. (Surfaced by the Sales cutover course B4a.) **Also needs a WhatsApp connection** to manage/surface the gate and reminders over WhatsApp (not just in-app).

---

## Sales-management build backlog

From the read-only sales-management oversight discovery (what a sales line-manager needs to oversee a team and coach off data — gaps the system does not surface today). For the Director (MD) onboarding track and post-cutover builds.

1. **Live per-rep performance dashboard** — pipeline / win rate / conversion / activity **by rep, side-by-side, on LIVE post-cutover data**. Today the only per-rep cut is historical (from the Zoho archive). **Biggest gap for a coaching manager.**
2. **Rebuild the per-rep intelligence boards on LIVE data** — Win/Loss, Client Intel, Demand are currently **archive-only / historical**; they won't reflect post-July performance until rebuilt on live Odoo records.
3. **First-response SLA fixes** — align to the agreed **2-hour** standard (already 2h in system — confirm); make it **forward-looking** (flag still-open, unanswered leads, not just retroactive once a late response lands); and add a **manager rollup / per-rep breach view** (none today — breach is a per-lead ribbon only).
4. **"Copy Munashe on all client emails" compliance** — currently **unmonitored / honour-system**; needs a tracking mechanism, **likely including a WhatsApp connection** to manage/surface it.
5. **Team follow-up compliance rollup** — the follow-up/stuck-deal crons nudge individuals, but there's **no per-rep manager view** of who's behind on follow-ups / breached SLA / stale quotes.

*(Item 6 — the logistics-confirmed-before-quote gate + AI reminder — is open-issue #6 above, now noted to also need the WhatsApp connection.)*

---

## Cutover courses — pre-publish gates

Both cutover courses (`neon_cutover_courses`) are built and seeded **UNPUBLISHED**. Finance is walkthrough-verified / deploy-ready; Sales must clear all items below before it publishes.

**Cutover — Sales — pre-publish items (all must clear first):**
1. **Rep-screen verification** — confirm A2 + B1–B6 against a real sales-rep session (Lisa/Evril or screen-share). Drafted from the director/superuser view, so the actual rep-facing screens are unconfirmed.
2. **Munashe's discount threshold** — confirm the live figure, then fill it into B6 / C2 / Q4 (currently "above the threshold", no number).
3. **Response standard 1h → 2h** — the built Sales seed (`data/cutover_sales_course.xml`) currently says **"1 hour"** in C1 and Q5; change to **"2 hours"** to match the system's actual SLA (2h) and the agreed standard. *(Seed not yet edited — logged here as a pre-publish fix only.)*

**Cutover — Finance:** verified against the live walkthrough; deploy-ready pending the gated deploy + director review/publish.

---

## Active priority — team onboarding / adoption (Phase 11 cutover, adoption half)

**The problem (in plain terms):** The team is not yet onboarded onto the live ERP. The system is built and live; the people are not on it. Need a low-friction, reliable path to get current staff logged in, competent in their actual daily tasks, and re-grounded in company culture/expectations — fast — then a repeatable version for future hires. This is the adoption half of Phase 11, not a separate programme.

**Hard constraint:** Finance + Sales cut over **1 July 2026**.

**Rollout order:** Sales + Finance first → Munashe (director) → Tech Crew last. (Driven by cutover sequence. Tatenda, who is *building* the system, becomes the first "sales hire" trained *through* this method once live — a useful real-world test that it works for someone who didn't build it.)

**Gating intent:** mandatory / blocking full role orientation before users start operating — but see the dual-path decision below, because a *broken* blocking gate stops cutover rather than smoothing it.

**Specific people / needs:** Munashe needs to learn a system she hasn't been building. Kudzaiishe (Finance) is exploring it but needs structured help. Lisa/Evril (Sales) not yet onboarded.

### Two-path approach (decided 27 Jun)

- **Primary / safety net for 1 July — lightweight, reliable path.** Per-role guided walkthrough + checklist, delivered via the *existing, live, proven* `neon_lms`. Low-tech, can't break, guarantees Finance + Sales cut over on time. This is the redundancy — it is never blocked on the trainer.
- **Attempt / proper version — the in-system trainer (`neon_sales_onboarding`).** Fixed, tested against the real DOM, eventually extended to Finance + culture content and made blocking. Realistic 4-day target is *"fixed + tested locally, Sales modules working, ready to deploy — optionally turned on for Sales if genuinely solid."* Finance content, culture content, and the blocking gate come *after* cutover. Crew rollout + future hires are its real home. **Never the thing standing between a user and the system on 1 July** — the lightweight path always carries cutover if the trainer isn't ready.

### The `neon_sales_onboarding` addon — known issues (from code read, 27 Jun)

Pre-written 22-file Odoo 17 addon (3 models, 7 seeded modules, OWL overlay, systray, manager dashboard, LMS hook, own-progress row security). Sound structure, but **not yet installed anywhere live** and carrying:
1. **Missing cron method** — `cron_data.xml` calls `_cron_check_overdue_onboarding()` which doesn't exist. Disabled (`active=False`) so harmless until toggled; crashes if enabled. [Decision pending: implement the ~15-line nudge method, or strip the cron.]
2. **`/odoo` → `/web` bug** — controller redirect + seeded `target_url`s use `/odoo...`, which 404s on this build. Needs a verified sweep to `/web` equivalents (not blind replace — the dashboard action needs its real target).
3. **Unverified DOM selectors** — steps target guessed selectors (`a.o_menu_entry:contains('Dashboard')` etc.). Must be corrected against the live rendered DOM (the handover note's own "most likely to break" item). This is browser-walkthrough work, not a desk fix.
4. Sales-only target groups; no Finance content; no culture content yet.

### Reuse available (for the proper trainer + future roleplay/coaching)

- `neon_lms` — already has a **`practical.scenario` + `scenario.completion`** pattern (built for crew) — closest existing analogue to roleplay/scenario practice. Plus tracks/modules/quizzes/certs.
- `neon_ai_core` — department-neutral chat orchestrator + tool registry + two-phase write guard (for future AI coaching). Note: chat path is **Groq + Gemini**, not Claude.
- `neon_crm_extensions` — lead scoring/SLA/data.
- `neon_training` — cert/competency patterns.

### Wider vision (sequenced, not parked)

The full sales-enablement vision the documents describe — a **department-agnostic** onboarding + roleplay/coaching + certification framework where a "department programme" is a configurable record (Sales / Crew / Directors as the first three, future departments addable mostly as config) — remains the destination. The AI Roleplay Simulator (`neon_lms_roleplay` in its spec) is a separate, larger build needing the AI engine; it shares the LMS. Build piece by piece; Sales adoption first.

**Decision points for Robin + Munashe (not settled):** AI chat provider for any roleplay/coaching (Groq/Gemini vs adding a Claude adapter — cost/data/latency); whether the trainer host is `neon_lms` or a sibling module; the blocking-gate design.

---

*Last updated: 27 June 2026.*
