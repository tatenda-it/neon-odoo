# WA-13 — Quote/Invoice retrieval + invoice-from-quote · Gate-1 plan

**Status:** Gate-0 done (2026-06-12, engine read first-hand). Gate-1 decisions
**user-ratified 2026-06-12**. Plan **adversarially reviewed against the live code
2026-06-12** — 21 findings folded in below (3 BLOCKER + 6 HIGH + MEDIUM/LOW).
⛔ **Robin's money sign-off is required before the Face-2 build completes** (rides
the WA-12 worksheet sitting). No build until then.

**Premise:** a **WhatsApp face on the EXISTING P6.M7 invoice machinery** — *no new
finance engine*. Reuses the WA-12 rails.

---

## §1 — Reused, NOT rebuilt (verified in code)

- **Invoice engine** `neon.finance.invoice.schedule`: per-quote
  (`quote.invoice_schedule_ids`), staged, `percentage`-based.
  `action_create_invoice()` builds a **DRAFT** `account.move` out_invoice (sudo,
  per-quote-line prorated on `line_subtotal` + re-adds `tax_id`, **idempotent** on
  `state != 'scheduled'`, sets `invoice_id`, `invoice_origin`, `ref`). It does
  **NOT** `action_post()` — so the move stays draft with **no INV- number** until
  Kudzai posts it in Odoo. `action_trigger_now()` is the **approver-gated**
  (`group_neon_finance_approver`) + state-guarded wrapper around it.
- **PDF reports — corrected (review BLOCKER):** quotes render via the **action**
  `neon_finance.action_report_neon_quote` (report_name
  `neon_finance.report_neon_quote_document`). Invoices render via the **stock
  wrapper action `account.account_invoices`** (report_name `account.report_invoice`)
  — **NOT** `account.report_invoice_document`, which is the inner template (no
  `html_container`, no `docs` loop) and is not directly renderable. neon_finance's
  `report_invoice_document_neon_finance` inherit applies transitively, so the
  ZIMRA/banking blocks still appear. *Verify the exact action xmlid in the running
  instance at build time before hardcoding.*
- **WA-12 rails:** `send_document` (returns **False** on failure, never raises —
  see §6), `_wa12_resolve_client`, `_wa12_is_approver`, `_wa6_can_initiate`,
  `_wa6_resolve_user`; the tight-parser → list-then-pick → advisory-lock dispatch
  + the `_wa12_handle_session` re-prompt pattern.

---

## §2 — Ratified Gate-1 decisions (2026-06-12)

1. **Vocabulary** — verb = **"Send"**: `Send quote <client|ref>`,
   `Send invoice <client|ref>`, `Send <QUO-…|INV-…>`. **No bare "Quote for X"**
   (collides with the WA-12 `Quote:` create face). Tight parser; list-then-pick on
   multiple; terse refusal outside entitlement. ⚠️ **Ref format (review):** quote
   names carry a currency infix — `QUO-USD-NNNNNN` / `QUO-ZIG-NNNNNN`, never bare
   `QUO-NNNNNN`. The ref lookup matches the full name (or `ilike`); document the
   real format to users.
2. **Own-rule (v1)** — a sales rep sees **only their own** quotes
   (`salesperson_id == rep`). MD/OD see all. **Kudzai/finance see ALL quotes
   read-only.** Partner-owner scoping is future, not v1. ⚠️ **Enforcement
   (review):** WA reads go through `sudo()`, which **bypasses the salesperson
   ir.rule** — so own-scope must be an **explicit code domain**
   `[('salesperson_id','=',rep.id)]` for non-approver/non-OD requesters, applied to
   **both client-name AND ref lookups** (a ref must not bypass scope).
3. **Face-2 gate** — **GROUP-based: `neon_finance.group_neon_finance_approver`**
   (never numeric uids). ⚠️ **Prod membership (verified) = Administrator(2),
   Munashe(7), Robin(21), Tatenda(6) — KUDZAI IS MISSING.** Kudzai must be ADDED
   (§5 migration). *(Tatenda's approver membership → temp-superuser teardown review
   list; team decision, not a WA-13 action.)*
4. **Face-2 flow** — the **generation tap IS the authority gate** (tapper holds the
   group) **+ a two-phase CONFIRM by the same person** showing stage / % / amount
   (**VAT-inclusive**, = `schedule.amount`) / client. **No second approver** (MD/OD
   self-approval principle).
5. **Stage pick** — **never silent**. Exactly one **`scheduled`** stage → named
   confirm; multiple → list-then-pick. **No "latest" auto-fire.**
6. **Advisory lock ns = 5594000** (verified free).

---

## §3 — Face 1: RETRIEVAL (read-only; no money moves)

Parse the tight `Send {quote|invoice} <client|ref>` → resolve → find doc(s) →
list-then-pick if >1 → render → `send_document`. No compliance gate (ZIMRA
fiscalisation is outside Odoo).

**Entitlement — EXPLICIT positive gates (review HIGH; never "can_quote and not
approver", never rely on account.move ACL to deny):**

| Requester | Quotes | Invoices |
|-----------|--------|----------|
| Pure sales rep (`group_neon_sales_rep`, not approver/OD) | **own only** — code domain `salesperson_id=rep` (both name + ref) | **denied** (terse refusal) |
| jobs_manager (passes `_wa12_can_quote`, not approver) | own only | **denied** — note: jobs_manager *can* read account.move via ACL, so the deny MUST be the explicit WA gate, not data-ACL |
| Finance / Kudzai (`group_neon_finance_approver`) | **all** (read-only) | **all** |
| MD / OD (`_wa6_can_initiate`) | **all** | **all** |
| Unmapped / other | silent fall-through (Copilot) | — |

`_wa13_can_retrieve_invoice(user) = _wa12_is_approver(user) or _wa6_can_initiate(user)` — **explicit allow-list only.**

**Draft vs posted (review):** the engine produces **DRAFT** invoices (no INV-
number). Face-1 invoice retrieval **restricts to `state='posted'`** (refuse a
draft honestly: "not yet finalised — Kudzai posts it in Odoo"), so a provisional/
numberless document never goes out. (The "1 real out_invoice" test target is
likely draft — handle it.) **Currency (review + org rule):** list-then-pick rows
show **currency + amount + stage + date** so a client with both USD and ZWG
invoices disambiguates.

---

## §4 — Face 2: INVOICE-FROM-QUOTE (money surface → ⛔ Robin)

**Precondition (review HIGH/MEDIUM):** refuse unless `quote.state == 'accepted'`
**AND** it has at least one `scheduled` schedule. Never invoice a draft/sent/
approved/rejected quote (a rep can pre-design draft schedule rows on a
non-accepted quote — guard against billing it).

**The on_acceptance reality (review BLOCKER):** on accept, the engine **auto-fires
every `scheduled` `on_acceptance` schedule to `invoiced`** — incl. the default
single-100%-final fallback. So for a plain quote, by 'accepted' there is **no
`scheduled` stage left** and the invoice already exists. Face-2 therefore:
1. **Gate:** tapper in `group_neon_finance_approver` (§2.3) — else terse refusal.
2. **Find `state == 'scheduled'` schedules** (excludes the auto-fired
   on_acceptance default):
   - **none scheduled, but an `invoice_id` already exists** → offer to **RE-SEND
     that already-generated invoice PDF** (the common default-quote path — not a
     dead end, not a new invoice);
   - **exactly one scheduled** → named two-phase confirm (§2.4);
   - **multiple scheduled** → list-then-pick → named confirm.
3. **On Confirm (same person):** fire **`action_trigger_now()`** (review MEDIUM —
   the approver-gated + state-guarded wrapper; gives defence-in-depth behind the WA
   gate, vs the ungated `action_create_invoice()`). The created move is **DRAFT**
   (no INV- number) — Kudzai posts in Odoo. Render via the **`account.account_invoices`
   action** (§1) and `send_document`, clearly marking the PDF a draft.
4. **Lock** ns 5594000 (first-tap-wins) around the generate-tap; the engine is also
   idempotent on `state != 'scheduled'`.

**Tax basis (review LOW):** `schedule.amount = quote.amount_total × pct/100` is
**VAT-inclusive** (`amount_total` is taxed); the engine prorates the **ex-VAT
`line_subtotal`** per line then re-adds `tax_id`, so the move total reconciles to
`schedule.amount`. The confirm shows the **VAT-inclusive** figure — do **not**
recompute ex-VAT in the WA layer.

---

## §5 — Footprint (planned; for the build, post-sign-off)

- **neon_crew_comms — `whatsapp_message_wa13.py` (new):** `_wa13_maybe_intercept`
  (after WA-12, before WA-6); the `Send …` tight parsers; `_wa13_can_retrieve_quote`
  / `_wa13_can_retrieve_invoice` (= approver/OD only) / `_wa13_can_generate`
  (group); retrieval resolution with the **explicit own-scope domain** (§2.2) +
  list-then-pick; the Face-2 confirm FSM. ⚠️ **While an `inv_*` session is live,
  WA-13 MUST claim every text turn (return True; re-prompt on unrecognised input)**
  — WA-6 (the next interceptor) grabs ANY live-session text unconditionally and
  would mis-feed it to the equip FSM (review HIGH). Lock ns 5594000.
- **neon_crew_comms — `wa_equip_session.py` (EDIT, review BLOCKER):** add
  `('inv_pick', …)` + `('inv_confirm', …)` to the `step` Selection + a `_start_inv`
  helper (buffer dict {quote_id, schedule_ids, …}). The intercept claims **ONLY**
  `inv_*` steps (mirrors WA-12's `_WA12_STEPS` bail-out) so it never overruns a
  live WA-6/7/8/10/12 session on the one-row-per-phone.
- **neon_channels — `wa_payload.py`:** add `wa13_inv_confirm` / `wa13_inv_cancel`
  / `wa13_inv_pick` to `INTENTS` **unconditionally** (review — the [Confirm]/
  [Cancel] buttons are interactive HMAC; `encode` raises on an unknown intent).
- **neon_finance — migration (⛔ NEW ACCESS POWER, gated):** add **Kudzai** to
  `group_neon_finance_approver`. ⚠️ **Her login is `admin@neonhiring.co.zw`
  (Kudzaiishe — a real staffer; reads like, but is NOT, the Odoo superuser)**
  (review HIGH). Resolve by that **exact login**, **assert non-empty** (fail loud,
  never silent no-op), then ORM `(4, group_id)` write per the group-membership +
  noupdate gotchas; manifest bump. Executed in the build, **after Robin's sign-off**.
- **Manifest bumps:** neon_crew_comms (new file + session-model edit), neon_finance
  (migration), neon_channels (intents).
- **No new model, no new finance compute, no row-touching schema migration.**

---

## §6 — Test list (pwa13, real dispatch path)

- **Entitlement:** pure sales rep → own quote sent / other-rep quote refused (name
  **and** ref) / any invoice refused; **jobs_manager (mapped, non-approver,
  non-OD) → `Send invoice <client>` REFUSED** (the ACL-leak guard); finance + MD/OD
  → all quotes + posted invoices.
- **Face-1 retrieval:** `Send quote <client>` → PDF; `Send QUO-USD-NNNNNN` (full
  name) → PDF; multiple → list-then-pick (currency-labelled); no-match → honest
  miss; **draft invoice → refused** ("not finalised"); cross-currency client →
  both invoices listed with currency.
- **Parser false-positives:** "send me the address", "quote for X", mid-sentence
  "invoice" → fall through (no turn stolen).
- **Session:** garbage text during `inv_pick` → **re-prompt, return True** (NOT a
  WA-6 equip turn); a live WA-6/q_* session is not overrun.
- **Face-2:** non-approver tap → refusal; **non-accepted quote → refusal**;
  **default 100%-on_acceptance quote (already invoiced) → "already invoiced, here
  is the PDF" (re-send), not a dead end**; approver + one scheduled → named confirm
  (stage/%/**VAT-incl** amount/client correct) → Confirm → exactly one DRAFT
  invoice via `action_trigger_now` (idempotent on double-tap) → Cancel → none;
  multiple scheduled → list-then-pick.
- **send_document failure (review):** PDF rendered but Meta send → False → honest
  "invoice created but the PDF couldn't be sent — retrieve it from Odoo" (the
  invoice EXISTS; never read as "no invoice").
- **Kudzai migration:** before → refused; after → holds the group + can generate;
  the migration **asserts the `admin@neonhiring.co.zw` user resolved** before the
  write.
- **[TEST-WA13] teardown:** the created DRAFT move → `sudo().unlink()` directly
  (draft is directly unlinkable; no draft→cancel→unlink needed); append-only rows
  (quote chain + invoice.schedule, `perm_unlink=0`) via `sudo().unlink()` as the
  sanctioned [TEST-*] exception; order: move → schedule → quote.line → quote →
  event_job → commercial.job → fixtures → wire rows → baseline.

---

## §7 — Holds & go-live

- ⛔ **Gate-1 doc (this) → Robin's money sign-off (rides the WA-12 worksheet) →
  build.**
- **Face 1 (read-only)** can go LIVE with the **WA-12 LIVE batch**.
- **Face 2 (generation)** is **operationally** live at the **Zoho→Odoo finance
  cutover** (Robin's call). The code can ship behind the group gate before then.
- **Kudzai → approver group** = a **new access power**, executed only after Robin's
  sign-off.
- ⛔ Standing: every Face-2 path is money-adjacent and stays walled until sign-off.
