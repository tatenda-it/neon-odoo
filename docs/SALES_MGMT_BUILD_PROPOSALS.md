# Sales-Management Build — Design Proposals & Worklist

**Status:** PROPOSALS ONLY — nothing built. A ready-to-run worklist for Tatenda to execute item by item.
**Source:** the read-only sales-management oversight discovery (27 Jun 2026) + the PROGRESS.md "Sales-management build backlog". Read-first; file refs are to `addons/`.
**Compiled:** 28 Jun 2026.

---

## Cross-cutting facts that shape all five

- **All five require the cold-install chain to test locally.** They live in `neon_dashboard` / `neon_crm_extensions` / `neon_migration` / `neon_channels`, each of which depends on the `neon_base → neon_jobs → neon_finance → neon_training → neon_core` chain. Unlike the `website_slides` course seeds (which test in isolation), **none of these can be tested without the foundation installed.** So **clearing the `neon_training` cold-install debt (PROGRESS open-issue #3) — or using a warm prod-like DB — is a de-facto prerequisite for local testing of every item here.**
- **Live data is thin until post-cutover.** The live CRM/quote tables only fill from 1 July onward. Items that *display* live per-rep numbers (#1, #5) are buildable now but won't show meaningful data until reps work the system; **#2 (live intel) is essentially meaningless until weeks/months of live data accrue.**
- **Per-rep aggregation is shared between #1 and #5.** Both need "group CRM/quotes/activities by salesperson". Build the helper once in #1; #5 reuses it.
- **Dashboard scope today:** `_compute_sales_block` (neon_dashboard:2233) aggregates by **stage / source / win-rate only — never by rep**; KPI tiles run `.sudo()` team-wide with no rep filter. So per-rep is genuinely new aggregation, and per-rep data must be **director-scoped** (don't leak a rep-vs-rep scoreboard to individual reps).

---

## Recommended build sequence

**#3 (SLA signal) → #1 (per-rep dashboard + aggregation layer) → #5 (compliance rollup, reuses #1+#3) → #2 (live intel, post-cutover-gated) → #4 (email compliance, design-heavy / weakest-enforceable).**

Rationale: #3 fixes the underlying signal #5 consumes; #1 establishes the per-rep aggregation #5 reuses; #2 is gated on live data; #4 needs design decisions and is the least technically enforceable.

---

## Item #3 — First-response SLA fixes  *(do first — small, self-contained, feeds #5)*

- **What it does:** (a) confirm/align the breach threshold to the agreed **2 hours**; (b) make breach detection **forward-looking** (flag a lead that is *still open and unanswered* past 2h, not only retroactively once a late first response lands); (c) add a **per-rep manager breach view**.
- **Where it lives:** `neon_crm_extensions` — `models/crm_lead.py` (`x_first_response_time`, `x_sla_breached`, `_compute_sla_breached`, the `message_post` stamp), a new cron in `data/cron_jobs.xml`, a new saved filter/action in `views/crm_lead_views.xml`.
- **What it touches:** `crm.lead` compute + a new cron + a list/pivot view grouped by `user_id`/`salesperson_id`.
- **Co-owned/shared:** ⚠️ **`crm.lead` is co-owned** (neon_crm_extensions, Tatenda). ⚠️ **Adds a cron** (shared cron surface).
- **Key design decisions:**
  - Current threshold **is 2h** (`crm_lead.py:153`, hard-coded) — confirm it stays 2h; consider lifting to an `ir.config_parameter` so it's tunable without code.
  - Forward-looking detection **needs a cron** (a stored compute can't fire on "time passed with no response"): a frequent cron (e.g. hourly) sets a new `x_sla_open_breach` (open lead, no `x_first_response_time`, `create_date` > 2h) — distinct from the existing retroactive `x_sla_breached`.
  - Manager view = a `crm.lead` list/pivot action filtered to breached, grouped by salesperson — **director/manager-gated** (group on the action).
- **Dependencies/sequencing:** none upstream; **prerequisite for #5** (provides the breach signal #5 rolls up).
- **Local build+test:** **requires cold-install chain.** Test: create a lead, leave unanswered >2h → cron flags open-breach; late first response → retroactive breach; confirm manager view lists+groups by rep.
- **Risk flag:** LOW–MEDIUM. New cron (keep its own idempotency + a tight domain so it doesn't churn). No state machine. Don't change the *existing* `x_sla_breached` semantics relied on by the alert ribbon — *add* the forward-looking field beside it.

## Item #1 — Live per-rep performance dashboard  *(establishes the per-rep aggregation layer)*

- **What it does:** a director-only view of **pipeline / win rate / conversion / activity by rep, side-by-side**, on live data.
- **Where it lives:** `neon_dashboard` — `models/neon_dashboard.py` (new block compute beside `_compute_sales_block:2233`; surfaced via `get_dashboard_data:531`), a new OWL block in the dashboard assets, director variant only.
- **What it touches:** dashboard data assembly + an OWL block component; `read_group` on `crm.lead` / `neon.finance.quote` / `mail.activity` grouped by `salesperson_id`/`user_id`.
- **Co-owned/shared:** ⚠️ **`neon_dashboard` is co-owned** and this touches **dashboard scope logic** (the very area the discovery flagged as inconsistent). ⚠️ **OWL assets** (the five-file scaffold discipline applies).
- **Key design decisions:**
  - Build a reusable `_compute_per_rep_*` helper (read_group by salesperson) — **#5 will reuse it**.
  - **Director-scoped only** — add to the director variant's block set, gated so individual reps cannot see the rep-vs-rep scoreboard (respect the existing variant/record-rule model; do NOT widen rep visibility).
  - Live-data caveat surfaced in the UI ("fills as the team works post-cutover").
  - Decide metrics per rep: open pipeline value, win rate (90d), conversion (won/total), activity (logged interactions / open activities).
- **Dependencies/sequencing:** after #3 (so activity/SLA signals exist); **prerequisite for #5** (shared aggregation). Meaningful only with live data.
- **Local build+test:** **requires cold-install chain.** Test: seed a few leads/quotes across 2+ salespeople → confirm the block splits by rep correctly and is director-only (a sales-rep login doesn't see it).
- **Risk flag:** MEDIUM. Touches the shared dashboard scope logic and OWL bundle. Keep the new block **additive** (new compute + new widget); don't refactor the existing team-wide tiles in the same change.

## Item #5 — Team follow-up compliance rollup  *(reuses #1 + #3)*

- **What it does:** a per-rep manager view of **who's behind on follow-ups / has breached SLA / has stale quotes** — the aggregation layer over what the crons already detect per-lead.
- **Where it lives:** `neon_dashboard` (a director block, reusing #1's per-rep helper) **or** `neon_crm_extensions` (a manager pivot). Recommend the dashboard block for a single oversight surface.
- **What it touches:** reads the per-lead signals the crons act on (`crm.lead` activities, `x_sla_breached`/`x_sla_open_breach`, `neon.finance.quote` stale/aging), aggregated by rep.
- **Co-owned/shared:** ⚠️ co-owned (`neon_dashboard` and/or `neon_crm_extensions`). Reads cron-produced per-lead state.
- **Key design decisions:**
  - **Reuse #1's per-rep aggregation helper** — don't duplicate.
  - Define "behind" precisely: open activities overdue, leads with `x_sla_open_breach`, quotes `sent`/`draft` older than the aging cutoff — counts per rep.
  - Read-only rollup (no new nudges — the crons already nudge individuals; this is the *manager visibility* layer). Director-scoped.
- **Dependencies/sequencing:** **depends on #1 (aggregation helper) and #3 (open-breach signal).** Build last of the dashboard trio.
- **Local build+test:** **requires cold-install chain.** Test: manufacture overdue activities / breaches / stale quotes across reps → confirm the rollup counts per rep match.
- **Risk flag:** LOW–MEDIUM (read-only aggregation). Main risk is double-maintaining aggregation if it doesn't reuse #1 — so reuse it.

## Item #2 — Rebuild per-rep intel boards (Win/Loss, Client Intel, Demand) on LIVE data

- **What it does:** make the three intel boards reflect **live post-cutover** performance, not just the historical Zoho archive.
- **Where it lives:** `neon_migration` — the compute layer (`scripts/compute_winloss_intel.py`, `compute_client_intel.py`, `compute_demand_intel.py`) currently reads `neon.finance.quote.archive` / `…invoice.archive` (e.g. `compute_winloss_intel.py:106-108`), keyed on `salesperson_display` *strings*. Plus the stored intel models + their recompute crons.
- **What it touches:** new/parameterized computes that read **live** `neon.finance.quote`, `crm.lead`, `account.move`, keyed on live `salesperson_id` (`res.users`) instead of archived name strings; either new `*.live` models or a `source` flag on the existing ones; new/extended recompute crons.
- **Co-owned/shared:** ⚠️ **`neon_migration` co-owned.** ⚠️ **recompute crons.** ⚠️ reads finance models via `sudo()` (cross-module read — keep the append-only/scoping discipline).
- **Key design decisions:**
  - **Keep historical and live separate** (don't overwrite the archive boards) — reps/managers need both "learn from history" and "live now". Likely parallel models or a `dataset = archive|live` dimension.
  - Re-key from `salesperson_display` (string) to live `user_id` — cleaner per-rep identity.
  - **#1's live per-rep dashboard is the better near-term per-rep tool;** this item is the *intel-board* equivalent and is lower urgency.
- **Dependencies/sequencing:** ⚠️ **GATED ON LIVE DATA.** Buildable now, but **meaningless until weeks/months of live quotes/invoices exist** post-cutover. Sequence after the dashboard trio; revisit once live data has accrued.
- **Local build+test:** **requires cold-install chain** + representative live-shaped data (hard to fake meaningfully). Test the compute logic on a small live-shaped seed; real validation waits for production data.
- **Risk flag:** LOW (additive, read-only computes) — but **don't disturb the existing archive computes/boards** (they're the historical coaching material). New crons must not collide with the existing recompute crons.

## Item #4 — "Copy Munashe on all client emails" compliance tracking  *(design-heavy; weakest-enforceable — do last)*

- **What it does:** surface whether client correspondence actually copies the MD.
- **Where it lives:** `neon_channels` (WhatsApp) + a new tracking model; possibly a light `mail.message` inspection in `neon_crm_extensions`.
- **⚠️ Hard truth from the read:** **most client email is almost certainly external (Gmail), not sent from Odoo** — the quote `action_send` is still a state-only placeholder (`neon_finance_quote.py:645` "P6.M8 wires the actual email"), and there is **no existing email-cc tracking anywhere.** So **Odoo cannot technically observe an out-of-system email's cc list.** Pure email-cc enforcement is **not feasible** for Gmail-sent correspondence.
- **Scoped approach (options, weakest→least-weak):**
  1. **In-Odoo only (partial):** if/when client comms are sent *from* Odoo (`mail.message`), check recipients include the MD and flag misses. Catches only Odoo-sent mail — likely a small fraction. Low value alone.
  2. **WhatsApp-assisted attestation/logging (the "WhatsApp connection"):** reps log/forward client comms through a WhatsApp lane (reusing `neon_channels` rails) so there's a record the MD is in the loop; or a periodic WhatsApp prompt for the rep to confirm compliance. Process-plus-tooling, not hard enforcement.
  3. **Honour-based + coaching (today's reality):** keep it a coached standard (the Director course teaches it); add only a periodic reminder.
- **Co-owned/shared:** ⚠️ **`neon_channels` / WhatsApp legs** (the most sensitive shared surface — message routing, `neon.bot.user`, send templates). New WhatsApp intents must be added to `wa_payload.INTENTS`.
- **Key design decisions (for Robin + Munashe + Tatenda):** decide what "compliance" can realistically mean given external email; whether a WhatsApp logging lane is worth the build; or accept honour-based + coaching. **This needs a product decision before any build.**
- **Dependencies/sequencing:** independent; **do last.** Needs the design decision above first.
- **Local build+test:** **requires cold-install chain** (neon_channels → neon_ai_core → chain) + WhatsApp test rig. Real test needs the WhatsApp legs — heavier, and gated by the standing WhatsApp/real-phone guardrails.
- **Risk flag:** ⚠️ **HIGH-sensitivity surface** (WhatsApp message routing + real-phone guardrails). Plus the honest expectation-setting that **no approach fully enforces external-email cc**.

---

## One-line dependency map
- **#3** → feeds **#5**.
- **#1** (per-rep aggregation helper) → reused by **#5**.
- **#5** depends on **#1 + #3**.
- **#2** independent but **gated on live data** (post-cutover).
- **#4** independent; **product decision first**, weakest enforcement, highest-sensitivity surface.

## Shared-surface review list for Tatenda (before any build)
1. **#1/#5 — dashboard scope logic** (`neon_dashboard`): per-rep block must be director-scoped; keep additive.
2. **#3/#2 — new crons**: idempotency + tight domains; don't collide with existing crons.
3. **#3 — `crm.lead` compute**: add forward-looking field beside the existing `x_sla_breached`; don't change its current meaning.
4. **#4 — WhatsApp legs**: highest-sensitivity; needs the product decision + respects real-phone/money guardrails.
5. **All five** require the cold-install chain (or a warm DB) to test → clearing PROGRESS #3 helps here.
