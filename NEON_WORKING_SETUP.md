# How We Work — Neon Events Elements / Odoo build

**To:** Claude (whether you're the chat assistant helping us think, or Claude Code working inside VS Code)
**About:** how this project is run across **two equal workstations** — Tatenda's and Robin's.

This is not a handover. It's the standing description of how we both work. Tatenda and Robin
each run their own station, and **both can commit and deploy to production the same way.**
Read this so you can pick up the project on either machine and work the way we work.

---

## Read this first

If you're **Claude Code inside VS Code**: there's a `CLAUDE.md` in the root of this repo. Read
it fully before doing anything — it's the rulebook. This file is the picture and the "where we
are"; CLAUDE.md is the law.

If you're the **chat assistant**: you won't have the repo in front of you, but this gives you
the full picture so you can advise well and hand clean instructions to Claude Code.

---

## LOCAL vs PRODUCTION are two SEPARATE systems (read this — it causes confusion)

There are two different machines and they are not the same thing:

- **PRODUCTION** = the live Hetzner server (`neon-odoo-prod`, `188.245.154.84`, database
  `neon_crm`, repo at `/opt/neon-odoo`). This is full and live — real data, real modules
  installed, real clients. When this file says something is "live in production," it means here.
- **LOCAL** = a developer's own laptop (Tatenda's or Robin's). A freshly set-up laptop is
  **empty by design** — no `neon_crm` database, submodules not initialised, stack not yet
  started. **That is normal and expected. An empty local machine is NOT a contradiction of
  "live in production."** They describe different machines.

So if you're on a new machine and find local is blank while this file says modules are live —
both are true. Local is a clean sandbox; production is the live server. Don't try to "fix" the
empty local state as if something's wrong; just set the local stack up.

How we verify each:
- **Local:** bring the stack up, smoke-test in the browser at `localhost:8069` before committing.
- **Production:** READ-ONLY checks via the browser ORM (`fetch /web/dataset/call_kw`) over SSH
  (`ssh hetzner`, user `root`). This is a **Claude Code** job — the chat assistant cannot reach
  prod. We never verify prod by logging in and clicking around, and never edit posted entries.
  There is **no Odoo MCP connector** and there never was one — prod access is SSH + ORM only.

---

## The short version

Neon Events Elements is a premium event-production company in Harare, Zimbabwe. We're building
our whole ERP on **Odoo 17 Community**, self-hosted on **Hetzner** (`188.245.154.84`), replacing
an old PHP/MySQL system and a legacy Zoho setup. The build follows a **12-phase master plan**.
Phases 1–5 are live in production; Phase 6 (Finance) onward are in active build.

We are a real, shipping project. **We commit, we deploy, and we change production** — from
either station — through a gated process. Getting that gate and the two-station coordination
right is the most important thing on this page.

---

## How we work with production (the important part)

**Both stations DO touch production.** We commit code, deploy, and make live changes — Tatenda
from his machine, Robin from his. The rule is not "don't touch prod." The rule is:

> **Every production-changing action goes through the gated Claude Code pipeline, with an
> explicit per-action GO from the developer. One action, one GO. Nothing unilateral.**

So always **propose → confirm → execute**:
1. Describe exactly what you're about to change and why.
2. The developer reviews and says GO (or asks for changes).
3. Only then run it.

What's forbidden is *acting on your own* — clicking around prod logged in, keying financial
figures by hand, editing posted ledger entries directly, or running a security change without a
GO. Read-only checking of prod is fine, via the browser ORM (`fetch /web/dataset/call_kw`).

### Because two stations both deploy: deploy ONE AT A TIME

This is the rule that keeps the two machines from colliding:

- **Only one station deploys to production at any moment.** The other waits.
- **Before deploying:** pull latest, and confirm the other person isn't mid-deploy. A quick
  "I'm deploying now" between the two of you is enough — no special tooling needed.
- **Let a deploy finish completely** before the other station starts one.
- The GO gate stops *bad* changes. One-at-a-time stops *two good changes colliding*. You need
  both.
- **Prefer separate feature branches** so you're not editing the same files at once; merge to
  main when ready.

---

## Who's who

- **Munashe Goneso** — MD. **Robin Goneso** — OD. Equal system permissions; family business (Goneso is the shared surname).
- **Tatenda Ngairongwe** (`tatenda@neonhiring.co.zw`, GitHub `tatenda-it`) — Sales Rep + Developer. No finance role.
- **Kudzaiishe** — Bookkeeper (`admin@neonhiring.co.zw`).
- **Lisa, Evrill** — Sales Reps.
- **Ranganai** — permanent Lead Tech; default `lead_tech_id` on `commercial.event.job`.

---

## Facts that affect the code

- **VAT = 15.5%** (confirmed; any "15%" is outdated). Invoices carry ZIMRA registration; default terms 7 days.
- **Currency:** USD and ZiG (Zimbabwe Gold) — always be explicit which.
- **No Zoho data migration** — clean cutover; only pending jobs carry across, history stays read-only.
- **Odoo URLs:** use `/web` and `/web#action=<numeric_id>`. The `/odoo` routes 404 on this build.
- **WhatsApp** is a role-aware ERP front-end (capabilities inherit from Odoo security groups via `neon.bot.user`).

---

## Discipline we never skip

- **Browser-smoke verify BEFORE every commit.** Python tests can pass while the browser path is
  broken (the T413–T416 incident). Check the *rendered view a real user sees*, not just the data.
- **Intra-file XML load-order audit before any prod deploy.** A cold fresh-install can expose
  ordering bugs a warm local upgrade hides.
- **Before locking a design decision, check "already built or deferred?"** in prior milestone commits.
- **Cosmetic work waits for Phase 12.** Phases 5–11 stay functional-only; styling goes to the polish backlog.

---

## Where we are right now

- **Stations:** Tatenda's machine (the original) and Robin's MacBook (just set up — Homebrew,
  git, gh, VS Code, Colima + Docker, repo cloned, Claude Code installed inside VS Code). Git
  identity on both is `tatenda-it`.
- **Local stack on the new Mac:** Colima (Docker engine) is running; the local Odoo stack has
  **not** been brought up there yet.
- **Active branch:** `feat/wa6-equipment-face` — the "Off-Excel Into-Odoo" banking/accounting
  programme. **The codebase has BUILD 1–4 (numbered); BUILD 5 is the NEXT thing to build, not
  yet written.** ("Builds 1–5" in earlier notes was loose wording — trust the code: 4 numbered
  builds.) Also on the branch (un-numbered): `neon_web_sidebar`, `neon_weekly_budget`,
  `neon_mis_reports`, `neon_menu_order`, `neon_bank_import`, `neon_insights`, `neon_migration`.
- **Module status note:** `neon_web_sidebar` and `neon_weekly_budget` ARE live on production
  (confirmed 28 Jun 2026). Any older "DEV GATE-HOLD" note on those two is stale — they are live.
- **main vs prod (as of 28 Jun 2026):** prod is checked out on `feat/wa6-equipment-face` at
  HEAD `6d3f484`. `origin/main` (`b178259`) is a **strict ancestor** — 143 commits behind, zero
  divergence — so reconciling main is a clean fast-forward. Production also carries a submodule
  layer (`.gitmodules` + 11 OCA submodules under `/mnt/oca-*`) that does NOT exist on main yet;
  both the 9 neon module dirs and the OCA submodule layer must land on main for it to match live.
- **Weekend work (28 Jun 2026, on a review branch, NOT deployed):** Phase 2 Commercial
  Intelligence chain (2A–2F, builds INERT/shadow-mode), Market Radar (inert), 4 role cockpits,
  Ranganai offboarding. All additive, all gates held, nothing on main, nothing deployed. Pending
  conflict-check against reconciled main before any deploy.
- **Exploring:** LinkedIn company-page firmographic ingestion (Bright Data / Apify → n8n →
  `res.partner`); trial against seed URLs before building.

---

## Where to start (in order)

1. **Get oriented.** Read `CLAUDE.md`, then summarise back — in your own words — how we handle
   production, the propose→confirm→execute gate, and the one-at-a-time deploy rule.
2. **Bring up the local Odoo stack** on whichever Mac you're on. Review the `docker compose`
   setup, flag anything Apple-Silicon related (may need `platform: linux/amd64` on some
   services), then wait for GO before `docker compose up -d`.
3. **Pick up the wa6-equipment-face / banking work** once local is up. Confirm what's done
   (BUILD 1–4 exist; BUILD 5 is next) and what's next, browser-smoke verifying as you go.
4. **Resolve the Phase 2A/2B scoping question** before any new build starts on it.

At every step: propose first, wait for GO, then execute. When unsure about a figure, a rule, or
whether something's already built — ask, don't guess.

---

## Daily habit (two stations)

The remote is the single source of truth.
- **`git pull` when you sit down.**
- **`git push` when you stand up.**
- **Deploy one at a time** (see the production section above).
- Prefer separate feature branches; merge to main when ready.
- Commits are authored as `tatenda-it` even when the Claude session is logged in under Robin's
  Anthropic account — the login pays for the tool, the git identity is whose name lands on history.
