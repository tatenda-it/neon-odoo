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
| `neon_finance` quote build | helper to create quote + lines from the parsed payload + price-list lookup + the **LED-wall dimensional rule** (parse `3×2m` → m² × per-m² rate, OR panel-count × per-panel rate) | new helper |
| **QWeb quote PDF report** | a report on `neon.finance.quote` (none exists today; the invoice report does) — renders **state-stamped** (DRAFT at submit, final on approval); used by both legs | **new** |
| `send_document` outbound | new send type on `neon.whatsapp.message` (inbound already recognises `document`); **Meta `/media` upload → media_id → send by id**. Used at **TWO points**: the approver's [View PDF] tap (draft PDF) AND on approval (final PDF → requester) | **new** |
| email-to-client | `action_send` already mails; **SMTP sender fix scope confirmed INSIDE this Gate-1** (outgoing-mail server / from-address / deliverability must be prod-ready) | confirm |
| Meta template | the **MD/OD approval-ping template** (cold-window) — drafted + submitted EARLY (separate track, see the template draft) | **new (in flight)** |
| tests | `pwa12` real-path (command→parse→draft→submit→approve-tap→PDF→send-tap), false-positive, reject+comment, self-approval, first-tap-wins, dimensional parse; + a staged `[TEST-WA12]` handset proof | new |

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

## 5. Open decisions for Gate-1 review

1. Template variable count — lean (3: requester/client/total) vs detailed
   (4: + item summary). Draft proposes **4** (matches "quote summary + total").
2. Dimensional rule storage — a config rule per dimensional product
   (per-m² + per-panel rates on the product) vs a global rule. Recommend
   **per-product** fields populated from the pricing sheet's dimensional section.
3. `[Send to client]` channel — email (confirmed) vs also a client WhatsApp doc
   (that is **phase 2**, separate Meta template + media rules; out of v1).
4. Currency — the quote carries currency; the sheet's CURRENCY column (USD/ZiG)
   drives the line `unit_rate` currency. Confirm ZiG handling (house rule).

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
- **Quick-reply buttons (3):** `[Approve]` `[Reject]` `[📄 View PDF]` → intents
  `wa12_approve` / `wa12_reject` / `wa12_view_pdf`. View PDF sends the **draft
  quote PDF into the approver's chat** (in-window); the Reject comment is
  captured in-session after the tap. (WHATSAPP-NATIVE: the approver never needs
  Odoo to read the quote.)
- **Param count (132000 lesson):** 4 body params, 0 URL, **3 static QR** — the
  send call MUST pass exactly `body_params=[requester, client, item_summary, total]`.

⚠️ This body **displays a money total over WhatsApp** (to the internal approver
— inherent to approving a price). That is the money-adjacent surface gated on
Robin's sign-off; flagging explicitly.

**On Robin's "yes" (now applies to the 3-button form):** submit via WhatsApp
Manager (same path as `wa6_equip_finalize`). The assistant then verifies its
status in the Manager (Pending → Active). Lean alternative if Robin prefers
fewer variables: drop {{3}} (item summary) → 3-var body; the lines then come via
**[📄 View PDF]** (never "see Odoo" — the loop is WhatsApp-native).
