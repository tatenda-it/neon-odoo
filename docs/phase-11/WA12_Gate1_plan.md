# WA-12 — Quote-by-WhatsApp · Gate-1 design plan

**Status:** DESIGN ONLY — ⛔ holds for (a) Gate-1 review (assistant + Tatenda)
AND (b) Robin's explicit sign-off (first money-adjacent WhatsApp feature).
Build proceeds after review; **LIVE switch-on waits for the pricing load + a
staged handset proof** (`[TEST-WA12]`, requester + approver phones, full
teardown). Drafted 2026-06-11.

Companion: [[project_wa12_quote_by_whatsapp_queued]] (memory), the WA-12
amendment (MD/OD approval flow), the Phase-11 pricing-capture sheet
(`WA12_pricing_capture_sheet.md`).

---

## 1. Principle — encode onto the REAL lifecycle, invent nothing

**⭐ BINDING (Tatenda, confirmed): the entire quote loop is WHATSAPP-NATIVE.**
Draft AND approved quotes are visible/actionable on WhatsApp (the PDF is the
visible artifact); **Odoo is the system of record, never a required screen** —
no one must open Odoo to see, approve, or send a quote. The draft PDF renders at
`submit_for_approval` time and is available on-demand to the approver; the final
PDF lands in the requester's chat on approval.

WA-12 is a **WhatsApp skin over the existing `neon.finance.quote` state
machine**, not a parallel flow. Verified states:
`draft → pending_approval → approved → sent → accepted/…` with
`action_submit_for_approval` / `action_approve` / `action_reject` /
`action_send` / `action_accept` / `action_cancel`, plus
`action_recalculate_pricing` and the payment-term wizard. Quote lines price as
**`quantity × unit_rate × duration_days × bracket_multiplier`** — so the
team's day-rate sheet feeds `unit_rate` directly; `line_type` already supports
equipment / labour / service. Approval is config-gated by
`neon_finance.approval_required_for_all` (default **True** → every quote routes
through `pending_approval` + a `neon.finance.approval` record + approver
activities). WA-12 layers the MD/OD WhatsApp tap on top of that gate — it
**honours** the gate + the append-only `perm_unlink=0`, never bypasses them.

## 2. Flow (onto the states)

| Step | WhatsApp | Odoo |
|---|---|---|
| 1 | Sales texts `Quote: <client> — <items/dimensions>, <date>` | — |
| 2 | parse lane → client + items + optional date | WA-9 `_wa9_match_partner` → `partner_id` (else human-qualify) |
| 3 | (optional) availability check for the date | reuse WA-8 read-only engine (no hold) |
| 4 | bot echoes the parsed draft for confirm | `neon.finance.quote` created (partner_id) + `quote.line` rows (product_template_id, quantity, **unit_rate from the price list**, duration_days, line_type); `payment_term_id` set (required to submit) |
| 5 | requester confirms → submit; **draft PDF rendered now (on-demand)** | `action_submit_for_approval` → **pending_approval**; render the draft QWeb PDF |
| 6 | **approval ping to MD/OD (uids 7 + 21)** — summary + total + **[Approve] [Reject] [📄 View PDF]** | the `neon.finance.approval` record + approver activities exist already |
| 6b | **[📄 View PDF]** → bot sends the **draft quote PDF into the approver's chat** (in-window) | `send_document` (draft PDF, Meta `/media`) |
| 7a | **[Approve]** (first-tap-wins; other notified — WA-10 dedupe) → approver gets **"approved ✓"**; **final PDF → requester's WhatsApp + [Send to client]** | `action_approve` → **approved**; render final PDF → `send_document` to the requester |
| 7b | **[Reject]** → bot prompts for a comment → comment relayed to the **requester** | `action_reject(comment)` → back to **draft** |
| 7b-edit | **v1 edit path = requester re-texts a corrected `Quote: …` request** (conversational in-place line-editing = **phase 2**, logged) | a fresh draft |
| 8 | requester taps **[Send to client]** → sales sends | email the client (SMTP) → `action_send` → **sent** |

**Self-approval exemption:** when the requester **is** MD/OD, step 6's ping
collapses into their **own confirm tap** (no separate approver ping) — they
approve their own draft in one step.

**Honest authorship throughout:** every tap acts via `with_user(real_tapper)`
(resolved phone → bot.user → res.users), never bare sudo; the approval gate +
audit trail attribute to the real MD/OD.

## 3. Footprint (estimate — confirm at Gate-1 review)

| Area | Work | New? |
|---|---|---|
| `neon_channels` parse + dispatch | tight `Quote:` command parser (equals/startswith, false-positive test); the approval-ping + View-PDF + requester-return legs; session steps (`q_*`); intents `wa12_approve` / `wa12_reject` / **`wa12_view_pdf`** / `wa12_send` → `wa_payload.INTENTS` | new |
| `neon_channels` first-tap-wins | advisory lock (fresh namespace, e.g. `5593900`) + WA-10 dedupe shape for the approver pair | new |
| `neon_finance` quote build | helper to create quote + lines from the parsed payload + per-product rate lookup + duration mapping ("for N days" → `duration_days`); **LED = named size-variant match only** (ruling 3 — "3×2m" → the named product, else list sizes + ask; NO per-m²) | new helper |
| `neon_crew_comms` "Price:" face | read-only `Price: <item>` → rate + currency + per-day note; **WA-8 entitlement rail, NO approval, NO quote record** (ruling 4) | **new** |
| **QWeb quote PDF report** | a report on `neon.finance.quote` (none exists today; the invoice report does) — renders **state-stamped** (DRAFT at submit, final on approval); used by both legs | **new** |
| `send_document` outbound | new send type on `neon.whatsapp.message` (inbound already recognises `document`); **Meta `/media` upload → media_id → send by id**. Used at **TWO points**: the approver's [View PDF] tap (draft PDF) AND on approval (final PDF → requester) | **new** |
| email-to-client | `action_send` already mails; **SMTP sender fix scope confirmed INSIDE this Gate-1** (outgoing-mail server / from-address / deliverability must be prod-ready) | confirm |
| Meta template | the **MD/OD approval-ping template** (cold-window) — drafted + submitted EARLY (separate track, see the template draft) | **new (in flight)** |
| tests | `pwa12` real-path (command→parse→draft→submit→approve-tap→PDF→send-tap), false-positive, reject+comment, self-approval, first-tap-wins, dimensional parse, **placeholder-rate BLOCKS submit (add 1)**, **entitlement denial — mapped non-sales crew refused on BOTH faces, refusal leaks no capability (add 2)**, **one-currency-per-quote / mixed-asks (add 3)**, **dual-payload dispatch — [Approve]/[Reject]/[View PDF] matched as BOTH template-QR button text AND interactive HMAC payload (the live-proof seam)**; + a staged `[TEST-WA12]` handset proof | new |

## 4. ⛔ Gates / guardrails (binding)

1. **Money:** WA-12 *displays* a total over WhatsApp (to the approver) → the
   walled-off money class → **Robin's explicit sign-off before LIVE**. Quoting
   moves no money; client delivery is the sales-initiated [Send to client].
2. **No invented prices:** the quote uses **only** the loaded price-list rates.
   Until the pricing load lands, the build is exercised against `[TEST-WA12]`
   fixtures with test rates — **never** shipped against the $1 placeholders.
3. **Approval never bypassed:** [Approve] = `action_approve` by the real MD/OD;
   self-approval only when the requester genuinely holds MD/OD.
4. **Switch-on sequence:** build (after review) → pricing load (data-load
   ritual + count verification) → `[TEST-WA12]` staged handset proof (requester
   + approver phones; zero sends to real clients) → teardown → Robin's go →
   LIVE.

## 4a. ⛔ Gate-1 BINDING ADDITIONS (Tatenda, approval conditions 2026-06-11)

1. **PLACEHOLDER-RATE GUARD.** Any quote line with an unset / $1 placeholder
   rate renders **"no rate set"** and **BLOCKS `submit_for_approval`** until
   every line is genuinely priced — with an honest reply to the requester
   ("can't submit — these lines have no rate yet: …"). The build lands BEFORE
   the pricing load, so this guarantees **no $6 / placeholder quote ever reaches
   an approver**. **`pwa12` test REQUIRED** (placeholder line → submit blocked +
   honest message).
2. **ENTITLEMENT GATE (APPROVED 2026-06-11).** `_wa12_can_quote` =
   **OD/superuser + `neon_sales_rep` + `jobs_manager`** (narrower than WA-8's
   any-mapped rail), **shared by `Quote:` AND `Price:`**. (Org-map verified:
   Evrill covered — her groups are a superset of Lisa's.)
   - **Non-sales MAPPED** sender → **polite, terse refusal that NEVER names the
     capability** (no "quoting is for sales", no command syntax — e.g. "Sorry,
     that isn't available on your account."). Don't teach excluded users what
     the commands do.
   - **UNMAPPED** sender → silent **fall-through** (client lane / Copilot, as
     WA-6/7/8) — no acknowledgement at all.
   - **Denial test (sharpened):** a **mapped NON-sales user (crew fixture)** is
     refused on **BOTH** faces, AND the refusal text is asserted terse +
     **leaks no command/capability detail**.
3. **ONE CURRENCY PER QUOTE (v1).** A quote carries a single currency; a mixed
   request → **the bot asks** which. **ZiG only where a rate is configured;
   unset → exclude** (per the house rule / the manual ZiG↔USD rate). Test:
   mixed-currency ask path.
4. **`[TEST-WA12]` TEARDOWN SCOPE.** The teardown explicitly removes **the quote
   rows (quote + quote.line) + any action-centre rows + the uploaded Meta media**
   (the `/media` doc), atomically — closing the orphan-ACT class the WA-9 sweep
   exposed (the durable teardown-helper fix applies here too).

## 5. Open decisions — SETTLED at Gate-1 (2026-06-11)

1. **Template variable count → 4-var** (requester / client / item-summary /
   total). SETTLED.
2. **Dimensional rule → per-product fields** populated from the pricing sheet's
   **Section B** (per-m² + per-panel + panel size on the product). SETTLED.
3. **`[Send to client]` → email in v1.** Client WhatsApp doc = **phase 2**
   (separate Meta template + media rules). SETTLED.
4. **Currency → per binding addition 4a.3** — one currency per quote; mixed →
   bot asks; ZiG only where a rate is configured, unset → exclude. SETTLED.

---

## 6. Meta template draft — MD/OD approval ping (⛔ for Robin's go)

Submitted EARLY (separate from the build) so Meta's review runs in the
background — the approval ping lands cold-window (>24h since the MD/OD last
messaged the bot) so it **needs an approved template**. **NOT submitted until
Robin says yes** (hard gate 2 — Meta submission).

- **Name:** `wa12_quote_approval`
- **Category:** UTILITY (transactional internal approval — not marketing)
- **Language:** en
- **Body (4 variables):**
  ```
  🧾 Quote approval needed
  {{1}} drafted a quote for {{2}}.
  {{3}}
  Total: {{4}}
  Approve or reject below — full quote attached on request.
  ```
  - {{1}} = requester name · {{2}} = client name · {{3}} = item summary
    (e.g. "Truss ×4, LED wall 3×2m, Distro ×2") · {{4}} = total + currency
- **Quick-reply buttons (3, PLAIN labels):** `[Approve]` `[Reject]` `[View PDF]`
  → intents `wa12_approve` / `wa12_reject` / `wa12_view_pdf`. **⚠️ BUILD FLAG
  (corrects bea5d73):** Meta **strips emoji from BUTTONS** (verified) — the
  button label + tap-back payload is **`View PDF`** (no 📄), so the dispatch
  MUST match `wa12_view_pdf` ⇄ payload **`"View PDF"`**, NOT `"📄 View PDF"`. The
  **body keeps 📄** (body emoji is fine). View PDF sends the draft quote PDF into
  the approver's chat (in-window); the Reject comment is captured in-session.
  (WhatsApp-native: the approver never needs Odoo to read the quote.)
- **Param count (132000 lesson):** 4 body params, 0 URL, **3 static QR** — the
  send call MUST pass exactly `body_params=[requester, client, item_summary, total]`.

⚠️ This body **displays a money total over WhatsApp** (to the internal approver
— inherent to approving a price). That is the money-adjacent surface gated on
Robin's sign-off; flagging explicitly.

**SUBMIT NOW (Tatenda go, 3-button form):** ready to submit via WhatsApp Manager
(the team's UI action, same path as `wa6_equip_finalize`) — button labels PLAIN
`[Approve] [Reject] [View PDF]`, body as above (keeps 📄). The assistant verifies
status post-submission (Pending → Active). 4-var body is settled (no lean
fallback). Meta's review then runs in the background starting today; the cold-
window approval ping can't deliver until it's Active.

---

## 7. Robin's binding pricing rulings (2026-06-11)

1. **DAYS + RECALC — NO new field, NO new engine.** `quote.line` already has
   `duration_days` + `day_breakdown_json`; `action_recalculate_pricing` exists.
   CSV `Rate` = the **per-day** hire price → line total = `qty × rate ×
   duration_days` via the EXISTING compute. The parse lane maps "for N days" /
   a date-range → `duration_days` (default 1, echoed in the draft summary).
   ⚠️ build-time reconciliation: "no new field" ⇒ the per-product rate lives in
   the existing per-product price field and is set onto `line.unit_rate`
   directly (pricing_status `manual`), NOT via the category `pricing.rule` path
   — document the exact source when wiring (bend spec→reality per CLAUDE.md).
   **DURATION-CHANGE POLICY (binding):** draft → `action_recalculate_pricing`
   in place; **after approval → DUPLICATE with the new duration → recalculate →
   fresh MD/OD approval → NEW quote.** Approved quotes are NEVER mutated.
2. **The 3 × $1 receivers (SHURE / INNOPOW / CineEye)** = ADD-ONS, never quoted
   alone. No pricing rule; excluded from standalone quoting; requested solo →
   the bot says they're included with their parent kit. (Placeholder guard does
   NOT trip on them in a kit context.)
3. **LED = named size-variant matching ONLY.** "3×2m LED" → the exact named
   product if it exists (e.g. "3M X 2M LED SCREEN" $300), else list available
   sizes + rates and ask. **No per-m² formula.**
4. **SCOPE = everything quotable from the phone** — packages (Corporate /
   Wedding / DJ / School), Generator, Camera Setup, Logistics all quotable.
   **Quotable Zoho items missing from Odoo get CREATED** as products/services
   during the load (⛔ money-gated, after Robin's sign-off + the dedup pass —
   see the catalogue review).
   **NEW FACE — "Price:" enquiry.** Sales-capable mapped staff text `Price: <item>`
   → the bot replies rate + currency + per-day note. **Read-only, WA-8
   entitlement rail, NO approval, NO quote record.** Added to the footprint +
   `pwa12` (incl. a denial test for a non-entitled sender).

---

## §8 — FLEXIBILITY AMENDMENT · Gate-1 ratified 2026-06-12 (build rides the LIVE batch behind Robin's money sign-off; plan adversarially reviewed 2026-06-12, 22 findings folded in)

**Sub-hire ruling:** quotable ≠ warehouse — **no stock check ever gates a quote**
(confirmed; WA-12 never checks QOH). No code change.

### Ratified decisions
1. **Discount = PER-UNIT-DAY** (parallel to `unit_rate`, scale-safe under qty/days):
   `line_subtotal = qty × max(unit_rate − discount_amount, 0) × days`, or
   `qty × unit_rate × (1 − pct/100) × days`. **`unit_rate` NEVER overwritten** (for
   equipment lines). Commands: **`price <item> <amt>`** (PRIMARY = new effective
   unit rate → stores `discount_amount = unit_rate − amt`); **`discount <item>
   <amt|%>`**. Summary / ping / PDF render **"base → discounted (disc. X)"**.
2. **Pct vs amount — exclusive per line:** setting one **clears the other**
   (last-write-wins).
3. **Custom = a `line_type` value `'custom'`** (not a flag): equipment needs an
   engine rule (guard intact); custom needs the typed price; rendered **loudly
   CUSTOM**; auditable.
4. **`days <n>` = whole-quote**; **`days <item> <n>` = per-line.**
5. **`client <name>` mid-draft = RE-POINT IN PLACE.** ⚠️ **Write the ROOT writable
   node `quote.event_job_id.commercial_job_id.partner_id`** — `quote.partner_id`
   and `event.job.partner_id` are **stored-readonly RELATED** (a direct write is
   rejected); the stored-related cascade flows partner_id to event.job + quote +
   the PDF. pwa12 asserts all three reflect it. Rebuild-chain only as a documented
   fallback.

### Model deltas — `neon.finance.quote.line`
- `+ discount_pct = Float()` and `+ discount_amount =
  Monetary(currency_field='currency_id')` (quote.line HAS `currency_id`).
  **Mutually exclusive** (write/onchange clears the other; last-write-wins).
  ⚠️ **CHECK** `discount_amount >= 0`, `0 <= discount_pct <= 100`; clamp
  `discount_amount` to `[0, unit_rate]` so `price <item> <amt>` with `amt > base`
  is **rejected** ("above base rate"), never a silent negative discount (markup).
- `+ ('custom', 'Custom')` to `_LINE_TYPES`.
- `_compute_subtotal` (+ `discount_pct`, `discount_amount` to `@api.depends`):
  `effective = (unit_rate − discount_amount) if discount_amount else
  unit_rate × (1 − pct/100)`; `line_subtotal = qty × max(effective, 0) × days`.
  **Verify the discount also reaches `line_total_taxed`** (the stored field
  `amount_total` reads) so the approval figure moves.
- **Engine interaction (verified):** the create()/recalc gate keys on
  `line_type=='equipment'` (`quote_line.py:300`, `quote.py:748`), so a `'custom'`
  line skips `_compute_line_pricing` and (typed `unit_rate>0`) lands
  `pricing_status='manual'` — the explicit labeled rate, as intended. Discounts
  never touch `unit_rate`.

### `<item>` resolution — a NEW line resolver (review BLOCKER)
The WA-6 catalogue matcher `_wa6_match_one` matches **product.template
(is_workshop_item)** and returns a `product_id` — it **cannot** address a quote
line (esp. a `custom` line with no product) and can't disambiguate two lines
sharing a category. The edit loop needs **`_wa12_match_line(quote, token)`** scoring
the token against `quote.line_ids` by `.name` (+ `product_template_id` + a 1-based
index fallback), covering custom lines; on >1 candidate → **refuse + re-list**.
Only **`add <item> x<n>`** (a NEW catalogue line) uses `_wa6_match_items` +
engine-prices it.

### Guard evolution — line_type-aware (review HIGH)
`_wa12_unpriced_lines` (currently has NO line_type branch) becomes:
**bad** if `(line_type=='equipment' and pricing_status in
('not_yet','no_rule','manual'))` **OR** `(unit_rate <= $1 and line_type != 'custom')`.
A `custom` line (manual, typed `unit_rate > $1`) **passes**; an `equipment` line
with no rule still **blocks**. The guard reads **base `unit_rate`** (not the
discounted effective) — a 100% discount is an explicit, approval-visible free item,
not "unpriced". The lane still **cannot fabricate a hidden manual rate on an
equipment line** (it builds equipment lines `unit_rate=0` → engine prices).
⚠️ **`price`/`discount` are REFUSED on a `no_rule`/`not_yet`/placeholder equipment
line** (honest "no rate set") — valid only on an engine-priced equipment line or a
custom line (else a typed rate slips past the guard the lane exists to enforce).

### Draft-editing FSM (q_confirm session, pre-submit)
Each command → mutate → `action_recalculate_pricing` → **guard re-evaluates** →
re-show summary → await confirm/more edits; "yes"/submit only from the re-shown
summary; **unrecognised → re-prompt (still claimed)**; bare `cancel`/`no`/`stop`
still exits (never trap the user). Commands:
`price <item> <amt>` · `discount <item> <amt|%>` · `qty <item> <n>` · `days <n>` ·
`days <item> <n>` · `add <item> x<n>` · `add custom <desc> at <price>` ·
`remove <item>` · `no tax` / `with tax` · `client <name>`.
- **Custom-line pricing:** on a `custom` line `price <item> <amt>` **overwrites
  `unit_rate`** (re-type the custom price) and clears `discount_*`; `discount` on a
  custom line is rejected (the custom rate IS the price). Avoids double-counting.
- **`remove`** that would empty the quote is **refused** (keep ≥1 line).
- **`no tax`/`with tax`:** write `tax_id` across `quote.line_ids` via standard
  write — `tax_id=False` for no-tax, `_default_tax()` (VAT 15.5%) for with-tax.

### Render (review HIGH — the report is NOT already conditional)
- **VAT row is currently UNCONDITIONAL** (`neon_finance_quote_report.xml:151-157`,
  no `t-if`) — `no tax` would render "VAT 15.5% 0.00". **Wrap the VAT `<tr>` in
  `t-if="o.amount_tax"`** AND gate the 15.5% footnote (~:237-239) + the
  draft-summary "(incl. VAT)" string (emit "(no VAT)" / omit when `amount_tax==0`)
  + the ping body.
- **Discount is currently invisible** — `Rate/day` shows base `unit_rate`. Render a
  discount indicator: `Rate/day` = effective with a struck base + "(disc. X)" (or a
  dedicated column) so `Qty × shown-rate × Days` reconciles to `Amount`; render
  **FREE (disc. 100%)** for a full discount.
- **Custom line:** a **CUSTOM** badge when `line_type=='custom'`.
- **`_wa12_draft_summary` + the approval ping** ALSO show effective rate +
  "(disc. X)" + CUSTOM (the approver must see honest line detail, not the base).
  ⚠️ the cold-window TEMPLATE body var is fixed-shape — if the discount/custom
  detail can't fit, surface it via the in-window buttons / the PDF (flag at build).

### pwa12 expansions
- discount math (price/discount → correct `line_subtotal` + `amount_total`,
  `unit_rate` UNCHANGED, scale-safe under a following qty/days edit); pct↔amount
  exclusivity; **over-discount/markup rejected or clamped**.
- custom: `add custom … at <price>` → a `custom` line, priced, **labeled CUSTOM**,
  passes the guard; an `equipment` no_rule line still **blocks**; `price` on a
  no_rule equipment line **refused**.
- edit loop: each command mutates + recalcs + re-shows; submit only from the
  re-shown summary; **remove-last-line refused**.
- `days <n>` (all) vs `days <item> <n>` (one).
- `client <name>`: re-point writes `commercial.job.partner_id` and the stored
  related reaches **event.job.partner_id + quote.partner_id + the rendered PDF**.
- tax toggle: `no tax` → **no VAT row in the rendered PDF** + `amount_tax=0` +
  summary not "(incl. VAT)"; `with tax` → restored to the 15.5% figure.

### Footprint
- `neon_finance/models/neon_finance_quote_line.py` (2 fields + CHECK/clamp +
  `'custom'` + `_compute_subtotal` + exclusivity) — minor bump.
- `neon_crew_comms/models/whatsapp_message_wa12.py` (`_wa12_match_line` + edit-loop
  commands + `add custom`/`client` handlers + evolved guard + discount/custom
  render in summary/ping) — minor bump.
- `neon_finance/report/neon_finance_quote_report.xml` (conditional VAT row +
  footnote + the discount indicator + CUSTOM badge — **MINOR**, real conditional
  logic, not a patch) — minor bump.
- ⛔ **Money-adjacent.** Robin's money sign-off covers **WA-12 pricing + flexibility
  + WA-13 in one sitting** → the LIVE batch then builds + deploys **as one**.
