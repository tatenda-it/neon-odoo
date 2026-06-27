# Cutover — Finance · Verified Course Build Spec

**For:** Claude Code — build this as a plain `website_slides` course on the live LMS (no neon_lms track/cert machinery, no neon_branded flag — plain course, native completion tracking). Authored content below is verified against the live system on 27 June 2026 with Robin (every system-task step was checked on screen, not inferred).

**Course title:** `Cutover — Finance`
**Attendee:** Kudzaiishe (Bookkeeper). Enrolment: invite/internal, not public.
**Structure:** Sections A / B / C → Knowledge check (quiz) → Director Sign-off (final slide). Course reaches 100% only when the Director Sign-off slide is marked complete by a director = self-completed + director-attested.

---

## Course description (paste)

Your get-ready guide for the 1 July cutover, covering the finance functions that are **live today**. Work each step against the real system — every item is "can you actually do this," not "did you read it." When you and a director have signed off, you're cleared to operate.

⚠️ **Scope — what this course does NOT cover (deferred, by design):** the full Undeposited-Funds routing module, the restricted-cash tiers (Special Account / Tithe / Drawings / Owner-Personal UF), bank reconciliation, and interpreting financial reports. These are either not yet built or are end-of-July activities once real transactions exist. We only train what's live and usable on 1 July.

---

## Section A — Get in & oriented

**A1 · Log in & confirm your dashboard**
Go to crm.neonhiring.com, log in with the address IT gave you, set a strong password on first login, and confirm your Bookkeeper dashboard loads. If anything doesn't load, flag Robin or Tatenda now — before cutover.
*Note: until cutover, some dashboard figures are sample data; they become real as we go live.*
✅ Done when: logged in, password set, dashboard visible.

**A2 · Read your dashboard**
Your dashboard shows your finance picture — cash position, the USD and ZiG journals, customer invoices, vendor bills, undeposited funds and petty cash cards.
✅ Done when: you can find your dashboard and explain what the cards show.

**A3 · Your two workspaces — Accounting and Statements**
Your sidebar is set up with your accounting tabs. You'll spend most of your time in two:
- **Accounting** opens the Accounting Dashboard — the cards for Customer Invoices, Vendor Bills, your bank accounts (CABS USD, CABS ZWG), Undeposited Funds and Petty Cash. This is where you raise invoices, handle bills, and reconcile.
- **Statements** opens **Account Ledgers** — open a statement on any account (CABS USD, CABS ZWG, Petty Cash) to see its running balance and entries.
Use **Accounting** to *do* things; use **Statements** to *read* an account's running ledger.
✅ Done when: you can open both, and know which you use for what.

---

## Section B — Core daily finance tasks (what's live)

**B1 · Invoice from an accepted quote (schedule-driven, on request)**
You don't raise or approve quotes — that's the Sales side (the salesperson, who may be a director). Your finance work begins once a quote is **Accepted**.
- You don't manually "convert" a quote, and you don't invoice automatically the moment it's accepted. Each quote has an **Invoice Schedule** tab with one or more lines (e.g. *Final Balance, 100%, trigger: On Quote Acceptance*). When the quote reaches the triggering stage (**Accepted**), the system **auto-generates a Draft Invoice** — shown as a link like *"Draft Invoice (SCH-000003)"* in the schedule row.
- **You finalise on request, not on autopilot.** The salesperson handling the deal (may be a director — directors also do sales) tells you when to invoice. Events often have extras added or deductions made on the day, so the draft amount may not be final — only post when asked and the figure is confirmed.
- To finalise: open the **Draft Invoice** link from the Invoice Schedule row, **review** it (figures, currency, VAT treatment, the ZIMRA strip on the PDF), then **confirm/post** it.
- Read the quote's own **Payment Terms** and **VAT treatment** — both are set per quote/client (e.g. "no deposit / 7d final"); check, don't assume.
*Note: a standalone "New" invoice exists as a rare safety-net only — don't create one unless a director tells you to.*
✅ Done when: you can find an accepted quote's auto-generated Draft Invoice in its Invoice Schedule, confirm the amount reflects any extras/deductions, check its VAT treatment, and review + post it — on request, not automatically.

**B2 · Record a customer payment / receipt**
When money comes in, record it against the invoice. Two ways, both available:
- On the posted invoice, use **Register Payment** — the normal route when a client pays a specific invoice.
- From the Statements / account side, use the **Add-Transaction** quick entries — for recording receipts and moving money between accounts.
Receipts come in as cash or bank deposit and route through **Undeposited Funds** the way you already handle it — UF is the central account money passes through before it's settled to its final account (Petty Cash for operating float, etc.). Record the receipt into the right account and route through UF as you do today.
✅ Done when: you can record a customer payment against an invoice (via Register Payment and via Add-Transaction), and you know where UF sits in the flow.

**B3 · Recording expenses and money out**
Alongside receipts, you record money *going out* — expenses, replenishments, vendor payments, transfers between accounts — through the quick-entry transactions on the cash/bank accounts. You can create a new expense entry whenever one is needed. You already know these movements from running the books; this is just doing them in Odoo.
✅ Done when: you can record an expense / money-out entry in Odoo.

**B4 · Import a CABS bank statement (CSV)**
You import CABS statements as **CSV files** (CSV only — a PDF or Excel statement won't import). Works for both **CABS USD** and **CABS ZWG** (tested). Export the statement from CABS as CSV and import it; the lines appear in that account's statement under **Statements → Account Ledgers → Open Statement**, as a running ledger (Date, Details, Dr, Cr, Balance).
✅ Done when: you can import a CABS CSV (USD or ZWG) and see its lines in the account's statement.

**B5 · Financial reports — know where they are**
Odoo has your financial reports — **P&L, Balance Sheet, Cash Flow** — in both **USD and ZWG** (under Reporting). You won't use these much at first, because accounts start fresh on 1 July and there's little to report yet. For now: know they exist and how to open them, for when transactions have built up.
✅ Done when: you can find the reports and open one — knowing real reporting starts once there's activity.

**B6 · The USD↔ZWG rate on an invoice**
When invoicing across currencies, you set the **exchange rate on that invoice** — same idea as you've done manually before, now in Odoo. The rate applies to that invoice. Make sure you're using the correct rate for the day before you finalise.
✅ Done when: you can set the USD↔ZWG rate on an invoice and know to use the correct day's rate.

**B6b · Setting the rate for a report (global)**
Separately from the per-invoice rate, when you run a report across currencies you can set a **global rate that drives the conversion for the whole report**. Because it affects the entire report, **always get the rate confirmed by a director (Robin or Munashe) before you set it** — you enter it, but the number must be director-authorised. Never set the report rate from your own guess.
✅ Done when: you know the report rate is global and that you only set it with a director-confirmed figure.

**B8 · Weekly cash-planning sheet**
Open the **Weekly Budget** from your sidebar — your planning sheet for the week's cash, money in and money out. You receive requests, plan purchases, and work the week's expected inflows and outflows here. It's a planning tool (not the ledger itself); use it to stay ahead of the week.
✅ Done when: you can open the Weekly Budget and add/work a week's planned money-in and money-out.

**B9 · Outstanding payments (AR) — your oversight tool**
Open **Collections** from your sidebar — the **Outstanding Payments** worklist: every open client balance with the amount owed, the **Sales Rep** responsible, the contact, and a **status** (Chasing, Promised, Part Paid, PO Submitted, Cleared, Unresolved), with a running total.
Your role is oversight and backup: the named Sales Rep owns chasing their client; you make sure that's happening, and step in to chase directly when a rep needs help. You're the safety net, not the first chaser.
✅ Done when: you can open Collections, read who owes what and which rep is responsible, and you understand your job is to ensure follow-up happens (and assist when needed).

*(Note: B7 from the original draft — the quote→approval→schedule flow — is folded into B1. No separate step.)*

---

## Section C — Currency & compliance

**C1 · USD vs ZiG — always be explicit**
Always know which currency you're working in. Quotes are currency-locked; invoices carry their currency; you set the rate per-invoice when converting (B6). Never assume — check on every quote, invoice, and entry.
✅ Done when: you check currency on everything you touch.

**C2 · VAT & ZIMRA**
- VAT, when it applies, is **15.5%** — but whether VAT is charged is decided **per client**. Some clients are invoiced including VAT, some excluding. Always check; never assume.
- Invoices carry **ZIMRA registration** (on the invoice PDF).
✅ Done when: you know the rate is 15.5% when it applies, that VAT-or-not is per-client, and that ZIMRA registration is on invoices.
*(No payment-terms line — terms are per-quote, covered in B1; there is no flat default.)*

**C3 · Append-only — corrections are reversals**
You never delete a posted financial entry. To fix a mistake you **reverse and re-enter** using the **"Correct this entry"** flow (live and tested), leaving a clean audit trail. Nothing posted just disappears.
✅ Done when: you understand corrections are reversals via "Correct this entry," never deletions.

---

## Knowledge check (Quiz) — ✅ = correct

**Q1. How is VAT applied to invoices?**
- Always 15.5% on every invoice
- **15.5% when it applies — but whether VAT is charged is decided per client, so you check each one ✅**
- Never charged

**Q2. A quote reaches "Accepted." How do you invoice it?**
- Click "New Invoice" and rebuild it from scratch
- **Open the quote's Invoice Schedule, find the auto-generated Draft Invoice, confirm the amount reflects any extras/deductions, then review and post — when asked to ✅**
- It invoices itself automatically and sends; nothing for you to do

**Q3. You spot a mistake in a posted entry. What do you do?**
- Delete it and re-enter
- **Reverse it and re-enter using "Correct this entry" — finance is append-only ✅**
- Edit the posted line directly

**Q4. Setting the exchange rate — which is true?**
- The rate I set on an invoice changes every conversion in the system that day
- **The rate I set on an invoice applies to that invoice; the global report rate is different and I only set that with a director-confirmed figure ✅**
- I should never touch any rate

**Q5. In Collections (Outstanding Payments), whose job is it to chase a client?**
- Always mine
- **The named Sales Rep owns the follow-up; I make sure it's happening and step in to help when needed ✅**
- Nobody — it clears itself

**Q6. Where do imported CABS statement lines appear?**
- Posted straight into the ledger as final
- **In the account's statement under Statements → Account Ledgers, as a running ledger ✅**
- In the weekly cash sheet

**Q7. What must every invoice carry?**
- The director's signature
- **ZIMRA registration ✅**
- Nothing specific

---

## Final slide — Director Sign-off (Finance)

**Title:** Director Sign-off — Finance

This step is completed by a director (Robin or Munashe), confirming Kudzaiishe can independently invoice from an accepted quote, record payments, record expenses, import a CABS statement, set per-invoice rates correctly, work the weekly cash sheet, and oversee Collections — and understands the currency, VAT-per-client, and append-only rules.

When a director marks this slide complete, Finance cutover onboarding is signed off and recorded. Kudzaiishe is cleared to operate on the live system.

---

## Build notes for Claude Code

- Plain `website_slides` course; confirm on first build that a plain new channel (no `neon_branded`/track flag) renders as stock eLearning (no Workshop hero / track cards / capstone band).
- Section A/B/C as sections; each step a slide (Article/Web Page); the quiz as a Quiz slide; Director Sign-off as the final content slide.
- Completion tracked natively via `slide.channel.partner`. Course = 100% only when all slides done + quiz passed + Director Sign-off marked → self-completed AND director-attested.
- Enrolment invite/internal, attendee Kudzaiishe.
- This content is verified against live prod (27 Jun 2026). The deferred items (UF routing, restricted-cash, reconciliation, report interpretation, global daily-rate-table as director action) are deliberately excluded — do not add them.
- Do not deploy/publish without a separate GO; a director verifies the built course before it's published to the attendee.
