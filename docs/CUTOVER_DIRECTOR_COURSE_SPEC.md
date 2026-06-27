# Cutover — Director (MD) · Course Build Spec

**For:** Claude Code — build as a third plain `website_slides` course in `neon_cutover_courses` (same pattern: plain channel, native completion, `noupdate=0`, seeded **unpublished**).

**For:** Munashe — MD, highest-earning salesperson, sales line manager (team reports to her), and the team's main teacher. So this course serves four roles at once: top sales operator, approver, manager/coach, and trainer-of-others. Standalone course (reuses verified Sales content for the sales-mastery section).

**Not July-1-critical** — Munashe comes after the Finance + Sales cutover. Build it right rather than rushed.

**Gates before publish:**
- Sales-mastery section (Section 3) reuses the Sales course content, which itself holds on its two gates (rep-screen verification — *which Munashe runs* — + discount threshold she confirms).
- Director-specific sections (1, 2, 4, 5) verified against Robin's superuser view (which == her director view) + the read-only sales-management discovery (27 Jun 2026).

**Course title:** `Cutover — Director` · Enrolment: invite/internal, attendee Munashe.
**Structure:** Sections 1–5 → Knowledge check → Director Sign-off.

---

## Course description (paste)

Your orientation to the whole Neon ERP as Managing Director — how to see the business, approve what needs your sign-off, sell within the system as our top salesperson, and oversee and coach the sales team. Work each part against the live system.

---

## Section 1 — The whole-system map (your MD orientation)

Orient to what exists and where it lives. You don't operate every area, but as MD you should know the shape of the system:
- **CRM / Sales** — leads, pipeline, quotes (where you and the team sell).
- **Finance** — quotes→invoicing, payments, bank statements, reports (Kudzaiishe's domain; you oversee disbursements).
- **Operations / Jobs** — events, crew, equipment, the workshop (you're not involved in crew/equipment selection — this runs without you).
- **WhatsApp arm** — the business runs a lot through WhatsApp: client intake, crew coordination, quote-by-WhatsApp, approvals (incl. yours).
- **Dashboards & Intelligence** — your command centre + the sales-intelligence boards (Section 5).
✅ Done when: you can name the major areas and what each is for.

## Section 2 — Your Director Dashboard (your command centre)

Your dashboard is your daily business-at-a-glance. *(Verified against the live director view.)*
- **KPI tiles:** Pipeline Value, New Leads, Hot Deals, Aging Quotes, Won This Month, Win Rate (90d). *(Note: these tiles are **team-wide** — they show the whole company's numbers, not just yours.)*
- **Filter chips:** All / Hot / Aging / Won.
- **Pipeline by Stage**, **Win Rate**, **Lead Sources**.
- **Alerts** — as a director, this shows **all reps'** overdue invoices and stale quotes (a rep sees only their own). Your team-wide warning feed.
- **Hot Deals Watch**, **Aging Quotes** — deals needing a push.
- **Tasks** — your to-dos, including escalations routed to you (Section 5).
- **AI Insights** + **AI Copilot** (chat) — ask questions, get narrative insights; the Copilot can log leads, move stages, update values (with a confirm step).
✅ Done when: you can read your dashboard and know the tiles are team-wide.

## Section 3 — Selling in the system (sales mastery)

As our top salesperson you use the full sales workflow at mastery level. This is the **same content as the Sales course** — capturing leads, working the pipeline (New → Proposal Sent → Negotiation → Closed Won/Lost → Payment Pending Verification), logging interactions, raising catalogue-priced quotes, confirming logistics before sending, finding your quotes, the discount rule, and the culture standards (incl. the **2-hour** response standard, formal English, never quote verbally, copy yourself on… — see note). Reuse the verified Sales course steps A2/B1–B6/B4a + C here.
*(Build note: pull the Sales course content into this section rather than rewriting.)*
✅ Done when: you can run the full sales workflow independently.

## Section 4 — Your approvals & oversight

**D1 · Approving quotes** — when a rep submits a quote you're notified by **email or WhatsApp**.
- **Email:** the notification links to the quote; review and **approve/decline** there.
- **WhatsApp (live):** ask for a view of the quote, get a prompt to approve/decline, type your response.
Your approval is the gate between a drafted quote and one the client sees.

**D2 · Discount sign-off** — over-threshold discounts come to you the same way; reps can't apply them without your sign-off.

**D3 · Money oversight (disbursements / UF)** — disbursements flow from you. *(The full Undeposited-Funds module isn't in Odoo yet — you continue overseeing disbursements as you do now until it's built; when UF lands, this is where you'll do it.)*
✅ Done when: you can approve/decline a quote (email + WhatsApp) and a discount, and you understand your disbursement-oversight role.

## Section 5 — Overseeing & coaching your team

Know which tools show **live** activity and which show **historical** patterns — this is the most important distinction in your oversight.

**D5.1 · Live oversight (real-time, today):**
- **Native CRM grouped by Salesperson** — open Pipeline / quote lists, group by salesperson → a live per-rep view of who's working what. Generic Odoo, but real and live. *(This is your live per-rep tool — there isn't a bespoke per-rep scoreboard yet.)*
- **Director dashboard** — team-wide totals + the **alert feed** (all reps' overdue invoices & stale quotes).
- **Your escalation queue (Tasks)** — deals 7 days with no movement, and un-followed-up quotes, escalate as to-dos **to you**. Work this as your early-warning queue.
- **Feedback Insights** (`/neon/insights`, manager-only) — **live** client-satisfaction timelines, sentiment, recurring-concern flags. Your client-health coaching tool.
- *Live data grows from cutover:* as the team works post-July-1, the live views fill with real activity.

**D5.2 · Historical coaching material (the last two years — pattern-spotting, NOT live scorekeeping):**
- **Win/Loss & Realisation by rep** — historical win rates / realisation per salesperson.
- **Client Intelligence** — per-client value, win rate, segment.
- **Demand & Seasonality** — when business comes, recurring events.
- *(These read the pre-cutover archive. They won't reflect live post-July performance until rebuilt on live data — a planned build. Use them to coach on patterns and learn from history.)*

**D5.3 · Your approval controls** *(see Section 4)* — quote + discount sign-off are real, live manager controls.

**D5.4 · What the system does NOT yet track — coach these directly:**
- **First-response time** — the system flags first response at **2 hours** (matching the standard), but per-lead only, retroactively, with **no manager rollup/breach view per rep**. You can't yet see "who's slow" at a glance — coach it, a manager-view build is planned.
- **"Copy Munashe on all client emails"** — not system-monitored; honour-based (tracking build planned).
- **Logistics-confirmed-before-quote** — not yet a system gate (planned build).
- **Soft standards** (never quote verbally, formal English, same-day logging) — coaching / spot-check.
✅ Done when: you know your live oversight tools, your historical coaching boards, your approval controls, and which standards you coach directly because the system doesn't track them yet.

---

## Knowledge check (Quiz) — ✅ = correct

**Q1. Your dashboard's KPI tiles show…**
- Only your own deals
- **The whole team's numbers — the tiles are team-wide ✅**
- Nothing until you filter

**Q2. A rep submits a quote needing approval. How can you approve it?**
- Only by logging into a computer
- **By email (link to the quote) or WhatsApp (ask for a view, reply to approve/decline) ✅**
- It approves automatically

**Q3. You want a live, per-rep view of who's working what. Where?**
- The Win/Loss-by-rep board
- **Native CRM Pipeline / quotes, grouped by Salesperson ✅**
- The historical Client Intelligence board

**Q4. The Win/Loss-by-rep and Client Intelligence boards show…**
- Live current-month performance
- **Historical patterns from before cutover — for coaching and learning, not live scorekeeping ✅**
- Real-time team activity

**Q5. The system tracks each rep's 1-hour response compliance for you.**
- True — there's a per-rep breach dashboard
- **False — first-response flags at 2 hours, per-lead, with no manager rollup yet; you coach response time directly ✅**
- True — the AI Copilot reports it hourly

**Q6. Disbursements / Undeposited Funds oversight in Odoo today —**
- Fully built; you manage UF in the system now
- **The UF module isn't in Odoo yet; you oversee disbursements as you do now until it's built ✅**
- It's automatic, no oversight needed

---

## Final slide — Director Sign-off (Director)

**Title:** Director Sign-off — Director

Completed by a director, confirming Munashe can read the director dashboard, approve quotes and discounts (email + WhatsApp), run the full sales workflow, and oversee/coach the team using the live tools (native grouped CRM, alert feed, Feedback Insights, escalation queue) and historical boards — and that she knows which standards the system doesn't yet track and must be coached directly.

When marked complete, Director onboarding is signed off and recorded.

---

## Build & gate notes for Claude Code

- Third course in `neon_cutover_courses`, plain `website_slides`, `noupdate=0`, seeded **unpublished**.
- Section 3 reuses Sales course content — pull it in, don't rewrite (keep a single source of truth for the sales steps).
- **No Ranganai anywhere.**
- Verified against the director/superuser view + the 27 Jun read-only sales-management discovery. The "does NOT track" items (D5.4) are deliberately honest — do not soften them into implying the system enforces these.
- Local test + idempotency like the other seeds. No prod deploy without a separate gated GO; director reviews the rendered course before publish.

## Cross-course correction triggered by this work

**Response standard changed 1-hour → 2-hour** (aligns the taught standard to what the system measures). This must also be fixed in the **already-built Sales course seed** (`data/cutover_sales_course.xml`): C1 "respond within 2 hours" and Q5 answer "2 hours". Add to the Sales course's pre-publish fix list.
