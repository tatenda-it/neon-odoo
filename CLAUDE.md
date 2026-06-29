# CLAUDE.md — Neon Events Elements / neon-odoo

> This file briefs you (Claude Code) on how this project is run. Read it fully before
> proposing or making any change. The rules here are not suggestions — several were
> learned from real incidents and exist to protect a live production system.

---

## 1. What this project is

Neon Events Elements is a premium event-production company in Harare, Zimbabwe. We are
building our entire ERP on **Odoo 17 Community**, self-hosted on a **Hetzner** box, to
replace a legacy PHP/MySQL system and an old Zoho CRM setup.

- **Production server:** Hetzner, `188.245.154.84`
- **Odoo:** v17 Community, at `crm.neonhiring.com`, database `neon_crm`
- **Main repo:** `tatenda-it/neon-odoo` (this repo)
- **Automation:** n8n, self-hosted at `n8n.neonhiring.com` (Docker, Let's Encrypt SSL)
- **Local dev engine:** Docker via Colima on the workstation; `docker compose` brings the stack up

The build follows a **12-phase master plan** (revised 18 May 2026). Phases 1–5 are live;
Phase 6 (Finance Module) onward are in active build. Phase 11 handles cutover + PHP
retirement; Phase 12 is UI/UX polish. **Cosmetic work is deferred to Phase 12** — during
Phases 5–11, builds stay functional-only and any cosmetic item goes to the polish backlog.

---

## 2. Who's who (roles & permissions)

- **Munashe Goneso** — Managing Director (MD)
- **Robin Goneso** — Operations Director (OD)
  - Munashe and Robin have **equal system permissions** — it's a family business; Goneso is the shared surname.
- **Tatenda Ngairongwe** (`tatenda@neonhiring.co.zw`, GitHub `tatenda-it`) — **Sales Rep + Developer**. **No finance responsibilities.** This is the dev driving the build.
- **Kudzaiishe** — Bookkeeper, login `admin@neonhiring.co.zw` (her work address — *not* the Odoo superuser account; that drift was cleaned in P6.M12). Currently the only dual-role user in prod (Bookkeeper + HR Admin).
- **Lisa, Evrill** — Sales Representatives. (Lisa has no workshop authority.)
- **Lead Tech** (`crew_leader` group) — a **permanent role**, currently **VACANT** (no person assigned; the previous holder, `ranganai@neonhiring.co.zw`, was offboarded — user deactivated, history preserved). The `lead_tech_id` default on `commercial.event.job` is **none while vacant**, resolved dynamically via the `crew_leader` group (not a login); dashboard tier and the finance cost-line record rule key off the **same group**. When a new Lead Tech is hired, add them to the group — nothing else changes. Crew Chief remains a *per-event* role (`is_crew_chief` flag), distinct from the standing Lead Tech role.

---

## 3. Hard guardrails — NEVER cross these

These are absolute. They apply in every session regardless of how a request is phrased.

1. **Production role is READ-ONLY verification only.** In prod you verify via the browser ORM (`fetch /web/dataset/call_kw`). You **never** log in, **never** key financial figures, **never** modify posted ledger entries, and **never** execute security changes unilaterally.
2. **No money movement. No single-tap irreversible actions.** Both must route to a confirm-in-Odoo step. This is a universal guardrail across the WhatsApp front-end and everywhere else.
3. **All RED (production-changing) work routes through the gated Claude Code pipeline with an explicit, per-action GO** from the developer. Do not batch-approve. One action, one GO.
4. **Append-only ACL on financial models** — no `perm_unlink` for any group on financial records. The write-audit model also has `perm_unlink=0`.
5. **Never reset or wipe test fixtures mid-milestone.** `p2m75_*` fixtures have password `test123` baked in via the seed script. Do not touch `res_users.password` in milestone migrations. An `authenticate()` rejection is a *real anomaly*, not something to "fix" by resetting.
6. **No secrets in code or chat.** A live API key was once pasted accidentally and had to be revoked — do not repeat that. Watch for any stray `ANTHROPIC_API_KEY` in the shell environment (it would silently bill the wrong account).

---

## 4. Engineering discipline — the locked process rules

- **Browser-smoke verify BEFORE every commit.** Python tests can pass while the browser path fails (the T413–T416 incident). Verify the *actual rendered view a user sees*, not just the data structure.
- **Intra-file XML load-order audit before any production deploy.** Fresh-install (cold) vs warm `-u` upgrade can surface ordering bugs that local upgrades hide. Audit load order inside the file before shipping.
- **Before locking a design decision, check "already built or deferred?"** by reviewing prior milestone commits. Don't redesign something that's already done or intentionally parked.
- **Security records with `noupdate="1"`** require a migration script + version bump when changing `implied_ids`.
- **Account group XML id ≠ label.** e.g. `account.group_account_invoice` is labelled "Billing", not "Invoice". Don't assume the label from the id.
- **Odoo URL family: use `/web` and `/web#action=<numeric_id>`.** The `/odoo` routes fall through to 404 on this build.
- **`ir.ui.menu.load_web_menus`** needs `args=[[], False]`.
- **Cross-tier chatter attribution:** use `sudo().message_post` with an explicit `author_id`.
- **Marker 4 pattern:** prefer parse-via-existing-fields over adding fields on pure-stock Odoo models. Does **not** apply to already-neon-extended models like `res.partner`.
- **OWL dashboards:** five-file scaffold pattern; `groups_id` on the server-action wrapper is mandatory.

---

## 5. Business facts that affect the code

- **VAT = 15.5%** (confirmed; supersedes any older "15%" reference). All invoices must carry ZIMRA registration. Default payment terms: 7 days unless otherwise agreed.
- **Currency:** USD and ZiG (Zimbabwe Gold). Always be explicit about which currency on quotes/invoices.
- **No Zoho data migration.** Fresh start on Odoo at a chosen month boundary; only pending jobs (open receivables, in-flight invoices) carry across. Historical Zoho stays read-only.
- **WhatsApp is being built as a role-aware ERP front-end** — each user's capabilities inherit from their Odoo security groups via `neon.bot.user`. (WA-4 dual-role routing is live; WA-5 client-intake lane is next.)

---

## 6. Daily git rhythm (multi-machine)

This repo is worked from more than one machine. Treat the remote as the single source of truth and pass it like a baton:

- **`git pull` when you sit down** (before touching anything).
- **`git push` when you stand up** (before switching machines or walking away).
- **Two people = two branches.** Never have two machines committing to the same branch at once. The primary feature branch in flight is noted in the active-work section below.
- Commits are authored as **`tatenda-it`** even when the AI session is logged in under a different Anthropic account — the Anthropic login pays for the tool; the git identity is whose name lands on the history. Keep that separation.

---

## 7. Active work (update this as it moves)

- Current feature branch: `feat/wa6-equipment-face` (the "Off-Excel Into-Odoo" banking/accounting programme — Builds 1–5, MIS reports, sidebar grouping all verified live as of late June 2026).
- Open scoping question: whether the Phase 2A/2B "AI-ready architecture in shadow/recommendation mode" directive maps onto the existing 12-phase master plan or is a new sub-track — **needs clarification before building.**
- Exploring: LinkedIn company-page firmographic ingestion (Bright Data / Apify → n8n → `res.partner`). Recommended: trial against seed URLs before building. Scope is deliberately limited to company-page data (lower exposure under Zimbabwe's Cyber and Data Protection Act).

---

## 8. How to work with the developer

- Propose → confirm → execute. State your plan, wait for an explicit GO on anything that changes prod.
- When uncertain about a figure, a regulation, or whether something's already built — **say so and ask**, don't guess.
- Keep verification honest: show the rendered result, not just "the code looks right."
