# WA-12.4 — One-Item Stepper LOCKED SPEC (design wf_f123c981-90c, 2026-06-13)

Supersedes WA12_3 for the q_items INITIAL resolution. Matcher/prices/guards BYTE-UNCHANGED.
2 designs + 2 adversarial critiques, source-verified. Build->test->HOLD at deploy (user directive).

I now have full ground truth. Key confirmations for the locked spec:

- `_wa12_send_pick(self, sess, target, kind, cand_ids, label, family, from_e164, raw_from)` — `target` is positional #2, no `counter` kwarg. Encodes via `sess.id`. Row description = bare `PT.browse(p).name` (BUG-3 real).
- `_wa12_family_word("lighting")` → "lights", never "molefays" (BUG-4 real); `_r2_alias_expand` returns `(kind, val, expanded)` with `kind=="term"`/`val` carrying the alias word.
- `_wa12_extract_tap` only sentinels `wa12_pick/_more/_skip`; all other `wa12_*` browse `parts[0]` as a quote id → wrong record for `wa12_ok` etc. (BUG-1/3/5 confirmed, single root).
- `_wa12_handle_pick_tap` step gate (1229) admits only `("q_items","q_confirm")` (BUG-2 confirmed).
- `_wa12_buf_migrate` is v3-terminal (`v==3 and "lines" in buf → return unchanged`); must extend to v4 without wiping a live `pending` (BUG-12).
- Greeting (734), discovery (759), submit (785), show/continue (830), complaint (838) all sit ABOVE `_wa12_q_items_try` and call `_wa12_items_confirm_text` (BUG-14 real — fork must precede them, and continue/show must delegate to cursor presenter).
- `_WA12_PLACEHOLDER_RATE` price guard pattern at 1498–1519 is the template.
- `_wa12_open_items_confirm` called from `q_itemreq` path (779) with the locked positional signature; `days` defaults to 1 in the buffer (line 2084), not passed as arg.

Here is the locked build spec.

---

# WA-12.4 — One-Item Stepper (Cursor + Focused Sub-State): LOCKED BUILD SPEC

Ground truth verified line-by-line in `addons/neon_crew_comms/models/whatsapp_message_wa12.py` and `addons/neon_channels/models/wa_payload.py` on `feat/wa6-equipment-face`, 2026-06-13. This spec synthesises the two designs (cursor-substate + queue-walk), adopts the cursor model as the base (simpler — no separate `queue`/`resolved`/`seq` ledger; the cursor is derived from per-line `state`), and folds in the **idempotency** strength of the queue-walk design via a per-presentation `seq` token. **Every HIGH and MED bug from both critiques is fixed and called out by ID below.**

This is the WA-12 lane — money-adjacent + a new interactive surface → **⛔ Gate-1 + Robin before build** per the standing money wall (same gate WA-12 itself took). Build only after Robin approves.

---

## (1) BUFFER / CURSOR SCHEMA — v3 → v4

The v3 `lines[]` shape is preserved (the yes-projection at 790–795, the C/D edit grammar, `_wa12_line_by_lid`, `_wa12_line_by_number` all read it). v4 adds a **cursor**, a **focus flag**, a per-presentation **seq**, and a per-line **state**. `pending` is retained but its semantics narrow (see below).

### Per-line addition

```python
line = {lid, kind:'matched'|'unmatched',
        state:'pending'|'confirmed'|'picked'|'skipped',   # NEW (v4)
        product_id, product_name, qty, rep_price, stated_price,
        raw, suggestions, family, _variant, _cand_ids}
```

- **`pending`** — not yet resolved. The cursor stops at the first such line.
- **`confirmed`** — a confident line the rep tapped **✓ Correct** (or typed `ok`/`correct`).
- **`picked`** — bound via a LIST tap or a confident re-type/narrow.
- **`skipped`** — rep tapped **✗ → Skip** / typed `skip`/`remove`/`drop`. Kept in the buffer for audit; **never drafted, never deleted** (⚠️ DECISION D-SKIP, see below — diverges from queue-walk D2).

### Top-level additions

```python
buf = {v:4, next_lid, lines:[...],
       cur:   <lid|None>,    # NEW — the line being resolved RIGHT NOW
       focus: <bool>,        # NEW — True iff in focused sub-state
       seq:   <int>,         # NEW — per-presentation idempotency token (monotonic)
       pending: {...}|None,  # EXISTING — the tap offer for buf['cur']; carries 'seq'
       client_txt, partner_id, date_txt, days, prefills,
       narrow_target?}       # EXISTING — now scoped to the cursor
```

### `pending` (the offer slot) — shape with seq

```python
buf['pending'] = {lid:<cur>, kind:'confirm'|'variant'|'ambiguous',
                  candidates:[product_ids], label, family,
                  overflow:bool, seq:<int>}   # seq == buf['seq'] at send-time
```

### Invariants (encode in `_wa12_assert_focus(buf)`, assert at every presenter entry)

- `buf['focus']` is True ⇔ `buf['cur']` is a live lid whose line `state == 'pending'`.
- When `pending` is set: `pending['lid'] == buf['cur']` and `pending['seq'] == buf['seq']`.
- The cursor always points at the **first `state=='pending'` line in list order**.

### What "resolved" means

A line is **resolved** when `state in ('confirmed','picked','skipped')`. The walk is complete when **no `pending` line remains**. `days`/`date_txt`/`client_txt`/`partner_id` are buffer-header fields, **not** cursor lines — focused edits to them mutate the header and re-present the **same** cursor item (no advance).

### v3→v4 migration (fixes **BUG-12**)

`_wa12_buf_migrate` currently returns a `v==3` buffer unchanged. Extend it so the v3→v4 fold:
- stamps `state='pending'` on every existing line (both matched and unmatched);
- adds `cur=None, focus=False, seq=0`;
- **preserves any live `pending`** (do NOT force it null — a pre-deploy session mid-pick keeps its disambiguation). Use `buf.setdefault('cur', None)`, `buf.setdefault('focus', False)`, `buf.setdefault('seq', 0)`, and leave `pending` untouched.
- idempotent: a `v==4` buffer returns unchanged.

```python
def _wa12_buf_migrate(self, buf):
    if not isinstance(buf, dict):
        return {"v": 4, "next_lid": 1, "lines": [], "pending": None,
                "cur": None, "focus": False, "seq": 0}
    if buf.get("v") == 4 and "lines" in buf:
        return buf
    if buf.get("v") == 3 and "lines" in buf:
        for ln in buf.get("lines") or []:
            ln.setdefault("state", "pending")
        buf.setdefault("cur", None)
        buf.setdefault("focus", False)
        buf.setdefault("seq", 0)
        buf["v"] = 4
        return buf                       # pending PRESERVED (BUG-12)
    # ... legacy {matched,unmatched} fold (unchanged) then stamp v4 fields ...
    # (build lines as today, then:)
    for ln in lines:
        ln["state"] = "pending"
    buf.update({"lines": lines, "next_lid": lid, "v": 4,
                "cur": None, "focus": False, "seq": 0})
    buf.setdefault("pending", None)
    buf.pop("matched", None); buf.pop("unmatched", None)
    return buf
```

A pre-deploy `q_items` session whose buffer was `v3` with no focus folds to `focus=False`, so it lands in the **post-walk** (existing) grammar — the safe degrade. It never re-enters the stepper (the stepper only opens fresh at `_wa12_open_items_confirm`).

### Cursor helpers + advance (single exit for "resolved one item")

```python
def _wa12_first_unresolved(self, buf):
    return next((ln for ln in buf.get("lines") or []
                 if ln.get("state") == "pending"), None)

def _wa12_advance_cursor(self, sess, buf, from_e164, raw_from):
    buf["pending"] = None
    nxt = self._wa12_first_unresolved(buf)
    if nxt is None:
        buf["cur"] = None
        buf["focus"] = False
        sess._set_buffer(buf)
        return self._wa12_finalize_to_draft(sess, buf, from_e164, raw_from)  # (5)
    buf["cur"] = nxt["lid"]
    buf["focus"] = True
    sess._set_buffer(buf)
    return self._wa12_present_item(sess, buf, nxt, from_e164, raw_from)       # (3)
```

⚠️ DECISION D-NOAUTO: a confident (exact/strong) line is born `state='pending'` and shown for a ✓/✗ — we do **not** auto-confirm. The ratified v2 brief is "each in its own message with a counter"; auto-confirm would silently skip a wrong-but-confident match.

---

## (2) DISPATCH DECISION TREE at `q_items` while focused on item N

### Entry fork in `_wa12_handle_convo` (fixes **BUG-14**)

The cancel check (715–727) is unchanged. **Immediately after cancel, BEFORE greeting (734) / discovery (759) / submit (785) / show-continue (830) / complaint (838)**, insert the focus fork. This placement is load-bearing: those five branches currently call `_wa12_items_confirm_text` (the legacy combined block) and would re-create Robin's confusion mid-step.

```python
buf = self._wa12_buf_migrate(sess._get_buffer())   # now yields v4

if self._wa12_is_cancel(norm):                     # global; already above
    sess.sudo().write({"step": "done", "active": False})
    return self._wa6_reply(raw_from, from_e164, _("Quote cancelled."))

# WA-12.4: the FOCUSED SUB-STATE owns the turn. Gated on step==q_items AND
# focus (BUG-4 defence: can never fire at q_confirm even with a dirty buffer).
if sess.step == "q_items" and buf.get("focus") and buf.get("cur"):
    return self._wa12_focus_dispatch(sess, buf, raw, norm, from_e164, raw_from)

# ---- UNFOCUSED (all items resolved => post-draft, or legacy) : existing grammar ----
# greeting / q_client / discovery / submit / show / complaint / q_items_try / D / surface
```

Inside focus, `continue`/`show`/greeting do **not** reach the legacy block; the focused tree handles them (a greeting/continue → re-present the cursor; see branch 7).

### `_wa12_focus_dispatch` — the ordered tree (PROVABLY cannot spawn a line)

`N = buf['cur']`, `ln = _wa12_line_by_lid(buf, N)`. First match wins.

```python
def _wa12_focus_dispatch(self, sess, buf, raw, norm, from_e164, raw_from):
    """ALL input applies to buf['cur'] only. The ONLY line-creating verb on
    this path is an explicit 'add <item>'. No _wa12_q_items_try, no
    _wa12_surface_unmatched, no LLM-translate is reachable while focused."""
    import re
    sender = sess.user_id
    if not (sender and sender.active and self._wa12_can_quote(sender)):
        sess.sudo().write({"active": False})
        return self._wa6_reply(raw_from, from_e164, _(_WA12_REFUSAL))
    ln = self._wa12_line_by_lid(buf, buf["cur"])
    if ln is None:                                   # cursor vanished -> re-anchor
        return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)

    # 1) explicit 'add <item>' — the ONLY new-line verb. Tight: ^add\s+(.+)$.
    m = re.match(r"^add\s+(.+)$", raw, re.I)
    if m:
        return self._wa12_focus_add_item(sess, buf, m.group(1).strip(),
                                         from_e164, raw_from)

    # 2) skip / remove / drop THIS item -> state='skipped', advance. (BUG-6:
    #    'next' is NOT a drop synonym; bare 'next'/'ok'/'correct' = CONFIRM, br.4)
    if norm in _WA12_SKIP_WORDS:
        ln["state"] = "skipped"
        return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)

    # 3) header edits — re-present the SAME item (NO advance):
    m = re.match(r"^client\s+(.+)$", raw, re.I)
    if m:
        partner, _c = self._wa12_client_candidates(m.group(1).strip())
        buf["client_txt"] = partner.name if partner else m.group(1).strip()
        buf["partner_id"] = partner.id if partner else False
        sess._set_buffer(buf)
        return self._wa12_present_item(sess, buf, ln, from_e164, raw_from)
    ev_date, ph = self._wa12_resolve_date(raw)
    if not ph:
        buf["date_txt"] = ev_date.isoformat(); sess._set_buffer(buf)
        return self._wa12_present_item(sess, buf, ln, from_e164, raw_from)
    if re.match(r"^qty\s+(?:to\s+)?\d+\s*$", norm) and ln.get("kind") == "matched":
        ln["qty"] = max(1, int(re.search(r"\d+", norm).group()))
        sess._set_buffer(buf)
        return self._wa12_present_item(sess, buf, ln, from_e164, raw_from)
    m = re.match(r"^price\s+([0-9]+(?:\.[0-9]+)?)\s*$", norm)
    if m and ln.get("kind") == "matched":
        return self._wa12_focus_price(sess, buf, ln, float(m.group(1)),
                                      from_e164, raw_from)

    # 4) bare confirm words on a CONFIDENT card = CONFIRM-AND-ADVANCE (BUG-6).
    if ln.get("kind") == "matched" and norm in _WA12_CONFIRM_WORDS:
        ln["state"] = "confirmed"
        return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)

    # 5) a redirected 'yes'/'submit' inside focus -> NOT a draft; nudge.
    if norm in _WA12_SUBMIT_WORDS:
        return self._wa6_reply(raw_from, from_e164, _(
            "Let's finish item %s first — tap an option, type the item, "
            "or 'skip'.") % self._wa12_counter(buf, ln))

    # 6) QUESTION / unrecognised -> HELP + RE-SHOW N. Never matches catalogue,
    #    never creates a line. (BUG-7 fix: confident/family retype WINS first.)
    if not self._wa12_retype_confident(raw) or self._wa12_is_question(raw):
        self._wa6_reply(raw_from, from_e164, self._wa12_focus_help(buf, ln))
        return self._wa12_present_item(sess, buf, ln, from_e164, raw_from)

    # 7) a deliberate CONFIDENT/family RE-TYPE of N -> re-match through the
    #    funnel, bind N (confident) or re-frame N's LIST (weak/family). Never adds.
    return self._wa12_focus_retype(sess, buf, ln, raw, from_e164, raw_from)
```

**Greeting/continue while focused:** `_WA12_GREETINGS` and `_WA12_SHOW_WORDS`/`_WA12_RESUME_WORDS` are checked at the **top of branch 6's classifier** by routing them into `_wa12_is_question` → HELP+reshow (i.e. they re-present the cursor, not the legacy block). Concretely, extend the question classifier so a greeting/show/continue token returns "treat as meta" → reshow N. This satisfies **BUG-14** without a separate branch.

**Proof a new line cannot be spawned mid-pick (the Robin bug, wire 618–629):** the only `_wa12_add_line` callers reachable from `q_items` are (a) the re-typed-item branch of `_wa12_q_items_try` (1530–1549), (b) `_wa12_surface_unmatched` (930), (c) `_wa12_build_buf_lines` at extraction, (d) the LLM-translate batch (876–896), and (e) the new explicit `add` path. While `buf['focus']` is True, `_wa12_handle_convo` returns at the fork **above** (a)/(b)/(d). Branch 6 routes a question/unrecognised text to HELP (no match, no append). Branch 7 (`_wa12_focus_retype`) only ever **mutates the cursor line in place** (preserved `lid`), never appends. The sole append is branch 1's tight `^add\s+(.+)$`. Structural, not heuristic.

### Question-vs-retype test (fixes **BUG-7**: confident/family retype wins over a soft `?`)

```python
_WA12_Q_TOKENS = ("?", "where", "how", "what", "which", "why", "who",
                  "when", "help", "do i", "can i", "should i", "tap",
                  "explain", "confused", "i dont", "i don't")

def _wa12_retype_confident(self, raw):
    """True iff the whole message confidently re-identifies a product, OR
    names a family the picker can resolve. Reuses the byte-unchanged matcher."""
    hit = self._wa6_match_one(raw)
    if hit.get("status") == "matched" and hit.get("confidence") in (
            "exact", "strong"):
        return True
    fam = hit.get("family") or self._wa6_family_code(raw) or ""
    return bool(fam and self._wa12_is_family_term(raw)
                and self._wa12_family_candidate_ids(fam))

def _wa12_is_question(self, raw):
    low = " ".join((raw or "").lower().split())
    if not low:
        return True
    # greeting / show / continue mid-step = meta -> reshow (BUG-14)
    if low in _WA12_GREETINGS or low in _WA12_SHOW_WORDS \
            or low in _WA12_RESUME_WORDS:
        return True
    if "?" in low:
        return True
    return any(low == t or low.startswith(t + " ") for t in _WA12_Q_TOKENS)
```

**Ordering in branch 6** is `not _wa12_retype_confident(raw) or _wa12_is_question(raw)`: a **confident/family** message that happens to carry `?` (e.g. `"4x100 molefay?"`) still reaches branch 7 only if it is NOT a question — but since `?` forces `is_question` True, such a message goes to HELP. That is the safe choice (rep is asking); they re-tap or re-type cleanly. A bare confident product with no `?` (`"4x100 molefay"`) → `retype_confident` True, `is_question` False → branch 7 binds. `"where do I tap"` → `retype_confident` False → HELP+reshow (**the exact Robin failure, now caught**). `"smoke machine"` (weak, family/suggestion-bearing) → `retype_confident` True via family, `is_question` False → branch 7, which stays on N in pick mode.

### Constants

```python
_WA12_SKIP_WORDS    = ("skip", "skip it", "remove", "remove this", "drop",
                       "drop it", "none of these")   # 'next' REMOVED (BUG-6)
_WA12_CONFIRM_WORDS = ("ok", "okay", "correct", "yes that", "right", "next",
                       "looks good", "good", "confirm")   # bare-confirm on a card
_WA12_NUM           = {1:"①",2:"②",3:"③",4:"④",5:"⑤",6:"⑥",
                       7:"⑦",8:"⑧",9:"⑨",10:"⑩"}   # >10 -> "(N)"
```

⚠️ DECISION D-SKIP: `skip`/`remove`/`drop`/"None of these" all set `state='skipped'` — the line stays in the buffer (audit) but is excluded from the draft by the projection filter. We do **not** delete the line (queue-walk D2 deleted it). Reason: the audit-trail discipline in CLAUDE.md and the stable-lid contract — an old `wa12_pick` payload for a since-dropped lid should resolve to a known `skipped` line, not a vanished one. `_wa12_line_by_number` for the final draft already only sees matched lines via the projection.

---

## (3) PRESENTERS

```python
def _wa12_pos(self, buf, ln):
    return (buf.get("lines") or []).index(ln) + 1

def _wa12_counter(self, buf, ln):
    i, n = self._wa12_pos(buf, ln), len(buf.get("lines") or [])
    return _("%s of %d") % (_WA12_NUM.get(i, "(%d)" % i), n)

def _wa12_present_item(self, sess, buf, ln, from_e164, raw_from):
    self._wa12_assert_focus(buf)
    buf["seq"] = (buf.get("seq") or 0) + 1          # fresh idempotency token
    if ln.get("kind") == "matched":
        return self._wa12_present_confident(sess, buf, ln, from_e164, raw_from)
    return self._wa12_present_pick(sess, buf, ln, from_e164, raw_from)
```

### Confident (exact/strong) → `[✓ Correct][✗ Change]` with counter

```python
def _wa12_present_confident(self, sess, buf, ln, from_e164, raw_from):
    secret = self.env["ir.config_parameter"].sudo().get_param(
        "database.secret") or ""
    prod = self.env["product.template"].sudo().browse(ln["product_id"])
    rate, cur = self._wa12_price_lookup(prod)
    if rate is not None and rate > _WA12_PLACEHOLDER_RATE:
        money = "%s %.2f/day" % (cur, rate)
    elif ln.get("rep_price"):
        money = _("%s %.2f/day (rep-priced)") % (cur, ln["rep_price"])
    else:
        money = _("no rate yet — reply `price <amt>`")
    body = _("%s\n✅ *%s* ×%d — %s") % (
        self._wa12_counter(buf, ln), prod.name, ln.get("qty") or 1, money)
    sq = buf["seq"]
    self._wa12_set_pending(buf, ln["lid"], "confirm", [prod.id],
                           prod.name, ln.get("family") or "", seq=sq)
    sess._set_buffer(buf)
    ok  = wa_payload.encode(secret, "wa12_ok",     sess.id, "b%d" % ln["lid"], sq)
    chg = wa_payload.encode(secret, "wa12_change", sess.id, "b%d" % ln["lid"], sq)
    return self._wa6_send_buttons(raw_from, from_e164, body, [
        {"id": ok,  "title": _("✓ Correct")[:self._WA12_BTN_TITLE]},
        {"id": chg, "title": _("✗ Change")[:self._WA12_BTN_TITLE]}])
```

(2 buttons, not 3 — ⚠️ DECISION D-2BTN: the brief specifies `[✓ Correct][✗ Change]`; `skip` is reachable by typing `skip` or via ✗→list "None of these". Diverges from queue-walk D7's 3-button card to honour the ratified v2 wording exactly.)

### Ambiguous / family → LIST (fixes **BUG-2**, **BUG-3**, **BUG-4**)

`_wa12_send_pick` is **reused** but gets a backward-compatible signature extension. The live signature is `(self, sess, target, kind, cand_ids, label, family, from_e164, raw_from)`. Add `counter=None, seq=None` as **trailing kwargs** (byte-compat where unset — existing callers pass none):

```python
def _wa12_send_pick(self, sess, target, kind, cand_ids, label, family,
                    from_e164, raw_from, counter=None, seq=None,
                    drop_pid=None):                       # NEW kwargs
    ...
    if kind == "variant":
        body = _("*%s* → %s — which one?") % (label, self._wa12_family_word_for(
            label, family))                               # BUG-4: alias-aware
    else:
        body = _("\"%s\" — did you mean one of these?") % label
    if counter:
        body = "%s\n%s" % (counter, body)                 # BUG-2: counter prefix
    if drop_pid:                                          # BUG-11: drop rejected
        cand_ids = [p for p in cand_ids if p != drop_pid]
    def pick(pid):
        args = [sess.id, target, pid] + ([seq] if seq is not None else [])
        return wa_payload.encode(secret, "wa12_pick", *args)
    skip = wa_payload.encode(secret, "wa12_pick_skip", sess.id, target,
                             *([seq] if seq is not None else []))
    more = wa_payload.encode(secret, "wa12_pick_more", sess.id, target,
                             *([seq] if seq is not None else []))
    # row description: FULL name · $X/day (BUG-3)
    def row(p):
        prod = PT.browse(p); rate, cur = self._wa12_price_lookup(prod)
        desc = ("%s · %s %.2f/day" % (prod.name, cur, rate)
                if rate and rate > _WA12_PLACEHOLDER_RATE else prod.name)
        return {"id": pick(p), "title": prod.name[:self._WA12_LIST_TITLE],
                "description": desc[:72]}                  # Meta desc cap guard
    ...
```

**BUG-4 fix — alias-aware family word.** Add `_wa12_family_word_for(label, fam)`: prefer the matcher's term-alias expansion of `label` over the generic `_WA12_FAMILY_WORD[fam]`, so "blinders" frames as "molefays", not "lights":

```python
def _wa12_family_word_for(self, label, fam):
    kind, val, _exp = self._r2_alias_expand(label or "")
    if kind == "term" and val:
        # pluralise the alias term lightly for "blinders -> molefays. Which?"
        w = val.strip()
        return w if w.endswith("s") else (w + "s")
    return self._wa12_family_word(fam)
```

The stepper's pick presenter:

```python
def _wa12_present_pick(self, sess, buf, ln, from_e164, raw_from):
    cand_ids = ln.get("_cand_ids") or []
    sq = buf["seq"]
    if not cand_ids:                       # nothing to offer -> ask for a re-type
        self._wa12_set_pending(buf, ln["lid"],
                               "variant" if ln.get("_variant") else "ambiguous",
                               [], ln.get("raw") or "", ln.get("family") or "",
                               seq=sq)
        sess._set_buffer(buf)
        return self._wa6_reply(raw_from, from_e164, _(
            "%s  I couldn't place \"%s\" — type the item name, or 'skip'.")
            % (self._wa12_counter(buf, ln), ln.get("raw") or ""))
    kind = "variant" if ln.get("_variant") else "ambiguous"
    self._wa12_set_pending(buf, ln["lid"], kind, cand_ids, ln.get("raw") or "",
                           ln.get("family") or "",
                           overflow=len(cand_ids) > self._WA12_LIST_MAX, seq=sq)
    sess._set_buffer(buf)
    return self._wa12_send_pick(
        sess, "b%d" % ln["lid"], kind, cand_ids, ln.get("raw") or "",
        ln.get("family") or "", from_e164, raw_from,
        counter=self._wa12_counter(buf, ln), seq=sq)
```

`_wa12_set_pending` gains a trailing `seq=None` kwarg, stored on the pending dict.

`_wa12_send_pick` count-branching is unchanged: ≤2 → buttons (+ "None of these"); 3–10 → LIST + "None of these" row; >10 → top 9 + "Type to narrow" row. Titles `[:24]`, descriptions now `[:72]`. **Side-item rule** ("on totems" as its own step): already satisfied — `_wa12_match_text_items`/`_wa12_build_buf_lines` produce one `lines[]` entry per phrase, each its own cursor step.

### ✗ Change behaviour (fixes **BUG-8**, **BUG-11**)

`wa12_change` on a confident line re-derives candidates from the **bound product's own family**, **excludes the just-rejected product**, and re-presents N as a LIST. If the family yields nothing, fall to a "type the correct item name" text prompt (which lands in branch 7 on the next turn):

```python
# in _wa12_pick_apply_buffer, intent == 'wa12_change':
prod = self.env["product.template"].sudo().browse(ln.get("product_id"))
fam = prod.equipment_category_id.code or self._wa6_family_code(prod.name) or ""
cids = [p for p in (self._wa12_family_candidate_ids(fam)
                    or self._wa12_suggestion_ids([prod.name]))
        if p != prod.id]                          # BUG-11: drop the rejected one
ln.update({"kind": "unmatched", "raw": prod.name, "family": fam,
           "_variant": bool(fam), "state": "pending", "_cand_ids": cids})
ln.pop("product_id", None); ln.pop("product_name", None)
return self._wa12_present_pick(sess, buf, ln, from_e164, raw_from)
# (no advance; _wa12_present_pick handles the empty-cids -> type-prompt path)
```

---

## (4) INTENTS — `wa_payload.INTENTS` additions + payloads

Append two new intents (the confident card). The existing `wa12_pick / wa12_pick_more / wa12_pick_skip` are **reused** for the LIST path. All five carry a **trailing `seq`** for idempotency; `decode` returns all parts, so older 3-part payloads still decode and the handler reads a missing trailing seq as absent → stale-safe.

```python
# WA-12.4 — one-item stepper confident-line confirm/change (each = session id +
# 'b<lid>' target + seq; product is carried by the line, not the payload):
#   wa12_ok:<session_id>:b<lid>:<seq>      -- ✓ Correct  -> state='confirmed', advance
#   wa12_change:<session_id>:b<lid>:<seq>  -- ✗ Change    -> open the pick LIST for <lid>
# The LIST taps reuse wa12_pick/_more/_skip with a trailing :<seq>.
"wa12_ok", "wa12_change",
```

| Intent | Payload | Meaning |
|---|---|---|
| `wa12_ok` | `(sid, 'b<lid>', seq)` | confident → `state='confirmed'`, advance |
| `wa12_change` | `(sid, 'b<lid>', seq)` | open the family LIST for `<lid>` (rejected pid excluded) |
| `wa12_pick` | `(sid, 'b<lid>', pid, seq)` | bind → `state='picked'`, advance (**reused**) |
| `wa12_pick_more` | `(sid, 'b<lid>', seq)` | >10 overflow → narrow, scoped to `cur` (**reused**) |
| `wa12_pick_skip` | `(sid, 'b<lid>', seq)` | "None of these" → `state='skipped'`, advance (**reused**) |

**`_wa12_extract_tap` (fixes BUG-1/3/5 — the single ship-blocker root).** This is a **HARD line item**, not a table row. Extend the pick-sentinel tuple (line 327) so the two new intents return the `("pick", parts)` sentinel and reach `_wa12_handle_pick_tap` — otherwise they fall to the `startswith("wa12_")` block (330) which browses `parts[0]` (the **session id**) as a **quote id** and misroutes to `_wa12_handle_tap`:

```python
if decoded and decoded[0] in (
        "wa12_pick", "wa12_pick_more", "wa12_pick_skip",
        "wa12_ok", "wa12_change"):                       # NEW (BUG-1/3/5)
    return (decoded[0], ("pick", list(decoded[1])))
```

**`_wa12_handle_pick_tap` step gate (fixes BUG-2).** Add `"q_items"` is already in the gate (line 1229 `sess.step in ("q_items","q_confirm")`) — confirmed present, so q_items walk taps already pass the gate. (The queue-walk design needed a new `q_walk` step; the cursor model reuses `q_items`, so **no step-gate change is needed** — the new intents route to `_wa12_pick_apply_buffer` exactly like `wa12_pick` does today.) The seq/cursor revalidation lives in `_wa12_pick_apply_buffer` below.

No collision: `wa12_ok`/`wa12_change` are new distinct strings; WA-6/7/10/13 are namespaced. The `q_confirm` draft path (`_wa12_pick_apply_draft`) only ever sees `'l<line_id>'` targets + the old intents — **byte-unchanged**.

---

## (5) STEP ADVANCE + IDEMPOTENT TAPS + FINAL DRAFT

### `_wa12_pick_apply_buffer` rewrite (cursor-anchored, seq-idempotent)

Routes all five stepper intents. **Idempotency (queue-walk strength, BUG-6-class double-tap):** a tap is actionable only if its `lid == buf['cur']` AND its trailing `seq == pending['seq']`; otherwise it is a duplicate/stale delivery → re-present the current cursor (no re-apply, no double-advance). The single unique-phone session row + `_set_buffer` serialise the race.

```python
def _wa12_pick_apply_buffer(self, sess, intent, target, parts, from_e164, raw_from):
    buf = self._wa12_buf_migrate(sess._get_buffer())     # v4
    lid = int(target[1:]) if target.startswith("b") and target[1:].isdigit() else 0
    ln = self._wa12_line_by_lid(buf, lid)
    pend = buf.get("pending") or {}
    tap_seq = int(parts[-1]) if str(parts[-1]).isdigit() and len(parts) > (
        3 if intent == "wa12_pick" else 2) else None
    # IDEMPOTENCY + stale-anchor gate: only the live cursor's live offer acts.
    if ln is None or lid != buf.get("cur") or not buf.get("focus") \
            or (tap_seq is not None and pend.get("seq") not in (None, tap_seq)):
        return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)  # reshow

    if intent == "wa12_ok":
        ln["state"] = "confirmed"
        return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)
    if intent == "wa12_change":
        # re-derive family candidates from the bound product, drop the rejected
        # one (BUG-11), flip N back to a pending pick, re-present (NO advance).
        prod = self.env["product.template"].sudo().browse(ln.get("product_id"))
        fam = prod.equipment_category_id.code or self._wa6_family_code(prod.name) or ""
        cids = [p for p in (self._wa12_family_candidate_ids(fam)
                            or self._wa12_suggestion_ids([prod.name]))
                if p != prod.id]
        ln.update({"kind": "unmatched", "raw": prod.name, "family": fam,
                   "_variant": bool(fam), "state": "pending", "_cand_ids": cids})
        ln.pop("product_id", None); ln.pop("product_name", None)
        return self._wa12_present_pick(sess, buf, ln, from_e164, raw_from)
    if intent == "wa12_pick_more":
        return self._wa12_pick_narrow(sess, buf, lid, from_e164, raw_from)   # reused
    if intent == "wa12_pick_skip":
        ln["state"] = "skipped"
        return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)
    # wa12_pick — GUARD: re-validate pid against the OFFERED set (unchanged logic).
    pid = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 0
    offered = set(pend.get("candidates") or []) | set(ln.get("_cand_ids") or [])
    prod = self.env["product.template"].sudo().browse(pid)
    if not (pid and prod.exists() and pid in offered):
        return self._wa6_reply(raw_from, from_e164, _(
            "That option is no longer available — re-type the item."))
    ln.update({"kind": "matched", "product_id": pid, "product_name": prod.name,
               "rep_price": None, "stated_price": None, "state": "picked"})
    for k in ("raw", "suggestions", "family", "_variant", "_cand_ids"):
        ln.pop(k, None)
    return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)
```

### `_wa12_focus_retype` (fixes **BUG-1**/**BUG-9**: defined save-vars, qty from match)

```python
def _wa12_focus_retype(self, sess, buf, ln, raw, from_e164, raw_from):
    lid_saved = ln["lid"]; qty_saved = ln.get("qty") or 1
    hit = self._wa6_match_one(raw)
    if hit.get("status") == "matched" and hit.get("confidence") in (
            "exact", "strong"):
        ln.clear()
        ln.update({"lid": lid_saved, "kind": "matched",
                   "product_id": hit["product_id"],
                   "product_name": hit["product_name"],
                   "qty": hit.get("qty") or qty_saved,          # BUG-9
                   "rep_price": None, "stated_price": None, "state": "picked"})
        self._wa12_clear_pending_for(buf, lid_saved)
        return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)
    # weak/family -> re-frame N's candidates, STAY pending on N (never appends).
    fam = hit.get("family") or self._wa6_family_code(raw) or ""
    is_v = bool(fam and self._wa12_is_family_term(raw))
    cids = (self._wa12_family_candidate_ids(fam) if is_v
            else self._wa12_suggestion_ids(hit.get("suggestions") or []))
    for k in ("product_id", "product_name"):
        ln.pop(k, None)
    ln.update({"kind": "unmatched", "raw": raw, "qty": hit.get("qty") or qty_saved,
               "suggestions": hit.get("suggestions") or [], "family": fam,
               "_variant": is_v, "_cand_ids": cids, "state": "pending"})
    return self._wa12_present_pick(sess, buf, ln, from_e164, raw_from)
```

### `_wa12_focus_add_item` — the ONLY in-focus creator (appends at tail, cursor unchanged)

```python
def _wa12_focus_add_item(self, sess, buf, term, from_e164, raw_from):
    m, u = self._wa12_match_text_items(term)
    cur_ln = self._wa12_line_by_lid(buf, buf["cur"])
    if not m and not u:
        self._wa6_reply(raw_from, from_e164, _(
            "Couldn't read \"%s\" as an item. Finish item %s first, or type a "
            "catalogue name.") % (term, self._wa12_counter(buf, cur_ln)))
        return self._wa12_present_item(sess, buf, cur_ln, from_e164, raw_from)
    self._wa12_build_buf_lines(buf, m, u)        # appends; stamps state='pending'
    self._wa6_reply(raw_from, from_e164, _("Added \"%s\" — I'll get to it.") % term)
    return self._wa12_present_item(sess, buf, cur_ln, from_e164, raw_from)
```

`_wa12_add_line` and `_wa12_build_buf_lines` get `state='pending'` on every appended line.

### `_wa12_focus_price` (GUARD-preserving, mirrors 1498–1519)

```python
def _wa12_focus_price(self, sess, buf, ln, amt, from_e164, raw_from):
    prod = self.env["product.template"].sudo().browse(ln["product_id"])
    rate, cur = self._wa12_price_lookup(prod)
    if rate is not None and rate > _WA12_PLACEHOLDER_RATE:
        return self._wa6_reply(raw_from, from_e164, _(
            "%s has a catalogue rate (%s %.2f/day) — that's what drafts.")
            % (ln["product_name"], cur, rate))
    if amt <= _WA12_PLACEHOLDER_RATE:
        return self._wa6_reply(raw_from, from_e164, _(
            "That rate is too low — give the real day rate."))
    ln["rep_price"] = amt
    sess._set_buffer(buf)
    return self._wa12_present_item(sess, buf, ln, from_e164, raw_from)
```

### `_wa12_open_items_confirm` rewrite (replaces the combined block)

Keeps the F8 rep-price enrichment (2070–2076) and `_wa12_build_buf_lines`, then **sets the cursor and advances** instead of sending the combined text + one pick:

```python
# ... after buf = self._wa12_build_buf_lines(buf, matched, unmatched):
buf.update({"v": 4, "cur": None, "focus": False, "seq": 0})
for ln in buf["lines"]:
    ln.setdefault("state", "pending")
sess = self.env["neon.wa.equip.session"]._start_quote(
    from_e164, sender, "q_items", buf)
if not buf["lines"]:
    sess.sudo().write({"step": "done", "active": False})
    return self._wa6_reply(raw_from, from_e164, _(
        "I couldn't read any items — what should I quote?"))
self._wa6_reply(raw_from, from_e164, _(
    "Let's confirm %d item(s) for *%s*, one at a time.")
    % (len(buf["lines"]), buf.get("client_txt") or _("the client")))
return self._wa12_advance_cursor(sess, buf, from_e164, raw_from)   # presents ①
```

The deterministic-quote entry (`_wa12_run_quote`, call site ~394) calls `_wa12_open_items_confirm` with the **same positional signature** (`days` is not an arg; the buffer seeds `days:1` at 2084, and finalize defaults `buf.get("days") or 1`). **BUG-13** verified: no signature change; both entries (conversational 779, deterministic ~394) seed the buffer identically.

### `_wa12_finalize_to_draft` — the ONLY pre-draft all-lines render

Fires when no `pending` line remains. Clears focus/cursor defensively (BUG-4 belt-and-braces), projects matched+confirmed+picked (excludes `skipped`/`unmatched`/`pending`), then routes to the **unchanged** `_wa12_quote_from_slots` (which builds the draft, moves to `q_confirm`, and sends `_wa12_draft_summary` + `_wa12_inwindow_buttons` = `[Submit for approval][Edit a line]`):

```python
def _wa12_finalize_to_draft(self, sess, buf, from_e164, raw_from):
    buf["focus"] = False; buf["cur"] = None; buf["pending"] = None
    draftable = [{"product_id": ln["product_id"],
                  "product_name": ln["product_name"], "qty": ln.get("qty") or 1,
                  "rep_price": ln.get("rep_price"),
                  "stated_price": ln.get("stated_price")}
                 for ln in buf["lines"]
                 if ln.get("kind") == "matched"
                 and ln.get("state") in ("confirmed", "picked")]
    if not draftable:
        sess.sudo().write({"step": "done", "active": False})
        return self._wa6_reply(raw_from, from_e164, _(
            "Nothing left to quote — every item was skipped. Send new items "
            "or *cancel*."))
    partner = self.env["res.partner"].sudo().browse(
        buf.get("partner_id") or 0).exists()
    candidates = []
    if not partner:
        partner, candidates = self._wa12_client_candidates(buf.get("client_txt") or "")
    if not partner:
        return self._wa12_start_client_intake(
            sess.user_id, buf.get("client_txt") or "", candidates, draftable,
            buf.get("date_txt") or "", buf.get("days") or 1, from_e164, raw_from,
            prefills=buf.get("prefills") or {})
    return self._wa12_quote_from_slots(
        sess.user_id, partner, draftable, buf.get("date_txt") or "",
        buf.get("days") or 1, from_e164, raw_from, extras=buf.get("prefills") or {})
```

### C (line-number edit) + D (conversational) intact on the draft

Once `_wa12_quote_from_slots` moves the session to `q_confirm`, the focus fork is False (focus cleared, step != q_items), so `_wa12_handle_convo`'s **existing** post-draft grammar runs unchanged: C (`2 = <item>`, `remove 3`, `qty 1 to 4`, `price 2 250`, a date, `client <name>`) via `_wa12_q_items_try`/`_wa12_match_line`/`_wa12_try_edit`, and D (conversational) via `_wa12_llm_translate_items` + `_wa12_apply_multi` against real `quote.line` records. **Byte-compatible** — the stepper only replaces the *pre-draft* `q_items` confirm interaction.

⚠️ DECISION D-DEADTEXT: `_wa12_items_confirm_text` becomes dead **pre-draft** (the stepper never calls it). It is retained one cycle for any in-flight legacy v3→v4-folded `focus=False` session and is the renderer the post-draft show path uses — actually, post-draft uses `_wa12_draft_summary`, so `_wa12_items_confirm_text` is fully dead; keep it behind a ⚠️ marker, delete in WA-12.5.

---

## (6) GUARD PRESERVATION — proof no bad bind / no bad draft

The sacred guard: *every product bind ends in `_wa6_match_one` confidence ∈ {exact,strong} OR a tap re-validated against the offered set; no $0; no raw-string product; no cross-category; no skipped/unresolved line drafts.*

1. **`wa12_pick` tap** → `pid in (pending.candidates ∪ ln._cand_ids)` re-validation (identical to live 1265–1273). Candidates originate only from `_wa12_family_candidate_ids` (category-clean) or `_wa12_suggestion_ids` (matcher-surfaced) — never a raw string.
2. **`wa12_ok` confident confirm** → the line was created by `_wa12_match_text_items`/`_wa12_build_buf_lines` only at confidence exact/strong (2043–2047). ✓ flips `state`; no new bind.
3. **`wa12_change`** → re-derives `_cand_ids` from the bound product's own `equipment_category_id.code` (category-clean), excludes the rejected pid, re-enters the LIST (path 1). No raw bind.
4. **Focused re-type** (`_wa12_focus_retype`) → `_wa6_match_one`; confident → bind; **weak → stays pending on N in a LIST** (never a raw-string bind, never an advance, never a new line).
5. **Price** (`_wa12_focus_price`) → refuses when a catalogue rate exists; refuses `amt <= _WA12_PLACEHOLDER_RATE`. No $0.
6. **Draft projection** (`_wa12_finalize_to_draft`) → `kind=='matched' and state in ('confirmed','picked')` only. `skipped`, `unmatched`, and `pending` are excluded by construction, so no unresolved/skipped line can reach `_wa12_quote_from_slots`. Finalize only fires when **zero** `pending` lines remain, so a matched-but-unconfirmed line **blocks** finalize (can't slip through unconfirmed).
7. **Money is draft-only** at this stage; the approval / self-approve / PDF path is **UNCHANGED**. No money is sent over WhatsApp by the stepper.

---

## (7) METHOD MAP

### New
| Method | Signature | Role |
|---|---|---|
| `_wa12_first_unresolved` | `(self, buf) -> line\|None` | first `state=='pending'` line |
| `_wa12_advance_cursor` | `(self, sess, buf, from_e164, raw_from) -> reply` | move cursor + present, or finalize |
| `_wa12_present_item` | `(self, sess, buf, ln, from_e164, raw_from) -> reply` | bump seq; dispatch to confident/pick |
| `_wa12_present_confident` | `(self, sess, buf, ln, from_e164, raw_from) -> reply` | ✅ + `[✓ Correct][✗ Change]` |
| `_wa12_present_pick` | `(self, sess, buf, ln, from_e164, raw_from) -> reply` | LIST (delegates to `_wa12_send_pick`) |
| `_wa12_focus_dispatch` | `(self, sess, buf, raw, norm, from_e164, raw_from) -> reply` | focused decision tree |
| `_wa12_focus_add_item` | `(self, sess, buf, term, from_e164, raw_from) -> reply` | the ONLY in-focus line creator |
| `_wa12_focus_retype` | `(self, sess, buf, ln, raw, from_e164, raw_from) -> reply` | re-match N; weak → stay in pick |
| `_wa12_focus_price` | `(self, sess, buf, ln, amt, from_e164, raw_from) -> reply` | guarded rep-price on N |
| `_wa12_focus_help` | `(self, buf, ln) -> str` | one-line HELP for N (mode-tailored) |
| `_wa12_retype_confident` | `(self, raw) -> bool` | confident-or-family product test |
| `_wa12_is_question` | `(self, raw) -> bool` | `?`/wh-word/greeting/show meta test |
| `_wa12_counter` / `_wa12_pos` | `(self, buf, ln) -> str\|int` | "② of 4" / 1-based position |
| `_wa12_family_word_for` | `(self, label, fam) -> str` | alias-aware family word (BUG-4) |
| `_wa12_assert_focus` | `(self, buf)` | cur↔focus↔pending invariant guard |

### Changed
| Method | Change |
|---|---|
| `_wa12_buf_migrate` | v3→v4: stamp `state`, add `cur/focus/seq`, **preserve live `pending`** (BUG-12); v4 idempotent |
| `_wa12_add_line` / `_wa12_build_buf_lines` | default/stamp `state='pending'` |
| `_wa12_set_pending` | add trailing `seq=None`, store on the dict |
| `_wa12_open_items_confirm` | after building lines, seed v4 + `_wa12_advance_cursor` (present ①); drop the combined block + one pick |
| `_wa12_handle_convo` | insert the focus fork right after cancel, gated `step=='q_items' and focus and cur` (BUG-14/BUG-4); existing grammar runs only when unfocused |
| `_wa12_send_pick` | add `counter=None, seq=None, drop_pid=None` (BUG-2); counter prefix; rate-in-description (BUG-3); alias family word (BUG-4); seq in payloads |
| `_wa12_extract_tap` | add `wa12_ok`/`wa12_change` to the pick-sentinel set — **HARD line item** (BUG-1/3/5) |
| `_wa12_pick_apply_buffer` | switch on all five intents; seq+cursor idempotency gate; `state` + `_wa12_advance_cursor`; alias-aware `wa12_change` |
| `wa_payload.INTENTS` | add `wa12_ok`, `wa12_change` |

### Reused UNCHANGED (do not touch)
`_wa6_match_one`, `_wa6_match_items`, `_wa12_match_text_items`, `_wa12_family_candidate_ids`, `_wa12_suggestion_ids`, `_wa12_is_family_term`, `_r2_alias_expand`, `_wa6_family_code`, `_wa6_in_family`, `_wa12_price_lookup`, `_wa6_send_buttons`, `_wa6_send_list`, `_wa6_reply`, `_wa12_quote_from_slots`, `_wa12_draft_summary`, `_wa12_inwindow_buttons`, the whole `q_confirm` C/D path (`_wa12_q_items_try`, `_wa12_match_line`, `_wa12_try_edit`, `_wa12_after_edit`, `_wa12_apply_multi`, `_wa12_llm_translate_items`, `_wa12_batch_resolve_lids`), `_wa12_pick_apply_draft`, `_wa12_pick_narrow`, `_wa12_handle_pick_tap` session/entitlement re-check (step gate already admits `q_items`), the approval/self-approve/PDF path, `_wa12_line_by_lid`/`_wa12_line_by_number`/`_wa12_clear_pending_for`.

### Replaced for INITIAL resolution / retained for FINAL draft
- `_wa12_open_items_confirm` combined message + one-line pick → **replaced** by the stepper (cursor + advance).
- `_wa12_items_confirm_text` → **dead pre-draft** (⚠️ marker, delete WA-12.5); the FINAL draft uses `_wa12_draft_summary` (unchanged) and C/D edits run on it (unchanged).

---

## (8) TEST PLAN — REAL dispatch path (extend `.claude/pwa12_quote_smoke.py`)

Drive `_wa12_maybe_intercept` via `_txt(...)` / `_synth_tap(...)` (smoke 1784–1814); extend `_seed_qitems` to stamp `state`/`cur`/`focus`/`seq`. Never synthesise buffers as the sole proof.

- **T-WA12-70** stepper presents item ① only (one message, counter `①`, pending lid==line1.lid, `pending.seq==buf.seq`; lines 2+ NOT offered).
- **T-WA12-71** confident ✓: `_synth_tap(wa12_ok b<lid1> seq)` → line1 `confirmed`, cursor → line2, line2 presented.
- **T-WA12-72** confident ✗: `wa12_change b<lid1> seq` → line1 → family LIST **excluding the rejected product** (BUG-11); tap a sibling → `picked`, advance.
- **T-WA12-73 (the Robin "where do I tap" regression)** mid-pick `_txt("where do I tap")` → HELP + re-show N; assert **`len(buf['lines'])` UNCHANGED** (no phantom line), cursor still on N, `_wa12_q_items_try` NOT reached.
- **T-WA12-73b** mid-pick `_txt("which 4x100")` (a `?`-free narrow that starts with a Q-token via family) → reaches retype (BUG-7), NOT swallowed as a question.
- **T-WA12-74** mid-pick confident re-type (`4x100 molefay`) → binds N `picked`, advance; line count unchanged.
- **T-WA12-75** mid-pick weak re-type (`smoke machine`) → stays on N `pending`, new LIST; **no** new line.
- **T-WA12-76** `skip` on N → `state='skipped'`, advance; excluded from the final draft; line retained in buffer (D-SKIP).
- **T-WA12-76b** bare `ok` on a confident card → confirm-and-advance (BUG-6); bare `next` → confirm-and-advance, NOT a drop.
- **T-WA12-77** `add LED screen` mid-step → new `pending` line at tail, cursor stays on N; reached last in order.
- **T-WA12-78** all resolved → `_wa12_finalize_to_draft` provisions the draft (step → q_confirm), summary numbered, `[Submit][Edit]` present; skipped-only set → "nothing left to quote".
- **T-WA12-79 (C/D intact)** at the resulting q_confirm, `2 = <item>` and a conversational edit apply via the unchanged path.
- **T-WA12-80** stable-lid integrity across `add`/`skip` (port T-WA12-62): an old `wa12_pick` payload for lid L still resolves L after display numbers shift.
- **T-WA12-81** false-positive guard: `add` requires `^add\s+(.+)$`; bare `added`/`address` never creates a line.
- **T-WA12-82 (routing, not just round-trip)** `wa12_ok`/`wa12_change` through `_wa12_extract_tap` → assert they return the `("pick", parts)` sentinel and reach `_wa12_handle_pick_tap` (BUG-1/3/5 — proves the sentinel edit landed, which a bare encode/decode test would NOT).
- **T-WA12-83 (double-tap idempotency)** deliver the same `wa12_ok b<lid1> seq` twice → one advance; the second (stale seq / cursor moved) re-presents the current cursor, no double-advance, no re-bind.
- **T-WA12-84 (stale-card tap)** tap item ①'s old button after the cursor moved to ② → re-presents ②, no re-bind.
- **T-WA12-85 (family framing)** `2 blinders` → LIST body reads "*blinders* → molefays — which one?" (BUG-4), each row description = "FULL NAME · $X/day" (BUG-3).
- **T-WA12-86 (>10 overflow)** family with >10 candidates → 9 rows + "Type to narrow"; `wa12_pick_more` → narrow scoped to N (cursor unmoved).
- **T-WA12-87 (✗ Change, no family)** rejected product with no family/suggestions → "type the correct item name" prompt; next-turn confident retype binds (BUG-8).
- **T-WA12-88 (legacy bridge)** seed a v3 `q_items` session (no focus, a live `pending`) → folds to v4 preserving `pending` (BUG-12), behaves as the post-draft grammar, no crash.
- **T-WA12-89 (greeting mid-step)** `hi` while focused → re-shows the cursor item, NOT the legacy combined block (BUG-14).

**Regression:** full suite vs the baseline file (zero new failures). `pwa12` existing, `pwa6` Face-2 byte-unchanged, WA-6/7/10/13 tap decode (old 3-part payloads still decode; new trailing seq is additive).

**SAFE-DEPLOY holds:** no migration touching live rows (buffer migration is per-session lazy in `_wa12_buf_migrate`; sessions are TTL-ephemeral); no real-phone send; money still draft-only.

---

## (9) RISKS / OPEN

- **R1 — `_wa12_extract_tap` sentinel is the single ship-blocker.** If the implementer treats it as a table row rather than a hard edit, `wa12_ok`/`wa12_change` misroute to the approval handler and browse the session id as a quote id. T-WA12-82 asserts routing (not just encode/decode). **Mitigation:** build-order step 1 = the sentinel edit + T-WA12-82 green before any presenter work.
- **R2 — alias-word coverage.** `_wa12_family_word_for` assumes `_r2_alias_expand("blinders")` returns `kind=='term', val=='molefay'`. Verify against the live alias table during build; if "blinders" expands as a `category` rather than a `term`, fall back to `_wa12_family_word(fam)` (still "lights"). The fallback is non-breaking — only the exact ratified string ("molefays") is at stake. Confirm in GATE-0 of the build.
- **R3 — Meta description cap.** Rows now carry "FULL · $X/day"; truncate to 72 chars (`desc[:72]`) to stay under Meta's list-row description limit. Verify the cap empirically against `_wa6_send_list`.
- **R4 — `_r2_alias_expand` arity.** Confirmed `(kind, val, expanded)` 3-tuple at live line 1031. If any future matcher refactor changes it, `_wa12_family_word_for`/`_wa12_is_family_term` break together — both are guarded by R2's fallback.
- **R5 — confirm-words overlap.** `_WA12_CONFIRM_WORDS` includes `next`/`good`/`right`; ensure none collide with `_WA12_SUBMIT_WORDS` (`yes`/`submit`) or `_WA12_SKIP_WORDS`. `next` deliberately moved out of skip (BUG-6); a false-positive test (T-WA12-76b) covers it.
- **OPEN — counter denominator on `add`.** With the cursor model the counter is `pos of len(lines)`, so an `add` grows the denominator live ("② of 5" after adding). This is honest (queue-walk froze `total`; the cursor model does not). No bug; flagged so Robin sees the progress number can grow mid-walk.
- **OPEN — `skipped` lines visible in audit only.** D-SKIP keeps skipped lines in the buffer (not deleted). They never draft, but if a future "show the whole brief" recap is added it must filter `state!='skipped'`. Logged for WA-12.5.

**Files touched:**
- `c:\Users\Neon\neon-odoo\addons\neon_crew_comms\models\whatsapp_message_wa12.py` — all stepper methods + the `_wa12_handle_convo` fork + `_wa12_buf_migrate`/`_wa12_send_pick`/`_wa12_extract_tap`/`_wa12_pick_apply_buffer`/`_wa12_open_items_confirm` edits; manifest bump `neon_crew_comms` minor (new interaction layer).
- `c:\Users\Neon\neon-odoo\addons\neon_channels\models\wa_payload.py` — add `wa12_ok`, `wa12_change` to `INTENTS`; manifest bump `neon_channels` (registry-only — must read true) + ONE force-recreate so the webhook worker reloads INTENTS.
- `c:\Users\Neon\neon-odoo\.claude\pwa12_quote_smoke.py` — T-WA12-70…89.
- `c:\Users\Neon\neon-odoo\docs\phase-11\WA12_4_stepper_spec.md` — this locked spec (supersedes `WA12_3_interaction_redesign_spec.md`).

**Live line anchors:** dispatch hub `_wa12_handle_convo` 710–907 (fork after 727, above 734); the bug branch `_wa12_q_items_try` re-type 1526–1550; presenters `_wa12_open_items_confirm` 2061, `_wa12_items_confirm_text` 2103, `_wa12_send_pick` 1130 (positional `target`, no `counter`); tap routing `_wa12_extract_tap` 305–348 (sentinel 327), `_wa12_handle_pick_tap` 1217 (step gate 1229 admits `q_items`), `_wa12_pick_apply_buffer` 1245; family word `_WA12_FAMILY_WORD`/`_wa12_family_word` 1090–1097; price guard 1498–1519; buffer `_wa12_buf_migrate` 952 (v3-terminal), `_wa12_add_line` 987, `_wa12_set_pending` 1010; `INTENTS` `wa_payload.py` 34–130 (add after 117).