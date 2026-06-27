# NEON ERP — System Reference Map

**Purpose:** The single source of truth for *what exists* in the Neon ERP — modules, models, dependencies, what's live on prod, and the structural hazards. This file exists so that any new chat or Claude Code session can load the whole picture from here instead of rebuilding it from scratch.

**How to keep it useful:** This map goes stale the moment modules change. Treat it like the rest of the repo — refresh it when the system changes, the same way you `git pull` / `git push`. If a session's understanding and this file disagree, re-verify against the live system rather than trusting either blindly.

**Compiled:** 27 June 2026, from a read-only audit of branch `feat/wa6-equipment-face` plus a confirmed prod module-state check. 
**Build:** Odoo 17 Community, self-hosted on Hetzner (`188.245.154.84`). Prod: `crm.neonhiring.com`, DB `neon_crm`. URLs use `/web`; `/odoo` routes 404 on this build.

---

## 0. Headline facts

- **29 modules total:** 28 tracked on the branch + `neon_base` (uncommitted local-only shim).
- **Prod status — CONFIRMED (not inferred):** all 28 tracked modules are in state `installed` on prod. This **includes** the banking Builds and UI-shell modules, despite their commit history being tagged "(DEV ONLY, no prod)". `neon_base` is the only module not on prod (it has never left the local dev box).
  - ⚠️ **Observation worth raising with Tatenda:** the "DEV ONLY" commit tags on the banking modules disagree with their actual `installed` state on prod. Either they were deployed after those tags were written (stale history), installed-but-not-yet-exposed to users, or an unintended deploy. Not necessarily a problem — but "what we think we deployed" and "what's installed" have diverged at least in the record. Worth a reconcile.
- **Two equal workstations** (Robin's + Tatenda's), one shared branch, time-separated. Production changes go through the gated propose → confirm → execute pipeline in Claude Code; one action, one GO; deploy one station at a time.

---

## 1. Dependency graph & cold-install hazards

### neon-internal dependency edges (load order)

```
neon_base              → (none)                    ← must load FIRST
neon_crm_extensions    → (none, stdlib only)
neon_jobs              → neon_base
neon_finance           → neon_jobs
neon_training          → neon_jobs, neon_crm_extensions, neon_finance
neon_core              → neon_jobs, neon_finance, neon_training, neon_crm_extensions
neon_ai_core           → neon_core
neon_doc_gen           → neon_core
neon_channels          → neon_ai_core
neon_crew_comms        → neon_jobs, neon_channels, neon_finance
neon_dashboard         → neon_core, neon_ai_core, neon_jobs, neon_finance, neon_crm_extensions, neon_training
neon_hr                → neon_core, neon_jobs
neon_insights          → neon_core, neon_jobs
neon_lms               → neon_core, neon_training
neon_kb                → neon_core, neon_training, neon_lms
neon_library           → neon_core
neon_external_training → neon_core, neon_training
neon_onboarding        → neon_core, neon_jobs, neon_training
neon_migration         → neon_core
neon_status            → neon_core, neon_ai_core, neon_channels
neon_sales             → neon_finance
neon_weekly_budget     → neon_finance
neon_banking_labels    → neon_finance, neon_core (+ OCA: account_statement_base, account_reconcile_oca, partner_statement, account_financial_report)
neon_banking_statement → neon_finance, neon_banking_labels
neon_bank_import       → neon_banking_labels, neon_banking_statement
neon_mis_reports       → neon_banking_labels (+ OCA mis_builder)
neon_web_sidebar / neon_menu_order / neon_login_bypass → (no neon deps; stdlib only)
```

### The cold-install trap (why fresh installs fail but warm `-u` doesn't)

Everything from `neon_core` upward has **never been cold-installed** before the June 2026 sandbox exercise — it's always been warm-upgraded on Tatenda's box and prod. That masked a class of latent bugs that only a fresh DB exposes:

1. **Circular group dependency.** `neon_core` defines `group_neon_superuser` but depends on `neon_jobs`/`neon_finance`/`neon_training` — yet those lower modules reference that group. On cold install they load first and the xmlid doesn't exist yet. → **Fixed by `neon_base`** (the "Option 3" shim): a tiny module that pre-declares the group via `_post_init_hook` so it loads before `neon_jobs`. `neon_core` later updates the shell into the real group. Net access model unchanged.
2. **Chart-of-accounts assumption.** `neon_finance` references `account.1_tax_received`, `1_tax_paid`, `1_sale`, `1_sale_tax_template`, `1_purchase_tax_template` — these only exist once a CoA is applied. → Cleared on the dev sandbox by applying the generic v17 chart. (Prod uses whatever chart was applied at its original install — confirm before any tax/VAT/fiscal work.)
3. **`neon_training` intra-module cold debt:** (a) a `validity_months` → `default_validity_months` typo on the Safety certification category [one-line fix authorised]; (b) a menu load-order forward-reference — a wizard view at manifest pos 25 references `menu_neon_training_root` defined at pos 26. Both masked on warm upgrades.

**Standing principle:** cold-install hardening of the committed modules is a real, separate task that belongs to Tatenda (or a joint audit), not something to patch ad hoc solo. The dev sandbox is unblocked via local-only seeding that touches no committed source.

---

## 2. Module-by-module reference

> Format: Purpose · Depends · Key models (key fields) · Inherits · Groups · Record rules · Notable. 
> All 28 tracked modules are `installed` on prod. `neon_base` is local-only/uncommitted.

### Foundation / RBAC

**neon_core** — RBAC meta-groups + ACL hygiene. 
Depends: base, mail, sale_management, account, crm, product, neon_jobs, neon_finance, neon_training, neon_crm_extensions. 
Models: none (no models dir; empty ACL CSV). 
Groups (category "Neon Tier", cascading `implied_ids`): `group_neon_superuser` (full stack incl. dev mode + every Neon manager role), `group_neon_bookkeeper` (accounting mgr + sales read-all; no approver/dev), `group_neon_sales_rep` (CRM + own quotes + pricelist), `group_neon_lead_tech` (crew_leader + training signoff), `group_neon_crew` (jobs crew + training user). 
Record rules: none. 
Notable: the real work is `_post_init_hook` — (1) strips 4 leaked `implied_ids` from `base.group_user`; (2) assigns canonical users by login (robin/munashe/tatenda → superuser; admin@ → bookkeeper; lisar/evrill → sales_rep; ranganai → lead_tech). Mirrored by migrations. No crons/controllers/assets/WA.

**neon_base** ⚠️ *uncommitted, local only* — cold-install shim. 
Depends: base. Models/Groups/Rules: none. 
Notable: `_post_init_hook` creates a bare `res.groups` and registers it under the `neon_core.group_neon_superuser` xmlid (idempotent ORM); `neon_core` later updates it. Pure install-ordering shim. Not on prod.

### Operations

**neon_jobs** — Phase 2 Commercial Job Record + calendar/capacity. The central ops hub linking CRM ↔ Finance ↔ Calendar ↔ Workshop ↔ Training. 
Depends: base, neon_base, mail, sale, crm, contacts, account, product, base_geolocalize, purchase. (neon_doc_gen imported lazily.) 
Key models: `commercial.job.master` (multi-event contract parent), `commercial.job` (central event record, quote→active, 3 status tracks + capacity gate), `commercial.event.job` (execution model, 10-state machine + 6-dim readiness + closeout), `commercial.job.crew` (crew assignment + confirm/decline). Checklists (`commercial.event.job.checklist`/`.item` + templates). `commercial.scope.change`, `commercial.event.feedback` (client + WA-10 staff). Action Centre: `action.centre.item` (4-state nudge), `.item.history` (append-only), `.item.tag`, `action.centre.mixin`, `action.centre.trigger.config`. Equipment/Workshop: `neon.equipment.category`/`.unit` (9-state asset)/`.reservation`/`.movement` (append-only)/`.repair.order`/`.incident`/`.stock.take`/`.conflict` (P-B2 detection). AI/sub-hire/recon: `neon.deployment.plan`, `neon.subhire.request`, `neon.event.reconciliation` (B3/B4/B5 — Claude via neon_doc_gen). `venue.room` + ~13 wizards. 
Inherits: mail.thread/activity; crm.lead, crm.stage, res.partner (venue), sale.order, product.template (workshop fields). 
Groups (category "Neon Operations"): `group_neon_jobs_user`/`_manager`/`_crew`/`_crew_leader`. 
Record rules: 11 (all scope the crew tier to own assignments/jobs/event-jobs/checklists/scope-changes/feedback/AC-items + WA-10 write-own). 
Notable: 5 crons (soft-hold expiry; AC escalations hourly; AC time-triggers 00:30; stock-take weekly Tue 06:00; B2 conflict backstop daily 06:00 Harare). OWL: Workshop Dashboard, venue map widgets (vendored Leaflet). WA hook: check-in wizard fires WA-10 as a guarded cross-module call; module stays standalone-installable.

### Finance

**neon_finance** — ZW finance + Phase 6 pricing engine + quote + OD/MD approval + cost lines + P&L + multi-stage invoicing. 
Depends: base, account, neon_jobs. 
Key models: `neon.finance.pricing.rule` (rate card per category/product/currency/date), `.pricing.bracket` (multi-day taper), `.day.multiplier`, `.conversion.rate` (dated USD/ZiG FX). `neon.finance.quote` (central Phase 6 pivot, 8-state, currency-locked USD/ZWG). `.quote.line` (hosts pricing engine). `.approval`, `.cost.line` (may be negative for write-off), `.invoice.schedule` (+templates), `.dashboard` (virtual cash-flow RPC) + wizards. 
Inherits: account.move, account.account (+neon_source), account.payment.register, account.bank.statement, res.partner, res.config.settings, neon.equipment.category/incident, commercial.event.job. 
Groups (category "Neon Finance"): `group_neon_finance_user`/`_sales`/`_bookkeeper`/`_approver`. 
Record rules: 18, all `perm_unlink=False` — sales see own quotes/lines/approvals/schedules via salesperson_id; bookkeeper/approver all; crew_leader cost-lines via lead_tech_id. 
Notable: 3 daily crons (quote expiry, invoice-schedule sweep, overdue-payment). OWL cash-flow dashboard. **Append-only ACL across all financial models.** CoA xmlids + **VAT 15.5%** repartition. Invoice PDF has a ZIMRA strip. Seeds banking accounts/journals (CABS ZWG, undeposited funds) + currency_zwg. WA-12 quote provisioning hooks.

**neon_banking_labels** — cosmetic relabels of accounting jargon. 
Depends: account, account_statement_base, account_reconcile_oca, partner_statement, account_financial_report, neon_finance, neon_core. ⚠️ *the neon_core dep is the uncommitted held manifest edit.* 
Models/Groups/Rules: none. 
Notable: label overrides ("Journal"→"Account", Invoicing→"Accounting"), "Statements" + "Reporting" launchers (OCA wizards), hides native "New Transaction" on journal cards. No crons/controllers/JS.

**neon_banking_statement** — per-account running ledger + Add-Transaction quick entry. 
Depends: neon_finance, neon_banking_labels. 
Models: `neon.cash.entry.mixin` (Abstract) + 10 Transient wizards (expense, replenishment, vendor-payment, customer-receipt, vendor-advance, drawings, commission, contribution, transfer, correct). 
Inherits: account.move.line (read-only running balance + counterpart code). 
Notable: OWL list-controller patch adds the header dropdown. Vendor-payment/customer-receipt route via account.payment.register (cross-currency guard). Correction wizard reverses, never deletes (append-only). Hardcoded account codes, not xmlids.

**neon_bank_import** — CABS bank-statement CSV import. 
Depends: account_statement_base, neon_banking_labels, neon_banking_statement. 
Models: `neon.bank.statement.import.wizard` (parses CABS CSV USD+ZWG, signed amount = Credit−Debit, creates native account.bank.statement). 
Notable: one report XML; no posting-logic change.

**neon_mis_reports** — P&L / Balance Sheet / Cash Flow (OCA mis_builder), USD/ZWG. 
Depends: mis_template_financial_report, mis_builder_cash_flow, neon_banking_labels. 
Models: `neon.set.exchange.rate.wizard`. 
Notable: post_init builds 6 DRAFT reports (USD+ZWG × 3). ⚠️ The rate wizard writes a `res.currency.rate` row — money-adjacent (affects all conversions that date), finance-gated.

**neon_weekly_budget** — weekly cash-planning sheet (replaces Excel). 
Depends: neon_finance. 
Models: `neon.weekly.budget` + `.line`. 
Notable: planning-only, NO ledger/payment link (reconciliation deferred to v2). NOT append-only.

### CRM / Sales

**neon_crm_extensions** — custom CRM fields + workflow. 
Depends: crm, sale_management, phone_validation, mail, account. 
Models: `neon.payment.confirm.wizard`. 
Inherits: crm.lead (SLA/dedup/automation + write-guard), res.partner (finance overview), res.company (ZIMRA ids), mail.activity (alert tier). 
crm.lead custom fields: x_brand, x_consent_given, x_equipment_required, x_annual_event_month, payment_claim_status (none/claimed/verified — verified is write-guarded), x_duplicate_flag, x_first_response_time, x_sla_breached (>2h), x_lead_score (1–5), x_alert_label, x_alert_color. 
Groups: `group_neon_finance_manager` (only group that can set payment_claim_status='verified' — for the Zoho Books bridge service user). 
Notable: 6 crons (dedup; quote follow-up D3/D7; stuck-deal; annual-client 9-mo; dup-warning). WA hook posts to OpenClaw API (NOT neon_channels), best-effort.

**neon_sales** — sales-cycle customisations. 
Depends: sale_management, sale_crm, neon_finance, sale_global_discount. 
Models: none. Inherits: sale.order (covering-letter fields for quote PDF). 
Groups: `group_neon_legacy_stock_sales` (hidden group to hide stock sale menus). 
Notable: hides 5 stock sale menus, redirects "My Quotations" to the neon_finance quote action.

### AI

**neon_ai_core** — shared AI chat engine (provider abstraction, tool-calling orchestrator, two-phase write guardrail, chat audit). 
Depends: base, neon_core. 
Models: `neon.dashboard.ai.provider`, `neon.finance.ai.chat.session`, `.message`, `.write.log` (two-phase guardrail: confirmation_token, params_hash, status, 10-min TTL). Plain-Python adapters: groq, gemini, factory, orchestrator, tool_registry, pending_action. 
Notable: **chat adapters are Groq + Gemini only** (Anthropic/Ollama commented as future). Pure engine — no crons/controllers/views/assets; neon_dashboard adds the OWL panel. ChatOrchestrator: rate-limits (30 msg/hr, 10 confirmed-writes/hr), ≤3 tool iterations, group-filtered tool advertising, two-phase writes executed under the real user's identity in a savepoint.

**neon_doc_gen** — Claude API doc-generation engine (B3/B4/B5 docs). 
Depends: base, neon_core. 
Models: `neon.doc.gen.provider` (anthropic only, **claude-sonnet-4-6**, key in ir.config_parameter) + `.set.key.wizard`. Adapter `ClaudeDocGenAdapter`. 
Notable: **This is the only place Claude/Anthropic is used.** Deliberate split: Groq/Gemini for high-frequency tool-calling chat; Claude for low-frequency, high-value document generation. Consumed by neon_jobs B3/B4/B5 generators.

### WhatsApp / Comms

**neon_channels** — WhatsApp + Twilio + WA-0 Copilot rails. v17.0.1.22.7. 
Depends: base, crm, mail, utm, neon_ai_core. 
Models: `neon.bot.user` (phone→user identity spine, unique phone), `neon.whatsapp.message` (audit + inbound router), `neon.whatsapp.config` (Meta), `twilio.config` (legacy), `neon.wa.client.session` (client-intake FSM). Plain-Python: wa_payload (HMAC tap-back + INTENTS), wa_copilot, phone_utils. 
Notable: webhook GET/POST `/whatsapp/webhook` (public, HMAC verify, flush_all in-try to avoid Meta retry storms) + legacy `/twilio/webhook`. **Capability ceiling: WhatsApp tools = all read tools + only {log_lead, move_stage, post_chatter_note}. Money/irreversible writes are structurally absent for every role, including superuser — you cannot move money over WhatsApp.**

**neon_crew_comms** — B11/WA-2 WhatsApp-to-ops bridge (proactive crew messaging + all WA-N handlers). v17.0.1.21.4. ⚠️ *manifest version lags the actual WA-12/13 feature set — worth a version-bump audit before next deploy.* 
Depends: base, neon_jobs, neon_channels (+ neon_finance via inherit). 
Models: `neon.wa.equip.session` (multi-turn staff FSM ~30 steps), `neon.readiness.digest` (Abstract, WA-3 RAG), `neon.equipment.alias` (WA-12 slang matcher), `commercial.job.crew.notify.wizard`. 
Inherits: commercial.job/.crew/event.job (notify/finalize), neon.finance.quote (WA-12 approval ping), neon.whatsapp.message ×8 (the WA-arm interceptor chain). 
Notable: controller `/neon/readiness`. 2 crons shipped DISABLED. WA arm map: WA-0 Copilot · WA-1 renderer · WA-2 crew confirm/decline · WA-3 readiness digest · WA-4 dual-role lens · WA-5 client intake · WA-6 equipment face · WA-7 crew select · WA-8 availability · WA-10 feedback · WA-12/13 money-adjacent quote/invoice (approver-gated).

### People / Training

**neon_hr** — People R1a–R3a: employee master, contracts, docs, leave, payroll, wages, loans, accidents, discipline, TOIL, handbook, licences + competency gating. 
Depends: base, mail, hr, hr_contract, hr_holidays, neon_core, neon_jobs. 
Key models (~24): categories/document-types/documents; contract templates; payroll (wage.grade, event.wage, statutory.rule PAYE/NSSA/AIDS/NEC, payslip+line, commission, overtime); loans+repayments; accidents (NSSA 14-day)/cases; competency (competency, employee.competency, role.competency, licence); handbook+ack; reviews (append-only); availability (SQL view). 
Inherits: hr.employee, hr.contract (renewal SM + action.centre.mixin), hr.leave.type, commercial.job.crew (driver-licence = hard block; competency = OD/MD-overridable gate). 
Groups: `group_neon_hr_admin` (implies hr/contract/holidays managers); OD/MD via superuser. 
Record rules: owner-sees-own + admin/OD-all on ~14 confidential models. 
Notable: 3 daily crons (contract/doc refresh, accident NSSA deadline, licence expiry).

**neon_training** — Phase 7a workforce training/cert/skill + M8–M11 three-tier crew gating. ⚠️ *carries cold-install debt (see §1).* 
Depends: base, mail, neon_jobs, neon_crm_extensions, neon_finance. 
Models: `.certification.category` (`default_validity_months`), `.certification.type`, `.certification` (per-person SM), `.cross_competency`, `.assignment_gate_log` (append-only, tiers 1–3), `.dashboard`. 
Inherits: res.users (Training tab), neon.finance.quote (M10 tier-2 WARN gate), commercial.event.job (M8 rollup + M11 tier-3 BLOCK), commercial.job.crew (M8 inference + M9 tier-1 toast). 
Groups: `group_neon_training_user`/`_signoff`/`_admin`. 
Notable: 2 daily crons (expire certs; renewal 90/30/7-day). Certificate PDF with verify token.

**neon_external_training** — off-site manufacturer/regulator course bookings. 
Depends: base, mail, neon_core, neon_training. 
Models: `.vendor` (5 seeded), `.booking` (approval SM → auto-issues neon.training.certification on completion). 
Notable: daily 3-day-reminder cron; WA/email dispatch = Phase-9 stubs.

**neon_onboarding** — Phase 7b crew onboarding state machine (candidate → cert_collection → probationary → active). 
Depends: base, mail, portal, website, neon_core, neon_jobs, neon_training. 
Models: `.candidate`, `.requirement.template` (per-role), `.audit.log` (append-only). 
Inherits: commercial.event.job (recompute probationary jobs on completion). 
Notable: portal controller `/my/onboarding` (+/upload, /jobs) for self-upload certs + probationary view. WA/email = Phase-9 stubs. *(This is crew onboarding — distinct from the planned sales onboarding trainer.)*

**neon_lms** — internal LMS, 7-track + sub-certs + capstone. Custom domain layered on stock website_slides. 
Depends: base, mail, website_slides, neon_core, neon_training. 
Inherits: slide.channel, slide.channel.partner (NOT slide.slide). 
Models: 12 `neon.lms.*` — track, module, quiz.question/option/attempt/attempt.response, **practical.scenario + scenario.completion**, module.completion, track.completion, operating.authority, sop. 
Structure: one slide.channel ("Neon Workshop Training Program") → 7 tracks (Foundations & Safety gate → Audio, Lighting, Video/LED, Workflow/Ops, Soft Skills, Rigging) → 17 modules (M01–M17), each with a quiz (≥0.8, server-graded, unlimited retakes) + optional practical scenarios. Track completion mints a sub-cert; all 7 → capstone. 6 operating authorities computed from certified tracks. 
Record rules: own scenario/enrollment/quiz-attempt (tamper-proof scoring). 
Notable: quiz controller `/slides/neon/quiz/*`; issues certs into neon_training via sudo. 
📌 **The `practical.scenario` + `scenario.completion` pattern is the closest existing analogue to a roleplay/scenario-practice capability — relevant to the planned sales-enablement build.**

### Knowledge / Docs

**neon_kb** — searchable SOP/knowledge base (Phase 7d). 
Depends: base, mail, portal, neon_core, neon_training, neon_lms. 
Models: `.category` (5 seeded), `.tag`, `.article` (draft→published→archived; cross-links to cert-types/SOPs/modules). 
Notable: portal controller `/my/kb`. application=True.

**neon_library** — company file library, nested folders + full-text search. The simplest module. 
Depends: base, mail, neon_core, attachment_indexation. 
Models: `.folder` (nested), `.document` (file_data, index_content), `.tag`. 
Record rules: read-all / write-own / superuser-all. 
Notable: uses stock attachment_indexation for content indexing.

### Dashboards / Insights / Status

**neon_dashboard** — Phase 8A Director + 8B role-variant dashboards on the shared `neon.dashboard` framework. 
Depends: base, mail, web, neon_core, neon_ai_core, neon_jobs, neon_finance, neon_crm_extensions, neon_training. 
Models: `neon.dashboard` (one per user/type; hosts the RPCs), `.user.layout`/`.default.layout`, `.target`, `.alert.dismissal` (append-only), `.digest.log`/`.weekly.digest`, `.ai.insight` (append-only) + wizards. 
Inherits: neon.dashboard.ai.provider, res.users (preferred_dashboard_type, chat_panel_expanded). 
Notable: 2 crons (weekly digest Mon-Harare; AI insights 06/12/18). Controllers `/neon/ai_chat/{send,history,toggle,confirm,cancel}`. Variants: Director (7 tiles + Historical Intelligence band), Sales, Bookkeeper, Lead Tech, HR. **The AI Copilot's tool bodies live here** (18 read + 4 write tools, two-phase); the registry is in neon_ai_core. Dashboard Copilot hard-wired to Groq.

**neon_insights** — read-only client-feedback page `/neon/insights` (WA-11), manager-tier. 
Depends: base, web, neon_core, neon_jobs. 
Models: `neon.insights.collector` (Abstract — aggregates the WA-10 corpus). 
Notable: controllers `/neon/insights` (+/data). Gated to superuser + jobs_manager. Read-only; no sends.

**neon_status** — authenticated programme status board `/neon/status`, live-from-prod read. 
Depends: base, web, neon_core, neon_ai_core, neon_channels. 
Models: `neon.status.live` (Abstract — module versions, bot-user/WA-message counts, write-log status). 
Notable: controllers `/neon/status` (+/data). All internal users. Read-only.

### Migration / Intelligence

**neon_migration** — read-only Zoho Books historical reference import, isolated from live finance. 
Depends: base, neon_core. 
Key models (~22): inert archives (`neon.finance.quote.archive`/`.invoice.archive`/`.expense.archive` — NOT account.move; VAT stored, never posted); SQL-view reports; `neon.petty.cash.statement`/`.suspense.statement`/`.undeposited.statement`; `neon.job.history` (726 FamCal events), `.crew.member`, `.wages.entry`; LIVE `neon.collections.item` (team-editable receivables, no-unlink); STORED computed intel (`neon.client.intel`, `.demand.intel`, `.demand.recurring`, `.winloss.intel`); `neon.zoho.importer` (Abstract loader). 
Notable: **inert by design** — no ledger/AR/AP/cron side-effects on live finance; live aggregates never read archives. Sensitive models (petty/suspense/undeposited/wages) gated to bookkeeper+superuser via field-level `groups=`. 3 daily intel-recompute crons. Loaders are creds-gated scripts, not install-time.

### UI shell

**neon_web_sidebar** — persistent Zoho-style left module rail (coexists with web_responsive). 
Depends: web, web_responsive. Models/Groups/Rules: none. 
Notable: OWL NeonSidebar in main_components; per-user localStorage toggle. No Python/crons/WA.

**neon_menu_order** — sequence-only reorder of top-level app menus into department clusters. 
Depends: base. Models/data/Groups/Rules: none. 
Notable: post_init force-writes `ir.ui.menu.sequence` only (never groups/action/visibility) for ~40 menus (10s Sales, 20s Finance, 30s Intelligence, 40s Ops, 50s People, 60s Training, 70s Comms, 80s System). Idempotent.

**neon_login_bypass** — render `/web/login` bare (skip website chrome). 
Depends: web, website. Models/Groups/Rules: none. 
Notable: one data record deactivating stock `website.login_layout`. Portal routes unaffected.

---

## 3. Cross-cutting design principles (observed across modules)

- **Append-only financial & audit data.** Finance models, audit logs, gate logs, and chat/write logs are `perm_unlink=False` — corrections are reversals, never deletions.
- **Record-rule (row-level) security, not menu-hiding.** Sensitive scoping is enforced at the ORM/record-rule level so it holds through reports, search, API, and exports. (Note: the deferred Finance Phase 1 restricted-cash tiers — SA/Tithe/Drawings/Owner-Personal UF — are *specified* to this standard but *not yet built*.)
- **Two-phase writes for AI actions.** Any AI-initiated write goes propose → token → confirm → execute under the real user's identity. Money/irreversible actions are structurally unavailable over WhatsApp regardless of role.
- **RBAC tiers cascade via `implied_ids`**, defined once in `neon_core`, assigned by login in its post-init hook. Group membership lives in `noupdate=1` blocks → changes go through migration scripts, not ad hoc edits.
- **Standalone-installable where possible.** Cross-module calls (e.g. neon_jobs → WhatsApp) are guarded soft references so modules don't hard-break each other.

---

## 4. Provider / cost / data decision points (for Robin + Munashe)

These are not settled by this map — they're flagged because future builds (esp. AI/sales-enablement) will force them:

- **AI chat provider:** the live chat path runs **Groq + Gemini**, not Claude. Claude is used only for document generation (neon_doc_gen). Any new conversational-AI feature either uses Groq/Gemini or requires adding a Claude chat adapter — a cost/data/latency decision.
- **Chart of accounts:** the dev sandbox uses the generic v17 chart; prod uses whatever was applied at its original install. Confirm prod's actual chart before any tax/VAT/fiscal-bridge work.
- **The "DEV ONLY vs installed-on-prod" discrepancy** on the banking modules (see §0) needs a reconcile with Tatenda.

---

## 5. Maintenance

When modules are added, removed, or materially changed, refresh this file (a read-only audit + the prod module-state check regenerate it). Keep it committed alongside `CLAUDE.md` so every session — chat or Claude Code — can load it. Memory (in the chat assistant) holds only a *pointer* to this file; this file is the source of truth.

*Last verified: 27 June 2026 against branch `feat/wa6-equipment-face` + prod module-state check.*
