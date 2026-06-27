# Tatenda — Start Here Worklist

**The single pickup doc when you're back online.** Consolidates every open build/fix/reconcile from this session's work, with dependencies and shared-surface flags. Detailed designs live in `docs/SALES_MGMT_BUILD_PROPOSALS.md` (the 5 sales-mgmt builds) and the session chat (logistics gate). Branch: `feat/wa6-equipment-face` (local, **nothing pushed** — 14 commits ahead of origin).

**Legend:** 🟢 ready-to-start · 🔴 blocked-on-prerequisite · ⚠️ touches a co-owned / shared surface (review before building).

---

## 0. Prerequisite that unblocks almost everything

> **Two distinct tasks — don't conflate them:**
> - **Local sandbox unblock — ✅ DONE (Robin, this session).** `neon_db` has all 30 neon modules installed and a working login (`robin@neonhiring.co.zw`), achieved via **DB-only menu seeds** (scratchpad scripts, *outside the repo* — no source edits). **These seeds must be re-run on any fresh rebuild** until the source is hardened. This unblocks development/testing *now*.
> - **P0 below — the permanent source fix — STILL PENDING (Tatenda).** The seeds work around the bug; they don't remove it.

**P0 · Cold-install hardening (multi-module manifest load-order)** 🟢
- **What:** harden manifest data load-order so **menus are defined before they're referenced**, across **every affected module — not just `neon_training`**. Confirmed in `neon_training` (`menu_neon_training_root` referenced by a wizard view at manifest pos 25, defined at pos 26) **and `neon_hr`** (`menu_neon_hr_root` referenced by `neon_hr_review_views.xml` before definition). A generic local pre-seed pass had to create **52 menu xmlids across multiple neon modules** to get a cold install through — so treat this as a **suite-wide load-order audit**, not a single-module fix. The `validity_months` typo + the `neon_base` Option-3 shim are already committed locally.
- **Where:** `neon_training`, `neon_hr`, and any other module surfaced by the audit (each module's manifest `data` order — define the menu file before view/wizard files that reference its menus) ⚠️ co-owned, multi-module.
- **Why it matters:** these forward-refs only bite on a **cold/fresh install** (masked by warm `-u`). Affects disaster recovery / clean rebuilds / any new dev box. The local sandbox is already working via the DB seeds above, so this is **no longer blocking development** — but it is the real fix.
- **Also fold in:** the held, uncommitted `neon_banking_labels/__manifest__.py` dep edit (adds `neon_finance`+`neon_core`) — decide commit vs the proper structural fix.
- **Dependency:** none. High value (every fresh install), but **not blocking** now that the sandbox is seeded.

---

## 1. The five sales-management builds  (full design: `docs/SALES_MGMT_BUILD_PROPOSALS.md`)

Recommended internal sequence **#3 → #1 → #5 → #2 → #4**.

**#3 · First-response SLA fixes** 🔴(needs P0 to test)
- **What:** confirm the 2-hour threshold; add **forward-looking** open-breach detection (flag still-unanswered leads, not just retroactive); add a **per-rep manager breach view**.
- **Where:** `neon_crm_extensions` — `crm.lead` compute + a new cron + a manager list/pivot. ⚠️ co-owned `crm.lead`; ⚠️ **new cron**.
- **Dependency:** P0. **Feeds #5.** Self-contained otherwise — good first real build.

**#1 · Live per-rep performance dashboard** 🔴(P0)
- **What:** director-only pipeline / win-rate / conversion / activity **by rep, side-by-side**, on live data (today `_compute_sales_block` does stage/source only — net-new per-rep aggregation).
- **Where:** `neon_dashboard` — new block beside `_compute_sales_block` + OWL widget, director variant only. ⚠️ **dashboard scope logic**; ⚠️ OWL assets.
- **Dependency:** after #3. **Build the per-rep aggregation helper here — #5 reuses it.** Meaningful only with live (post-cutover) data.

**#5 · Team follow-up compliance rollup** 🔴(needs #1 + #3)
- **What:** per-rep manager view of who's behind on follow-ups / breached SLA / stale quotes (manager aggregation over what the crons already flag per-lead).
- **Where:** `neon_dashboard` director block (reuse #1's helper). ⚠️ co-owned; reads cron-produced per-lead state.
- **Dependency:** #1 (aggregation) + #3 (open-breach signal). Read-only rollup.

**#2 · Rebuild per-rep intel boards on LIVE data** 🔴(gated on live data)
- **What:** make Win/Loss, Client Intel, Demand reflect live post-cutover performance (today they read the Zoho archive, keyed on `salesperson_display` strings).
- **Where:** `neon_migration` computes (`scripts/compute_*_intel.py`) → read live `neon.finance.quote`/`crm.lead`/`account.move` keyed on live `salesperson_id`; keep historical + live **separate**. ⚠️ co-owned; ⚠️ **recompute crons**; reads finance via sudo.
- **Dependency:** **GATED — meaningless until weeks/months of live data accrue.** #1 is the better near-term per-rep tool. Revisit post-cutover.

**#4 · "Copy Munashe on all client emails" compliance** 🔴(blocked on Outlook — see I1) — *CORRECTED*
- **What:** ~~honour-based/unenforceable~~ → **once Outlook is connected (I1), client email flows through Odoo as `mail.message`, so this becomes a real build:** check client-email recipients include the MD and flag misses; optional WhatsApp surfacing of misses.
- **Where:** `neon_crm_extensions` / `mail.message` inspection + optional `neon_channels` surfacing. ⚠️ **WhatsApp legs** if surfaced there.
- **Dependency:** **blocked on I1 (Outlook→Odoo).** Do after the connection exists.

---

## 2. Logistics-confirmed-before-send gate  — *CORRECTED: mandatory line, no waiver*

**C · Logistics gate** 🔴(P0 to test) ⚠️⚠️
- **What:** a quote cannot be **sent** to a client unless a **LOGISTICS line is present with a positive amount**. **Decision made: the logistics line is MANDATORY on every quote — no "not applicable"/waiver path** (drop the previously-proposed `logistics_not_applicable`/reason fields).
- **Concretely:** `logistics_confirmed` = any `line_ids` whose `product_template_id.is_logistics` and line total > 0. Gate inside **`action_send`** (approved→sent): `if not rec.logistics_confirmed: raise UserError(...)`. No new state, no changed transition.
- **Where:** `neon_finance` — `action_send` (`neon_finance_quote.py:642`) + computed `logistics_confirmed` on `neon.finance.quote`; new `is_logistics` Boolean on `product.template`; quote-form indicator.
- **Shared surfaces (Tatenda review BEFORE build):** ⚠️ **`action_send` is the shared quote state machine.** ⚠️ **WA-12 send-leg** (`_wa12_handle_send_to_client`) routes through `action_send` — so the gate covers WhatsApp too, but the WA leg must present the refusal gracefully (touches `neon_channels`).
- **Sequencing trap:** ship the `is_logistics` field + **mark the real LOGISTICS product `is_logistics=True` on prod FIRST**, then enable the block (else it has nothing to detect / blocks everything).
- **Dependency:** P0 to test. Decision locked → ready to build once shared surfaces reviewed.

---

## 3. Integration prerequisite

**I1 · Microsoft Outlook → Odoo connection** 🟢 — *NEW (prereq for #4)*
- **What:** connect Outlook so client email is sent/received through Odoo (Odoo's Microsoft Outlook / OAuth mail integration). Makes client email visible as `mail.message` — which is what turns #4 from unenforceable into a real build.
- **Where:** Odoo mail/Outlook integration + config (largely setup/OAuth; minimal custom code). ⚠️ touches outbound/inbound mail routing.
- **Dependency:** none to start; **prerequisite for #4.**

---

## 4. Reconciles & hygiene

**R1 · Banking "DEV-ONLY" vs actually-installed reconcile** 🟢
- **What:** banking modules (`neon_banking_*`, `neon_mis_reports`, `neon_weekly_budget`, UI-shell) are tagged "DEV ONLY, no prod" in history but are `installed` on prod (PROGRESS #1). Reconcile "what we think we deployed" vs reality.
- **Where:** records/process + commit-history check; no code per se. **Dependency:** none.

**R2 · `neon_status` board drift** 🟢
- **What:** the `/neon/status` narrative doesn't track the banking modules as live and omits the onboarding/cutover work (PROGRESS #2).
- **Where:** `neon_status` (hardcoded Python constants in `controllers/main.py`) ⚠️ co-owned; updating it is a code change + **gated prod deploy.** **Dependency:** none.

**R3 = P0** (neon_training cold-install hardening — listed at top as the prerequisite).

---

## 5. Cutover-course pre-publish fixes  (module `neon_cutover_courses` — all three courses seeded UNPUBLISHED)

**F1 · Sales course 1h → 2h** ✅ DONE
- **What:** the Sales seed now reads "2 hours" in C1 + Q5 (matches system SLA + agreed standard) — applied + verified (clean/unpublished/idempotent) this session.
- **Where:** `neon_cutover_courses/data/cutover_sales_course.xml`. **Remaining Sales pre-publish gates: rep-screen verification + Munashe's discount threshold.**

**F2 · Discount-figure sync coupling (Sales + Director)** 🔴(blocked on Munashe)
- **What:** when Munashe confirms the discount threshold figure, fill it into the Sales seed (B6/C2/Q4) **and** the Director seed (Section 3) — they're separate copies (plain website_slides can't share slides across channels).
- **Where:** `neon_cutover_courses` (both `cutover_sales_course.xml` + `cutover_director_course.xml`). **Dependency:** Munashe's confirmation.
- **Related gates (not Tatenda's):** Sales rep-screen verification (Munashe runs); Director Section 3 inherits the Sales gates.

---

## Recommended order to actually work them

1. **P0** — cold-install / sandbox unblock *(unblocks testing of everything below)*.
2. **F1** — Sales 1h→2h *(2-minute fix, no cold-install needed, clears a pre-publish item)*.
3. **C** — logistics gate *(decision locked, mandatory-line is simpler; review `action_send` + WA-12 first)*.
4. **#3** — SLA fixes *(self-contained, feeds #5)*.
5. **#1** — per-rep dashboard *(builds the aggregation helper)*.
6. **#5** — follow-up rollup *(reuses #1 + #3)*.
7. **I1** — Outlook connection *(can run in parallel anytime; unblocks #4)*.
8. **#4** — email-cc compliance *(after I1)*.
9. **R1 / R2** — banking reconcile + status-board drift *(hygiene; fit in anytime)*.
10. **#2** — live intel rebuild *(post-cutover-gated; revisit once live data accrues)*.
11. **F2** — discount-figure sync *(when Munashe confirms)*.

**Blocked-on-prerequisite right now:** #1/#3/#5/#2/C (need P0 to *test*), #4 (needs I1), F2 (needs Munashe).
**Ready-to-start with no prerequisite:** P0, F1, I1, R1, R2.
