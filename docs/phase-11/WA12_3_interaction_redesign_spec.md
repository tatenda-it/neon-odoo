# WA-12.3 — B+C+D interaction redesign LOCKED SPEC (design wf_2a463848-260, 2026-06-13)

Source-verified synthesis of 2 designs + 2 adversarial critiques. Matcher byte-UNCHANGED.

Confirmed: q_confirm's `_wa12_match_line` ALREADY resolves a bare-int token to `lines[i-1]` (line 1608-1611) over `quote.line_ids`, and `_wa12_draft_summary` iterates the SAME `quote.line_ids` — so numbering it with `enumerate(quote.line_ids, 1)` aligns perfectly. C at q_confirm is essentially already wired (just unnumbered). And `_wa12_match_line` does index-first, contains-second — so a `qty 2 4`-style command resolving "2" hits the index.

I have full ground truth on all 10+ disputed bugs. Locking the spec now.

---

# WA-12.3 — LOCKED BUILD SPEC: B(tap-pick) + C(line-number) + D(conversational) correction layer

**Verified against live `whatsapp_message_wa12.py`, `whatsapp_message_wa6.py`, `wa_payload.py`, `wa_equip_session.py` on `feat/wa6-equipment-face` 2026-06-13.** This spec resolves the B vs C+D architectural split, fixes every HIGH/MED bug from both critiques, and corrects two claims BOTH designs got wrong against the live matcher.

## ARCHITECTURE DECISION (the B-vs-D split, resolved)

The two designs disagree on tap targeting: design-minimal uses a **slot token in the payload** (`u<i>`/`m<i>`/`l<lid>`); design-pending uses a **stable-`lid` buffer rewrite** (one ordered list, `next_lid` allocator). 

**LOCKED: stable-`lid` for q_items, existing index for q_confirm.** Reasoning, ground-truth-backed:
- At **q_items** the edit loop reorders the buffer between a pick-send and a tap (remove/add/replace). A positional index in the payload (`u0`/`m0`) is the exact volatile-position bug design-pending correctly flags. Stable `lid` is required. We adopt design-pending's **single ordered `lines` list with `lid`**, but constrained per the bugs below.
- At **q_confirm** the target is a real `quote.line` with a DB id. `_wa12_match_line` (verified line 1608) ALREADY does index→`lines[i-1]` over `quote.line_ids`, and `_wa12_draft_summary` (line 2241) iterates the same recordset. The payload carries the real `line.id`; no buffer model needed. Reuse as-is.

So: **q_items gets the buffer rewrite; q_confirm reuses the existing line-id machinery.** One pick handler branches on `sess.step`.

**Two claims BOTH designs got wrong (corrected here):**
- **C1 — `suggestions` is capped at `[:3]` on every matcher exit** (wa6.py:1180,1205,1209,1220,1256-58,1267,1271,1291). The matcher CANNOT return 4 candidates. The "blinders → 4 molefays as a LIST" headline is **unbuildable from `hit['suggestions']`**. Fix (LOCKED): for a confident-family-with-variants pick, candidates come from a **separate in-family enumeration** (`allp.filtered(_wa6_in_family(p, fam))`), NOT from `suggestions`. The `≤3 buttons / 4-10 list` branching applies to THIS enumerated set; `suggestions[:3]` only fuels the "ambiguous / did you mean" 2-3 button case.
- **C2 — `family_pick` cannot be a single matcher flag set once.** `forced_fam` is set only for category aliases (wa6.py:1162); `fam` (the closure var) is reliably in scope at the weak exits, but S4-dimensional (1209), S6b-token (1256), and S7-LLM (1266) all return `weak` within a family — framing all three as "which variant?" is wrong (critique A BUG-2). Fix (LOCKED): the matcher is **NOT touched**. The variant-vs-unsure signal is derived **in the WA-12 builder** from `hit['family']` + `hit['confidence']` + a builder-side family-term test, and the candidate set tells us the count.

---

## 1. BUFFER SCHEMA (q_items, schema v3)

Replace the two anonymous parallel lists (`buf['matched']`, `buf['unmatched']`) with ONE ordered list of line dicts, each carrying a stable `lid`, plus a single `pending` slot. **`_wa12_match_text_items` keeps its 2-tuple contract** (critique D BUG-7 — 5 callers at lines 370,755,847,979,1721 unpack it); the v3 line list is built by a NEW `_wa12_build_buf_lines` used ONLY by the q_items open/echo path.

```python
buf = {
    # preserved keys (untouched):
    "client_txt": str, "partner_id": int|False,
    "date_txt": str, "days": int, "prefills": {...},
    # NEW:
    "v": 3,                      # schema version; absent => legacy, migrate on read
    "next_lid": int,            # monotonic; NEVER reused, even after remove
    "lines": [
        {"lid": 1, "kind": "matched", "product_id": 880,
         "product_name": "RGB LED CAN", "qty": 5,
         "rep_price": None, "stated_price": 10},
        {"lid": 2, "kind": "unmatched", "raw": "blinder", "qty": 1,
         "stated_price": None, "suggestions": ["8-lite Blinder", ...],
         "family": "lighting",            # carried for variant framing/enumeration
         "_cand_ids": [881,882,883,884],  # transient: resolved candidate product ids
         "_variant": True},               # transient: confident-family-variant flag
    ],
    "pending": {                 # AT MOST ONE; the line awaiting a pick reply
        "lid": 2, "kind": "variant"|"ambiguous",
        "candidates": [881,882,883,884],  # product_ids, in the order shown
        "label": "blinder", "family": "lighting", "overflow": False,
    } | None,
}
```

**Rules (LOCKED):**
- `lid` allocated from `next_lid++`, never reused. A tap carrying `lid=2` can never hit a since-shifted line (fixes the volatile-index bug).
- `lines` is the single source of render order. Display number `N` = `enumerate(buf['lines'], 1)` → index `N-1`. **Numbers are display-derived, never stored; recomputed every reshow.** Every mutation reshows, so the rep always sees current numbering.
- `kind` collapses matched+unmatched into one numbered list — so a number addresses ANY line including an unresolved one (this is what lets C say "2 = X" against an unmatched line).
- `pending` is at most one. A new offer overwrites it; resolution or `remove` of `pending.lid` clears it.
- `_cand_ids`/`_variant` are transient underscore keys — dropped by the `yes`-projection (below), never reach the draft.
- **`yes`-projection** (in the submit branch): `matched = [{product_id,product_name,qty,rep_price,stated_price} for ln in buf['lines'] if ln['kind']=='matched']` → fed to the UNCHANGED `_wa12_quote_from_slots`. Unmatched/pending lines excluded (a rep can't draft an unresolved line — same as today).

**Migration `_wa12_buf_migrate(buf)`** (idempotent, on `v==3` returns as-is): fold legacy `matched`→`kind:matched` lines then `unmatched`→`kind:unmatched` lines, allocate `lid` 1..n, set `next_lid`, set `v=3`, `pop('matched')`, `pop('unmatched')`. Call at the TOP of every q_items buffer consumer (open, echo, try, surface, pick-tap) so a pre-deploy session degrades cleanly AND no path leaves both `lines` and legacy keys (critique D BUG-8).

---

## 2. INTENTS (`addons/neon_channels/models/wa_payload.py`)

Add to `INTENTS` frozenset (verified: `encode()` raises ValueError on unknown intent, line 138; parts must contain no `:`, all ids numeric → safe):

```python
    # WA-12.3 -- tappable candidate/variant pick on a q_items buffer line
    # (stable lid) OR a q_confirm draft line (real line id). Routed by the
    # neon_crew_comms bridge intercept (q_items/q_confirm session), NOT Copilot.
    #   wa12_pick:<session_id>:<target>:<product_id>  -- bind product to target
    #       target = 'b<lid>'  (a q_items buffer line, stable lid)
    #             | 'l<line_id>' (a q_confirm draft quote.line)
    #   wa12_pick_more:<session_id>:<target>   -- ">10" overflow: re-prompt narrow
    #   wa12_pick_skip:<session_id>:<target>   -- "none of these" -> leave unmatched
    "wa12_pick", "wa12_pick_more", "wa12_pick_skip",
```

`target` is a tagged token (`b<lid>` / `l<line_id>`) so ONE intent family covers both steps; it contains no `:` so `encode()` accepts it. `session_id` is `parts[0]` (NOT a quote id — the routing fix in §3 depends on this).

---

## 3. B — TAPPABLE PICK

### 3a. Tap extraction + routing (fixes critique A BUG-1, critique D BUG-6)

**`_wa12_extract_tap` (wa12.py:296):** the new `wa12_pick*` intents start with `wa12_` and would be swallowed by the existing `decoded[0].startswith("wa12_")` branch (line 311) which browses `parts[0]` as a **quote id**. Two changes, BOTH load-bearing:
1. Read `list_reply.id` too (today only `button_reply.id`, line 307 — the 4-10 list pick returns `list_reply`, would otherwise dead-end).
2. Test the pick intents **BEFORE** the `startswith("wa12_")` block, returning a sentinel that is NOT a quote recordset:

```python
        if mtype == "interactive":
            inter = message.get("interactive") or {}
            payload = (inter.get("button_reply") or {}).get("id") \
                or (inter.get("list_reply") or {}).get("id")        # FIX D-BUG6 (list)
            secret = self.env["ir.config_parameter"].sudo().get_param(
                "database.secret") or ""
            decoded = wa_payload.decode(secret, payload or "")
            if decoded and decoded[0] in (
                    "wa12_pick", "wa12_pick_more", "wa12_pick_skip"):  # BEFORE startswith
                return (decoded[0], ("pick", decoded[1]))   # sentinel, NOT a quote
            if decoded and decoded[0].startswith("wa12_"):
                intent, parts = decoded
                quote = self.env["neon.finance.quote"].sudo().browse(
                    int(parts[0])) if parts and parts[0].isdigit() else \
                    self.env["neon.finance.quote"].sudo().browse()
                return (intent, quote)
            return None
```

**`_wa12_maybe_intercept` step 1 (wa12.py:254):** branch the sentinel BEFORE `_wa12_handle_tap` (which would call `.exists()` on a list → crash, critique A BUG-1):

```python
        tap = self._wa12_extract_tap(message)
        if tap:
            intent, payload = tap
            if isinstance(payload, tuple) and payload[0] == "pick":
                return self._wa12_handle_pick_tap(
                    intent, payload[1], from_e164, raw_from, message)
            intent_, quote = intent, payload
            return self._wa12_handle_tap(intent_, quote, from_e164, raw_from, message)
```

### 3b. Pick handler (parity, two-factor, cross-session guard)

```python
def _wa12_handle_pick_tap(self, intent, parts, from_e164, raw_from, message):
    """B: apply a tapped candidate. parts = [session_id, target(, product_id)].
    target = 'b<lid>' (q_items buffer line) | 'l<line_id>' (q_confirm draft).
    Resolve session by PHONE, then assert it matches the payload session_id
    (cross-session lid collision guard, D-BUG5). The product came from the
    OFFERED matcher-sourced candidate set; we re-validate prod.exists() +
    membership in pending.candidates so a tap can never bind a product the
    matcher didn't surface (guard §7)."""
    self._wa6_audit_in(from_e164, message, intent)
    sess = self.env["neon.wa.equip.session"]._active_for_phone(from_e164)
    sid = int(parts[0]) if parts and str(parts[0]).isdigit() else 0
    if not (sess and sess.id == sid and sess.step in ("q_items", "q_confirm")
            and from_e164 == sess.phone_number):           # field VERIFIED: phone_number
        return self._wa6_reply(raw_from, from_e164, _(
            "That choice has expired — send the items again to re-quote."))
    sender = sess.user_id
    if not (sender and sender.active and self._wa12_can_quote(sender)):
        sess.sudo().write({"active": False})
        return self._wa6_reply(raw_from, from_e164, _(_WA12_REFUSAL))
    sess.sudo().write({"last_inbound": fields.Datetime.now()})
    target = str(parts[1]) if len(parts) > 1 else ""
    if sess.step == "q_confirm":
        return self._wa12_pick_apply_draft(sess, intent, target, parts, from_e164, raw_from)
    return self._wa12_pick_apply_buffer(sess, intent, target, parts, from_e164, raw_from)
```

`_wa12_pick_apply_buffer` migrates the buffer, resolves `lid` from `b<lid>`, handles `skip`/`more`, else validates `product_id ∈ pending.candidates` + `prod.exists()`, sets the line `kind='matched'`, `rep_price=None`, drops `raw`/`suggestions`/`_cand_ids`/`_variant`, clears pending, reshows. If `_wa12_line_by_lid` returns None (line removed since the offer) → reshow current list (no crash). `_wa12_pick_apply_draft` resolves `l<line_id>` → `quote.line` → re-match `prod.name` through `_wa6_match_one` + parity gate → guarded write via `with_user(salesperson)` → `_wa12_after_edit`.

**Does a tap re-check the parity gate?** Split decision, LOCKED:
- **q_items buffer pick:** NO re-match; bind directly. Reasoning: `pending.candidates` is matcher-sourced (the in-family enumeration or `suggestions`, both products the matcher surfaced), the candidate is re-validated `∈ pending.candidates` + `prod.exists()`, and the gate already held at mint time. Re-matching `prod.name` would be a verbatim catalogue name → always `exact`, a no-op tautology. Defence is membership + existence, not a re-match.
- **q_confirm draft pick:** YES re-match `prod.name` and assert `exact|strong`. Reasoning: the q_confirm write path goes through `_wa12_match_line`/the replace machinery which everywhere re-asserts the gate; staying consistent with that path is cheaper than auditing a bypass. Always passes (verbatim name) but keeps the draft write path uniform.

Either way **no path can bind a product outside the matcher's surfaced set.**

### 3c. Count branching + truncation + family-variant framing

Presenter `_wa12_send_pick(sess, target, kind, cand_ids, label, family, from_e164, raw_from)`. Meta limits VERIFIED against WA-6 usage: button title ≤20, list-row title ≤24, list rows ≤10.

```python
_WA12_BTN_TITLE = 20
_WA12_LIST_TITLE = 24
_WA12_LIST_MAX = 10

    def _wa12_send_pick(self, sess, target, kind, cand_ids, label, family,
                        from_e164, raw_from):
        PT = self.env["product.template"].sudo()
        secret = self.env["ir.config_parameter"].sudo().get_param(
            "database.secret") or ""
        cand_ids = [p for p in cand_ids if PT.browse(p).exists()]
        if not cand_ids:
            return self._wa6_reply(raw_from, from_e164, _(
                "I don't have a confident option for that — please re-type it."))
        # FRAMING: confident family variant vs genuinely unsure (C2 corrected).
        if kind == "variant":
            body = _("*%s* → %s — which one?") % (
                label, self._wa12_family_word(family))
        else:
            body = _("\"%s\" — did you mean one of these?") % label
        pick = lambda pid: wa_payload.encode(secret, "wa12_pick", sess.id, target, pid)
        skip = wa_payload.encode(secret, "wa12_pick_skip", sess.id, target)
        more = wa_payload.encode(secret, "wa12_pick_more", sess.id, target)
        n = len(cand_ids)
        if n <= 2:                                  # buttons + skip (<=3 total)
            buttons = [{"id": pick(p), "title": PT.browse(p).name[:_WA12_BTN_TITLE]}
                       for p in cand_ids]
            buttons.append({"id": skip, "title": _("None of these")[:_WA12_BTN_TITLE]})
            return self._wa6_send_buttons(raw_from, from_e164, body, buttons)
        # n>=3 -> LIST so a skip row never costs a candidate (B-BUG4 fix):
        show = cand_ids[:_WA12_LIST_MAX - 1] if n > _WA12_LIST_MAX else cand_ids
        rows = [{"id": pick(p), "title": PT.browse(p).name[:_WA12_LIST_TITLE],
                 "description": PT.browse(p).name} for p in show]
        if n > _WA12_LIST_MAX:
            rows.append({"id": more, "title": _("Type to narrow")[:_WA12_LIST_TITLE],
                         "description": _("None of these — type a few more words")})
            body += _("\n(showing the closest %d — or narrow it)") % len(show)
        else:
            rows.append({"id": skip, "title": _("None of these")[:_WA12_LIST_TITLE],
                         "description": ""})
        return self._wa6_send_list(raw_from, from_e164, body, _("Pick item"), rows)
```

Decisions (resolving critique A BUG-7/8, critique D BUG-4):
- **`n==3` uses a LIST, not 3 buttons** — so a "None of these" skip row never displaces a real candidate (3 picks + 1 skip = 4 rows ≤ 10). Pure buttons only for `n≤2` (+skip = ≤3 buttons).
- **`>10`: 9 real rows + 1 "Type to narrow"** (10 total). `wa12_pick_more` → `_wa12_pick_narrow` sets a transient `narrow_target` on the session so the NEXT free-text re-targets that slot (fixes critique A BUG-7's lost-slot-context dead-end). The narrow phrase re-runs the matcher scoped to `family` + the typed term.
- `_wa6_send_buttons`/`_wa6_send_list` already auto-fall-back to numbered text if Meta rejects the payload (VERIFIED wa6.py) — the numbered fallback is answerable by the C number grammar (§4). No new fallback machinery.

### 3d. The EXACT family-variant vs unsure signal (C2 corrected — derived in the BUILDER, matcher untouched)

In `_wa12_build_buf_lines` (q_items only), for each `_wa6_match_one` weak/not_found hit:

```python
        fam = h.get("family") or ""
        is_variant = bool(
            fam                                   # matcher scoped a real family
            and h.get("confidence") == "weak"     # not exact/strong (those auto-match)
            and self._wa12_is_family_term(h.get("raw"))  # rep NAMED a family, not a product
        )
        if is_variant:
            cand_ids = self._wa12_family_candidate_ids(fam)   # in-family enumeration (C1)
        else:
            cand_ids = self._wa12_suggestion_ids(h.get("suggestions") or [])  # [:3]
```

- `_wa12_is_family_term(raw)`: True when `raw` (after stopword strip) is essentially a bare family word/alias — reuse the matcher's own machinery via `self._r2_alias_expand(raw)[0] == "category"` OR `self._wa6_family_code(raw)` returns a code with no residue product token. This is the "rep named a family" test. (NOT a matcher change — a builder-side call into existing public helpers.)
- `_wa12_family_candidate_ids(fam)`: `allp.filtered(lambda p: self._wa6_in_family(p, fam))` mapped to ids, capped at 10. **This is C1's fix** — the 4 molefay variants come from here, NOT from `suggestions[:3]`. Gated on `fam` being a real category code → no cross-family leak.
- `_wa12_suggestion_ids(names)`: map each `suggestions` name → its `product.template` id by exact `_r2_norm` equality within `is_workshop_item`. Caps at 3 (the matcher's own cap).

So: **family-term + weak + a real family + ≥2 in-family products** → `kind="variant"`, "blinders → molefays — which one?", LIST of the in-family variants. **A thin/dimensional weak hit** (rep typed a specific-ish phrase, S4/S6b/S7 weak, NOT a bare family term) → `kind="ambiguous"`, "did you mean: …?", 2-3 buttons from `suggestions`. This is the ONLY place the two framings diverge; everything downstream is identical.

---

## 4. C — LINE-NUMBER EDIT

### 4a. Numbering

- **q_items `_wa12_items_confirm_text` (wa12.py:1431):** render `buf['lines']` with `enumerate(...,1)`. Matched: `"%d. %s ×%d @ %s%s"`. Unmatched: `"%d. ⚠️ \"%s\" — %s"` (where `%s` is "tap an option above" if this line is `pending.lid`, else the did-you-mean text). Number space is the single `lines` list, so "2" unambiguously targets the 2nd visible row whether matched or unmatched.
- **q_confirm `_wa12_draft_summary` (wa12.py:2238):** change `"• %s%s ×%g …"` to `"%d. %s%s ×%g …"` via `enumerate(quote.line_ids, 1)`. **VERIFIED** this is the exact recordset `_wa12_match_line` (line 1608) indexes — numbering aligns by construction (critique A BUG-5 closed).

### 4b. Command grammar (q_items, in `_wa12_q_items_try`)

A new `_wa12_line_by_number(buf, n)` (1-based over `buf['lines']`, None if out of range, with a refusal reply for out-of-range mirroring `find_one`). **The parse order is LOCKED and load-bearing** (critique D BUG-2) — number-leading commands need a keyword OR `=`/`->`; a bare leading int never eats a normal item:

Order inside `_wa12_q_items_try` (each tried before the existing token forms):
1. `client <name>` — unchanged.
2. **`<n> = <new>` / `<n> -> <new>`** — regex `^(\d+)\s*(?:=|->)\s*(.+)$` (**`:` excluded** to avoid time/ratio collision, critique D BUG-2). `find_by_number(g1)`; if not a valid index → return None (fall through, so "2x100 molefay" as a re-type still works); re-match `g2` through `_wa6_match_one`; `exact|strong` → swap product (`rep_price=None`); **weak-with-candidates → `_wa12_offer_pick_for_replace`** (B fallback).
3. `remove <tok>` — **FIX critique A BUG-4 / the silent multi-remove:** when `tok` is a bare int, resolve via `find_by_number` and remove EXACTLY that one line; only fall to the substring filter for non-numeric tokens. (Today `remove 3` substring-matches any name containing "3" and silently removes all — corrected.)
4. `qty <tok> <m>` — existing regex `qty\s+(.+?)\s+(\d+)`; `find_one` made number-aware (below) so `qty 2 4` and `qty 2 to 4` resolve "2" to the index.
5. `price <tok> <amt>` — existing F8 floor guard (`> _WA12_PLACEHOLDER_RATE`, line 962) preserved; number-aware `find_one`.
6. date — unchanged.
7. **re-typed item(s)** — existing path (lines 979-991); a bare leading int here is parsed as qty (e.g. "4 blinders" → qty 4 of blinders), NOT a line index. **This is the false-positive hinge.**

**Number-aware `find_one`** (the one shared resolver for replace/qty/price — `remove` handled separately per #3):
```python
        def find_by_number(tok):
            if not str(tok).strip().isdigit():
                return None, None
            ln = self._wa12_line_by_number(buf, int(tok))
            if ln is None:
                return None, self._wa6_reply(raw_from, from_e164, _(
                    "There's no line %s — you have %d.")
                    % (tok, len(buf.get("lines") or [])))
            return ln, None
        def find_one(tok):
            tok = (tok or "").strip()
            if tok.isdigit():                       # C: index wins for a bare int
                ln, err = find_by_number(tok)
                if ln is not None or err is not None:
                    return ln, err
            tok = tok.lower()
            hits = [ln for ln in buf["lines"]
                    if ln.get("kind") == "matched"
                    and tok in (ln.get("product_name") or "").lower()]
            ... (existing 0/>1 refusals)
```

**False-positive guard tests (NEW):** `qty 4 blinders` → `find_one("4 blinders")` (not bare int) → token path; `remove 3` with line 3 existing AND a "300W" product present → removes EXACTLY line 3, not the 300W; `4 blinders` → re-type qty 4 (not "line 4"); `2 = 4x100 molefay` → replace line 2.

### 4c. C at q_confirm

`_wa12_match_line` (line 1608) ALREADY does index-first. Add the `<n> = <new>` replace-by-index to `_wa12_try_edit` (parity-gated replacement, non-confident → pick offer for `l<line_id>`). Numbering `_wa12_draft_summary` (§4a) unlocks the rest with no further change.

---

## 5. D — CONVERSATIONAL (multi-item)

Reuse the existing translator pattern (`_wa12_llm_translate_items` wa12.py:1049 at q_items; `_wa12_llm_translate_edit` at q_confirm). Two surgical changes:

1. **Emit a LIST of commands** (one per line). System prompt gains: "output one command PER line, one per change; if a change names a line by position use `N = <item>`, else `<oldname> = <item>`." Inject the CURRENT numbered line list so the model can address by number. Returns `[cmd, ...]` or None.
2. **Cap + dedupe** (critique D BUG-9): cap at **6** commands/message; excess → "I caught a lot of changes — let's do them one at a time." Dedupe identical lines.

**Caller loop** in `_wa12_handle_convo` (q_items) — and symmetric in `_wa12_handle_session` (q_confirm) — refactors `_wa12_q_items_try` to take `batch=True` (mutate buf, return `'applied'|None`, NO per-command reply) so a batch yields ONE reshow:

```python
        cmds = self._wa12_llm_translate_items(raw, buf)
        if cmds:
            # FIX D-BUG3: two-pass — resolve every number-addressed command to a
            # stable lid BEFORE applying any mutation, so a `remove` earlier in
            # the batch can't shift the numbers a later command was generated
            # against. (Taps are lid-stable; typed number batches must be too.)
            resolved = self._wa12_batch_resolve_lids(buf, cmds)  # rewrites "N ..." -> "lid#L ..."
            applied = 0
            for cmd in resolved:
                if self._wa12_is_cancel(...): ...; if submit-word: continue
                if self._wa12_q_items_try(sess, buf, cmd, from_e164, raw_from, batch=True):
                    applied += 1
            if applied:
                sess._set_buffer(buf)
                return self._wa6_reply(raw_from, from_e164,
                                       self._wa12_items_confirm_text(buf))
```

`_wa12_batch_resolve_lids` maps each leading display-number against the PRE-batch `lines` to a `lid#<L>` sentinel token that `find_by_number` recognises directly (a `lid#` token bypasses positional lookup). This is critique D BUG-3's two-pass fix.

**Uncertain → B fallback is automatic:** each command re-runs through `_wa12_q_items_try`, and a non-confident replacement routes to `_wa12_offer_pick_for_replace` (which sends a pick and returns `'applied'`). So a multi-item sentence where one item is confident and one uncertain: the confident one applies, the uncertain one fires a B pick. **Single `pending` slot** (⚠️ DECISION, both designs agree): if TWO items go weak in one batch, only the first gets a pick offer; the second is flagged "still unmatched" in the reshow for the rep to resolve next. This keeps the tap→line binding provably unambiguous.

**Critical fix (critique A BUG-3 / critique D's same observation):** the EXISTING `replace <old> = <new>` path (wa12.py:899-917) currently returns a **text** "did you mean" reply (lines 908-913), NOT a B pick. Replace that text block with `return self._wa12_offer_pick_for_replace(...)` so ALL three lanes' non-confident replace converge on B buttons, satisfying the ratified "uncertain → B fallback, never a re-type prompt."

---

## 6. PRECEDENCE (decision tree, both steps)

```
INBOUND (q_items OR q_confirm session live for this phone)
│
├─ type == 'text' AND body ∈ {STOP,START,...}  → return None (opt-out, super())   [existing]
│
├─ 1. TAP (interactive button_reply/list_reply, OR template-QR text)
│     ├─ wa12_pick* sentinel → _wa12_handle_pick_tap → apply DIRECTLY (lid/line stable)   ◄ HIGHEST
│     └─ wa12_approve/reject/view_pdf/send → _wa12_handle_tap                              [existing]
│
├─ 2. pending follow-up (q_items only): buf.pending set AND a bare word/phrase
│     (not a command/yes/cancel) → narrow candidates for pending.lid (scoped re-match)
│
├─ 3. NUMBER-LED command  (C):  `N = …`, `remove N`, `qty N to M`, `price N amt`
│     → _wa12_q_items_try / _wa12_try_edit  (index resolve → funnel re-match → parity gate)
│
├─ 4. NAME-LED command:  `replace X = Y`, `qty X N`, `remove X`, `price X amt`, date, client
│     → same try-methods (find_one token path)
│
├─ 5. FREE text (D): LLM → [cmds] → two-pass lid resolve → each re-run through #3/#4 funnel
│     → uncertain replacement → B pick offer (never a guess)
│
└─ 6. fallback: re-typed confident item adds (existing) → else syntax card / surface_unmatched (→ B)
```

Invariant: a **tap** is structurally highest (different message type, caught at intercept step 1). A **number** resolves before token/free-text by being parsed first in the try-methods. **Free text** is last (LLM → deterministic re-run). All five terminate in `_wa6_match_one` + `confidence in (exact,strong)`.

---

## 7. GUARD PRESERVATION (the SACRED parity / no-$0 / no-raw-string wall)

The chokepoint is `hit['status']=='matched' and hit['confidence'] in ('exact','strong')` + `_wa12_unpriced_lines` (no $0) + `_wa12_build_lines` (always a real `product_id`). Per lane:

- **B (q_items tap):** binds only a `product_id ∈ pending.candidates`; those candidates come ONLY from `_wa12_family_candidate_ids` (in-family enumeration, `fam` a real category code → no cross-family, no raw string) or `_wa12_suggestion_ids` (matcher `suggestions`). Re-validated `prod.exists()` + membership. `rep_price=None, stated_price=None` on bind → a no-catalogue-rate pick still renders "no rate set — blocks submit" via UNCHANGED `_wa12_unpriced_lines`. **No $0, no raw string, no out-of-set product.**
- **B (q_confirm tap):** additionally re-matches `prod.name` and asserts `exact|strong`.
- **C (number):** `<n> = <new>` and verb forms route the **replacement term** through `_wa6_match_one` + the existing `exact|strong` block (wa6/wa12.py:906-907); the index resolver only selects WHICH existing line, never the new product's confidence. `price <n> amt` keeps the `> _WA12_PLACEHOLDER_RATE` floor (line 962) and the catalogue-rate-wins logic.
- **D (free-text):** the LLM emits ONLY deterministic command strings (no product id, no price); each re-runs the funnel + gate. Multi-item changes nothing — each command is independently gated. Two-pass lid resolution touches targeting, never the match gate.
- **Family-variant pick:** `family_pick`/`kind="variant"` changes ONLY the prompt wording; the candidate set is matcher-sourced (in-family), the bind path identical.
- **$0 / unpriced / money wall:** all of B/C/D operate PRE-DRAFT at q_items (no total, no PDF, no approval reachable until `yes`→existing draft path→existing approval gate). The `yes`-projection rebuilds `matched` from `kind=='matched'` lines only — an unresolved/pending line can't be drafted. **The redesign adds ZERO money surfaces.** The three live parity gates (`_wa12_match_slot_items`, `_wa12_match_text_items`, `_wa12_run_price`) are untouched.

---

## 8. METHOD MAP

`addons/neon_channels/models/wa_payload.py`: add `wa12_pick`, `wa12_pick_more`, `wa12_pick_skip` to `INTENTS`.

`addons/neon_crew_comms/models/whatsapp_message_wa6.py`: **NO CHANGE.** (Both designs proposed touching `_wa6_match_one` for `family_pick`; C2's correction makes that unnecessary — the signal is derived builder-side. The matcher stays byte-identical, closing critique A BUG-10's snapshot risk entirely.)

`addons/neon_crew_comms/models/wa_equip_session.py`: **NO model-field change.** Buffer helpers live on the WA-12 mixin; `narrow_target` (the >10 transient) is stored INSIDE the JSON buffer (`buf['narrow_target']`), not a new column. (`_get_buffer`/`_set_buffer`/`_active_for_phone`/`phone_number`/`last_inbound` all reused — VERIFIED.)

`addons/neon_crew_comms/models/whatsapp_message_wa12.py` — NEW:
| Method | Purpose |
|---|---|
| `_wa12_buf_migrate(buf)` | legacy→v3 fold, idempotent |
| `_wa12_build_buf_lines(text)` | v3 `lines` from `_wa6_match_one` hits; sets `_cand_ids`/`_variant` (q_items ONLY) |
| `_wa12_line_by_lid(buf, lid)` / `_wa12_line_by_number(buf, n)` / `_wa12_add_line(buf, **kw)` | line primitives |
| `_wa12_set_pending / _wa12_clear_pending_for(buf, lid)` | pending slot |
| `_wa12_is_family_term(raw)` | "rep named a family" via `_r2_alias_expand`/`_wa6_family_code` |
| `_wa12_family_candidate_ids(fam)` | in-family enumeration → ids (C1 fix) |
| `_wa12_suggestion_ids(names)` | `suggestions`→ids |
| `_wa12_family_word(fam)` | "blinders"/"screens" for the prompt |
| `_wa12_send_pick(...)` | count-branching presenter (§3c) |
| `_wa12_handle_pick_tap(...)` | B tap entry (§3b) |
| `_wa12_pick_apply_buffer / _wa12_pick_apply_draft` | bind to q_items lid / q_confirm line |
| `_wa12_pick_narrow(...)` | >10 narrow; sets `buf['narrow_target']` |
| `_wa12_offer_pick_for_replace(sess, buf, target_ln, new_hit, ...)` | non-confident replace → B pick |
| `_wa12_batch_resolve_lids(buf, cmds)` | two-pass: number→`lid#L` pre-mutation (D-BUG3) |

CHANGED (signatures stable except noted):
| Method | Change |
|---|---|
| `_wa12_extract_tap` | read `list_reply.id`; pick sentinel BEFORE `startswith("wa12_")` (§3a) |
| `_wa12_maybe_intercept` | branch the pick sentinel before `_wa12_handle_tap` (§3a) |
| `_wa12_q_items_try` | **+`batch=False` arg**; `find_by_number`+number-aware `find_one`; `<n> = <new>` regex; `remove` bare-int fix; existing `replace` non-confident → `_wa12_offer_pick_for_replace` |
| `_wa12_items_confirm_text` | render v3 `lines`, 1-based numbers, pending-aware + variant/unsure head |
| `_wa12_draft_summary` | `enumerate(quote.line_ids,1)` numbering |
| `_wa12_open_items_confirm` | build v3 buffer via `_wa12_build_buf_lines`; offer pick on the active unmatched/variant line |
| `_wa12_try_edit` | `<n> = <new>` replace-by-index; non-confident → pick for `l<line_id>` |
| `_wa12_llm_translate_items` / `_wa12_llm_translate_edit` | return LIST (one cmd/line), cap 6 + dedupe |
| `_wa12_handle_convo` / `_wa12_handle_session` | loop translated lists; two-pass lid resolve; one reshow |
| `_wa12_surface_unmatched` | write via `_wa12_add_line(kind='unmatched')` on v3 buffer (no legacy keys, D-BUG8) |

**REUSED unchanged:** `_wa6_match_one`, `_wa6_match_items`, `_wa6_in_family`, `_wa6_family_code`, `_r2_alias_expand`, `_wa6_send_buttons`, `_wa6_send_list`, `_wa6_reply`, `_wa12_match_line`, `_wa12_match_text_items` (2-tuple contract preserved — D-BUG7), `_wa12_match_slot_items`, `_wa12_build_lines`, `_wa12_quote_from_slots`, `_wa12_unpriced_lines`, `_wa12_price_lookup`, `_wa12_can_quote`, `_wa12_after_edit`, `_wa12_apply_multi`, the approve/reject `_WA12_LOCK_NS`.

---

## 9. TEST PLAN (`.claude/pwa12_3_pick_smoke.py`; drive `_wa12_maybe_intercept` end-to-end: command → present → synth tap → receive)

NEW tests:
1. `pwa12_3_pick_buttons_le2` — q_items, a 2-candidate ambiguous unmatched row → assert `_wa6_send_buttons` with 2 `wa12_pick` ids + a `wa12_pick_skip`; synth `interactive.button_reply.id` → assert the line becomes `kind=matched` at that product, pending cleared.
2. `pwa12_3_pick_list_3` — exactly 3 candidates → assert a LIST (not 3 buttons), 3 pick rows + 1 skip row, no candidate dropped (B-BUG4).
3. `pwa12_3_pick_list_4to10` / `pwa12_3_pick_list_over10` — 4-10 → list ≤10, full names in description; >10 → 9 real + 1 `wa12_pick_more`, titles ≤24.
4. `pwa12_3_family_variant` — a confirmed CATEGORY alias resolving weak to ≥2 in-family products → assert candidates come from in-family enumeration (NOT `suggestions[:3]`), `kind=variant`, head reads "→ … — which one?" not "did you mean" (C1+C2).
5. `pwa12_3_stable_lid` — **the core state test:** offer pick on lid=2 → `remove 1` (numbers shift; lid=2 now displays as #1) → synth the OLD `wa12_pick:sid:b2:pid` tap → assert it still binds lid=2, NOT the shifted line.
6. `pwa12_3_cross_session` — start session A (offer pick, lid=2) → cancel → start session B (new sid) → tap A's stale `wa12_pick:<sidA>:b2:pid` → assert "expired" (sid mismatch), NOT a bind in B (D-BUG5).
7. `pwa12_3_number_replace` — `2 = <confident>` swaps; `2 = <weak>` → B pick; **false-positives:** `qty 4 blinders` adds qty 4 (NOT line 4); `4 blinders` re-type qty 4; `remove 3` with a "300W" product present removes EXACTLY line 3 (D-BUG4/remove fix).
8. `pwa12_3_number_order` — `qty 2 to 4` resolves line 2 qty 4 (qty rule before replace); `2 = …` is replace; `:`-form is NOT a replace separator.
9. `pwa12_3_conversational_multi` — "the blinders are the 4x100 indoor ones and smoke is the upright one" → translator emits 2 cmds → both applied in ONE reshow (LLM stubbed deterministic); one weak → B pick; LLM muted → deterministic forms still resolve.
10. `pwa12_3_batch_remove_shift` — LLM emits `["remove 2","qty 3 to 5"]` → assert two-pass lid resolution edits the ORIGINAL line 3, not the post-removal line 3 (D-BUG3).
11. `pwa12_3_pick_tap_q_confirm` — a draft line `wa12_pick:sid:l<line_id>:pid` → re-match + guarded write via `_wa12_match_line` + `_wa12_after_edit`.
12. `pwa12_3_guard_parity` — forged `wa12_pick` id for a non-workshop/placeholder-rate product (not in `pending.candidates`) → refused; stale session → "expired"; phone mismatch → two-factor refusal; LLM emitting a `price`/raw-string product → still gated.
13. `pwa12_3_narrow_over10` — `wa12_pick_more` sets `narrow_target`; the next bare phrase re-targets that slot scoped to its family (B-BUG7).
14. `pwa12_3_cap6` — LLM emits 9 commands → "one at a time", ≤6 applied path (D-BUG9).
15. `pwa12_3_buf_migrate` — a v-absent legacy `{matched,unmatched}` buffer migrates to v3 and resolves a subsequent number command (D-BUG8); assert no path leaves both `lines` and `matched`/`unmatched`.

REGRESSION (must stay green, NO new failures vs baseline):
- `pwa12` full suite (existing q_items/q_confirm deterministic + LLM-translate + multi + price F8).
- `pwa6` (Face-2 matcher BYTE-UNCHANGED — `_wa6_match_one` not touched; assert `hit()` dict keys unchanged → critique A BUG-10 moot).
- `pwa7`, `pwa10` tap routing through the shared bridge unchanged (the `list_reply` `or` and the pick-sentinel branch are additive; `wa6_fixrow` stays index-based and untouched).
- `wa_payload` encode/decode: assert a `wa12_pick` payload does NOT resolve to a quote recordset (D-BUG6 regression guard); assert decode of WA-5/6/7/10/13 ids unchanged.

---

## 10. RISKS / OPEN

- **⚠️ DECISION (single `pending` slot):** one line awaits a pick at a time. Two weak items in one D batch → first offered, second flagged in the reshow for sequential resolution. Multi-pending would reintroduce the "which ask is this tap answering" ambiguity the redesign exists to kill. LOCKED as single-slot.
- **⚠️ DECISION (matcher untouched):** `family_pick`/variant signal is derived in the WA-12 builder (`_wa12_is_family_term` + in-family enumeration), NOT a new matcher key. This corrects both designs (C2) and keeps `_wa6_match_one` byte-identical, so the Face-2/WA-6/8 consumers and their snapshot tests are provably unaffected.
- **OPEN (LOW, build-time decision):** `_wa12_is_family_term` precision — a rep typing "blinder lights for the stage" (family word + noise) should still read as a family term. The `_r2_alias_expand[0]=='category'` test handles the alias case; the `_wa6_family_code(raw)` + no-residue-product-token test handles the synonym case. If a real proof shows a family phrase with descriptive noise mis-routing to "did you mean", widen the residue tolerance (mirror `_r2_alias_expand`'s `_WA6_GENERIC_NOUN` residue logic, wa6.py:992-994). Log to polish backlog if it surfaces; not a build blocker.
- **OPEN (LOW):** `_wa12_family_candidate_ids` cap at 10 for the LIST. If a family legitimately has >10 stocked variants, the `>10` narrow path (9+narrow) handles it; rare for the current catalogue. No new state.
- **NOT money-adjacent, NOT a real-phone send, NOT a migration:** the entire build is pre-draft buffer/correction logic + tests on `[TEST-*]` fixtures through synthesised inbound dicts. Within autonomy per CLAUDE.md SAFE-DEPLOY. The first real WA send (the approval ping / client send) remains the EXISTING WA-12 hard-gated path — unchanged by this layer.

**Files (absolute):**
- `C:\Users\Neon\neon-odoo\addons\neon_crew_comms\models\whatsapp_message_wa12.py` — all WA-12.3 logic.
- `C:\Users\Neon\neon-odoo\addons\neon_channels\models\wa_payload.py` — 3 new intents.
- `C:\Users\Neon\neon-odoo\addons\neon_crew_comms\models\whatsapp_message_wa6.py` — **no change** (matcher byte-identical).
- `C:\Users\Neon\neon-odoo\addons\neon_crew_comms\models\wa_equip_session.py` — **no change** (`narrow_target` lives in the JSON buffer).
- `.claude\pwa12_3_pick_smoke.py` — new test suite.

**Bug disposition vs the two critiques:** critique-A BUG-1 (handler-slot crash) fixed §3a; BUG-2 (`family_pick` mis-set) fixed by C2 builder-side derivation; BUG-3 (existing `replace` text path) fixed §5; BUG-4 (`remove` silent multi-delete) fixed §4b; BUG-5/6 (field/order) verified `phone_number` + order locked; BUG-7/8 (3-button no escape / count) fixed via n==3→LIST §3c + narrow_target; BUG-9 (LLM runaway) cap-6 §5; BUG-10 (snapshot) moot (matcher untouched). critique-D BUG-1 (4-variant unbuildable) fixed by in-family enumeration C1 §3d; BUG-2 (parse order/`:`) locked §4b; BUG-3 (batch number-shift) two-pass §5; BUG-4 (3rd candidate dropped) §3c; BUG-5 (cross-session lid) sid-match §3b; BUG-6 (intent shadowed) §3a; BUG-7 (5-caller arity) 2-tuple preserved + new builder §1; BUG-8 (legacy keys persist) migrate-on-read + `surface_unmatched` rewrite §8.