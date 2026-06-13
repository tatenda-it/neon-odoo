# Resolver v2 — LOCKED BUILD SPEC (design workflow wf_ff050027-348, 2026-06-13)

Source-verified synthesis of 3 independent designs + 3 adversarial critiques.
Robin's 6 OPEN rulings (folded below) captured 2026-06-13.

`workshop_name` on `product_template` (line 52) is a plain `fields.Char` — stored, real column. The raw-SQL trgm read is safe (the `neon_equipment_unit` one at line 108 is the related/non-stored one, irrelevant here).

I have confirmed every contested fact. The decisive findings:

1. **`_wa12_run_price:2044` accepts ANY `status=="matched"`** — does NOT gate on confidence. This is the BUG-4 (determinism-first critique) money-path leak. Real and HIGH. Resolver v2 must not let new `weak`/LLM-pick hits leak into the price read-out as priced lines (already partly mitigated — line 2055 suppresses placeholder rates — but a real-rate `weak` would price).
2. **`_wa6_parse_qty`** has NO bare-leading-count rule ("4 blinders" → qty 1). The "4 is qty" claim across proposals is false against live source.
3. **`_wa12_parse_dims`/`_wa6_parse_dims`** matches `4x100` (m optional) → both qty-mask AND `_wa6_parse_dims` read it. "4x100W INDOOR MOLEFAYS" parses to pseudo-dims (4,100), so dimensional-exact lands it.
4. **`_wa6_family_code` returns FIRST family in dict order**; `_WA6_CAT_SYNONYMS` lists `trussing` before `lighting`. "4 blinders on totems" → trussing first. Multi-family blind spot is real.
5. **`_wa12_llm_chat` is NOT `@api.model`** (line 1080) — plain method; callable from an `@api.model` method on the same model fine.
6. **The casing dup**: `len(exactd) > 1` → `weak` today. Real false-weak.
7. **`_wa6_family_code` is reused by `_wa12_discovery_family`** — must not change its signature/behaviour.

I now lock the design.

---

# RESOLVER v2 — LOCKED BUILD SPEC

Target: `addons/neon_crew_comms/models/whatsapp_message_wa6.py` — rewrite `_wa6_match_one` (889–1007) + add helpers. Synthesis: **minimal-diff's surgical mapping** (smallest blast radius, every exit through the existing `hit()` closure) as the skeleton; **determinism-first's confirmed-alias gate discipline + grounded-shortlist firewall**; **recall-first's spec/plural normalisation and casing-dup canonicaliser**. Every HIGH/MED bug from the four critiques is fixed below.

## 1. FUNNEL ORDER (definitive)

`fam` is initialised `""` at the very top (fixes BUG-5/B1 unbound-`fam`). The `hit()` closure is defined before any return. Stage S3 (family derivation) runs **before** S4 (dimensional), so the dimensional-exact golden cases fire (fixes BUG-1).

| # | Stage | Input | Rule | Output / Confidence | Fall-through |
|---|---|---|---|---|---|
| **S0** | Parse | `raw` | `qty,desc = _wa6_parse_qty(raw)` (dims masked → "3 x 2"/"4x100" never qty). **NEW**: bare-leading-count guard (§5). | `(qty, desc)` | always |
| **S1** | Normalise | `desc` | `want = _r2_norm(desc)`; `tokens` = `[a-z0-9.]+` minus `_WA6_STOP` (un-folded). `_r2_norm` adds spec-join + safe plural fold (§5). | `want`, `tokens` | always |
| **S2** | **Alias-expand (CONFIRMED only)** | `desc` | Single read via `_r2_alias_map()` (`state='confirmed'`). Whole-word, plural-tolerant (`s?`), longest-phrase-first. **product** → terminal hit; **category** → `forced_fam`; **term** → rewrite `desc`, recompute `want`/`tokens`, continue. **product short-circuit gated to whole-desc-dominant** (§ below, fixes B2). | product → `exact`; category/term → continue | no confirmed hit → continue |
| **S3** | Family derive | `desc`, `category_hint`, `forced_fam` | `fam = forced_fam or _wa6_norm_family(category_hint) or _wa6_family_code(desc) or ""`. | `fam` set | always |
| **S4** | **Dimensional** (only if `fam` AND dims) | `dims`, `cands=fam` | exact stocked size, after casing-dup canonicalise (§4): unique → `exact`; genuinely-distinct same-size → `exact` on rep + suggestions; no stocked size → nearest-by-area `weak`. | `exact` / `weak` | no dims, or fam empty → S5 |
| **S5** | Exact name | `want`, `cands` (or all if no fam) | `_r2_norm(p.name)==want or _r2_norm(p.workshop_name)==want`, canonicalised; unique-after-fold → `exact`. | `exact` | 0 hits → S6 |
| **S6** | **pg_trgm category-scoped rank** | `want`, `cands.ids` | `_r2_trgm_rank` (§2). top ≥ HI & margin ≥ MARGIN → `strong`; top ≥ FLOOR (thin/tied) → hand to S7; top < FLOOR → S7 with what little exists. Family-scoped → cross-category impossible. | `strong` | → S7 |
| **S7** | **Grounded shortlist (LLM constrained pick)** | `desc`, `fam`, S6 top-K real names | LLM returns an **index** (§3); validated in-range AND in-family. valid pick → `weak`; else → S8. **Gated on `fam` truthy** (fixes B3 — no no-family LLM lane). | `weak` (pick) | no-pick / invalid / LLM down → S8 |
| **S8** | Discovery / custom | — | family-known, nothing scored → `none` + closest-in-family suggestions. **No family** → conservative all-items token scorer (baseline 990–1007 verbatim), lone winner capped at `weak`; nothing → `none`. **Never invents, never LLM here.** | `weak`+suggestions or `none` | terminal |

### Where confirmed-alias expansion sits + alias-vs-synonym precedence

S2, **after parse/normalise, before family derivation (S3)** — so a `term` rewrite feeds the synonym layer, and a `category`/`product` alias pre-empts it.

**Precedence, highest → lowest: confirmed product alias > confirmed category alias (`forced_fam`) > LLM `category_hint` > synonym-derived family. Term aliases rewrite the input ahead of all of these.**

**Reasoning — alias WINS over synonym:** a CONFIRMED alias is Robin's explicit, UI-reviewed ruling; `_WA6_CAT_SYNONYMS` is a static code heuristic. When they conflict (e.g. a slang the synonyms scope wrong), Robin's confirmation must override. Concretely `forced_fam` from a category alias is consulted **before** `_wa6_family_code` in the S3 expression. `proposed`/`open` rows are structurally invisible (single read site, hard `state='confirmed'` domain).

## 2. pg_trgm (Stage S6)

`pg_trgm` v1.6 is live; `similarity()` native. `workshop_name` is a stored `fields.Char` on `product_template` (verified line 52) — raw SQL is safe. Wrap in try/except → degrade to `[]` on any SQL surprise (fixes BUG-6, never 500s mid-quote).

```sql
SELECT pt.id,
       GREATEST(
         similarity(lower(coalesce(pt.name,'')),         %(q)s),
         similarity(lower(coalesce(pt.workshop_name,'')), %(q)s)
       ) AS sim
FROM   product_template pt
WHERE  pt.id = ANY(%(ids)s)
ORDER  BY sim DESC, pt.id ASC          -- deterministic tie-break (fixes BUG-6)
LIMIT  %(k)s;
```

- `%(q)s` = the **normalised `want`** (same `_r2_norm` the funnel uses — NOT the raw desc; fixes BUG-6 token-dilution), `%(ids)s` = `cands.ids` (always family-scoped at S6), `%(k)s` = `_WA6_SHORTLIST_K`.
- No JOIN on category needed — scoping is by passing the already-family-filtered `cands.ids`. **Cross-category structurally impossible** at S6.
- Optional GiST index (one-shot migration, not required for correctness on ≤545 rows / <60 per family):
  `CREATE INDEX IF NOT EXISTS product_template_name_trgm ON product_template USING gist (lower(name) gist_trgm_ops);`

**Thresholds (module constants — tuned against the golden corpus at build, recorded as a DECISION):**
```python
_WA6_TRGM_STRONG = 0.55   # top sim ≥ this AND margin ≥ MARGIN → 'strong' (auto-accept)
_WA6_TRGM_MARGIN = 0.12   # winner must beat #2 by this
_WA6_TRGM_FLOOR  = 0.30   # below → no deterministic winner; hand to S7
_WA6_SHORTLIST_K = 6
```
Map: `sim_top ≥ STRONG and (sim_top − sim_2) ≥ MARGIN and fam` → **strong**; `sim_top ≥ FLOOR` → S7 (shortlist); else → S7 with whatever ranked (may be empty → S8).

## 3. GROUNDED SHORTLIST (Stage S7) — the firewall

**Only reached when `fam` is known** (B3 fix). **Sent to LLM:** the S6 top-K **real `product.template` names within `fam`** + the user's phrase. Never the catalogue, never free text.

**Prompt shape** (reuses `_wa12_llm_chat` temp-0 + `_wa12_llm_json`, both on `neon.whatsapp.message`):
```
SYSTEM: You match a sales rep's equipment phrase to ONE item from a FIXED numbered
        list of real products this company stocks, or none. Reply with ONLY JSON:
        {"index": <integer 0..K-1 or null>, "confident": <true|false>}.
        index MUST be one of the shown numbers. Do NOT invent a product, do NOT
        return a name. If none of the listed options is what the phrase means,
        return {"index": null}. Every listed product is in the '<fam>' family —
        never pick across families.
USER:   Phrase: "<desc>"
        Options:
          0. 3M X 2M LED SCREEN
          1. 6M X 2M LED SCREEN
          ... (K real names)
```

**Validation back to a REAL product_id (the wall):**
```python
data = self._wa12_llm_json(self._wa12_llm_chat(messages)) or {}
idx = data.get("index")
if not isinstance(idx, int) or not (0 <= idx < len(shortlist_ids)):
    return None                              # null / out-of-range / non-int / degraded → S8
pid = shortlist_ids[idx]                     # index → an id WE put in the list
p = self.env["product.template"].sudo().browse(pid)
if not p.exists() or not self._wa6_in_family(p, fam):   # defence in depth
    return None
return {"product_id": pid, "product_name": p.name, "confident": bool(data.get("confident"))}
```

**Confidence:** valid pick → **`weak`** always (human-confirmed by the WA-12 gate). Never `strong`/`exact` from an LLM. (`confident=true` only matters for the price-path filter, §6.) No-pick/invalid/outage → S8.

**Guarantees:** (1) **CONFIRMED-only** — S7 never reads aliases; alias gate is solely `_r2_alias_map`. (2) **Never cross-category** — shortlist built from `cands` (one family) + re-validated `_wa6_in_family`. (3) **Never invents** — returns an index into a matcher-built id list; any non-index reply discarded.

## 4. DIMENSIONAL (Stage S4) — exact vs nearest, casing-dup is NOT a false weak

Reuses `_wa6_parse_dims` (verified: normalises case/"x"/spacing/"m", so `"6m x 2m"` ≡ the `"6M X 2M LED SCREEN"` token). Runs only when `fam` known AND dims present.

- **EXACT** = requested `(w,h)` equals a stocked product's parsed `(w,h)`. After collapsing pure casing/space dups (below): unique → **`exact`**, empty suggestions. Golden `"3 x 2 screen"`→`3M X 2M LED SCREEN`, `"6m x 2m screen"`→`6M X 2M LED SCREEN`. Never downgraded to fuzzy/nearest.
- **Casing-dup fix (BUG-3 / B4):** before counting, collapse `exactd` by `_r2_norm(name)`. If all dups fold to one normalised string (the documented `"10m x 2m LED SCREEN"` / `"10M X 2M LED SCREEN"`), they are the SAME logical product → `_r2_pick_canonical` returns the deterministic representative (most-uppercase spelling, tie → lowest id) at **`exact`, empty suggestions**. The lower-case dup goes to the polish backlog for data cleanup (append-only, never auto-deleted). A pure casing difference NO LONGER returns `weak`.
- **Genuinely-distinct same-size** (two different real products at one size — rare) → `exact` on the representative **plus** `suggestions` populated so a consumer can offer the alternative; not downgraded to `weak` (a ⚠️ DECISION, logged).
- **NEAREST-as-exception** = only when NO stocked size matches → nearest-by-area, **`weak`**, top-3 sized suggestions → confirm / custom-price path.

## 5. QTY / SPEC PARSE — disambiguation

`_wa6_parse_qty` masks `digit [m] [x×] digit [m]` before the qty scan. Verified behaviour + the one NEW guard:

| Input | qty | desc kept | Mechanism |
|---|---|---|---|
| `"3 x 2 screen"` | 1 | `3 x 2 screen` | `3 x 2` matches the dim mask → masked out → not qty. Then `_wa6_parse_dims`→(3,2) at S4. **DIM, not qty.** ✓ already correct |
| `"4x100 molefay"` | 1 | `4x100 molefay` | `4x100` matches the dim mask (m optional) → masked → not qty. **SPEC, not qty.** Resolves via S4 (product `"4x100W INDOOR MOLEFAYS"` parses to pseudo-dims (4,100) → exact) or S6 trgm. ✓ already correct — the "4x100 would read as qty 4" claim in proposals is FALSE against live source. |
| `"4 blinders"` | **4** | `blinders` | **NEW guard** in `_wa6_parse_qty`: after the mask, a bare leading `^\s*(\d+)\s+(?=\D)` where the next char is non-digit AND not immediately an `x` → qty. So `"4 blinders"`→qty 4, but `"4x100"`/`"3 x 2"` are already mask-protected and skip it. |

**Bare-leading-count guard (exact rule, fixes BUG-2 qty leg):** add as a final qty branch, evaluated on the **masked** string so dims/specs are already blanked:
```python
if not m:
    m = re.search(r"(?:^)\s*(\d+)\s+(?=[a-z])", masked)   # "4 blinders" → 4
```
A leading integer followed by whitespace then a letter = quantity. `"4x100"`→masked→no leading-int-then-letter. `"3 x 2 screen"`→masked→`" 2 screen"` has no *leading* int (the "3" was masked). Safe.

### Cases that genuinely need Robin's confirm (flag, do not self-resolve)

- **`"4 blinders on totems"` — multi-item, OUT OF SCOPE for a single-item resolver.** `_wa6_match_items` splits only on `[,\n;]+|\s+and\s+` (verified) — `" on "` is NOT a separator, so this is ONE item and the second product is dropped. ⚠️ **DECISION (locked): `_wa6_match_one` resolves ONE item; multi-item phrasing is the caller's job.** We do NOT add `" on "` to the splitter (too ambiguous — "monitor on stage" is one item). Behaviour: with the qty guard, `"4 blinders on totems"`→qty 4, then resolves the dominant item to a `weak`/`strong` single product; the rep confirms in the WA-12 echo. Robin's confirm needed on whether the trainer guidance is "type compound gear comma-separated" (recommended) — surfaced, not coded around.
- **`"4x100" as spec vs qty** — defensibly a SPEC (the wattage on the fixture; qty-4-of-unspecified would be wrong). If Robin wants `4x100`=qty, it's a one-line mask change — flagged.

## 6. BYTE-COMPAT

Return dict — **unchanged keys and value-domains**, every exit through the existing `hit()` closure:
```python
{"raw": raw, "qty": qty, "product_id": pid_or_False, "product_name": name_or_"",
 "category": "", "status": "matched"|"not_found",
 "confidence": "exact"|"strong"|"weak"|"none", "suggestions": [names], "family": fam}
```
- `confidence` vocabulary **frozen at the 4 existing values** — both consumer gates stay byte-compatible. New stages emit only these: product-alias→`exact`; dim-exact/canonical→`exact`; exact-name→`exact`; trgm clear→`strong`; trgm-thin/LLM-pick/nearest/dup-distinct→`weak`; discovery→`weak`/`none`.
- `_wa6_match_one(raw, category_hint=None)` and `_wa6_match_items(text)` signatures **unchanged** → WA-8, WA-12 slot/text paths bind identically.
- `_wa6_family_code` / `_wa6_in_family` / `_wa6_norm_family` signatures unchanged (reused by `_wa12_discovery_family`, `_wa12_family_names`).
- Gates verified: `_wa12_match_slot_items:1328` and `_wa12_match_text_items:1386` accept only `matched` + `confidence in ("exact","strong")` → unchanged. WA-8 head-noun layers on `matched`+`product_name` → unchanged.

**⛔ HARD-GATE / money-path finding (BUG-4 / B-money, MUST go to Robin/Tatenda before build):** `_wa12_run_price:2044` filters on `status=="matched"` ONLY — it does NOT read `confidence`. Today its inputs are token-overlap weak hits; Resolver v2 adds **LLM grounded-picks and trgm-weak** to the `matched`+`weak` set, so the **Price:** read-out would quote a real rate for an LLM-picked/low-confidence product. Line 2055 already suppresses placeholder rates but a real-rate `weak` would price. **Per CLAUDE.md hard-gate #3 (money over WhatsApp), this is walled off and surfaced, not auto-decided.** Recommended fix (one line, for Robin's approval): tighten 2044 to `it.get("status")=="matched" and it.get("confidence") in ("exact","strong")` so Price: matches the quote gate. This is the ONE consumer edit outside `whatsapp_message_wa6.py` and it is gated.

## 7. SCOPE

Matcher searches **`product.template` WHERE `is_workshop_item = True`** — unchanged from baseline (`allp` at 908). Ground truth: 545 of 547 active templates are `is_workshop_item=True` (near-complete hireable scope); the 2 non-workshop + 2 no-category are the deposits flagged for removal — correctly excluded. The KEYSTONE guarantees `equipment_category_id` is reliably populated, so family-scoping via `_wa6_in_family` (which checks `equipment_category_id.code` first, name-synonym fallback second) is now category-accurate, not heuristic. No scope change needed; the data fix carries it.

## 8. METHOD MAP (on `neon.whatsapp.message`)

**New (`@api.model`, all in `whatsapp_message_wa6.py` beside `_wa6_match_one`):**
- `_r2_norm(self, s) -> str` — recall normalise: casefold; `×`/NBSP→`x`/space; spec-join bare `(\d+)x(\d+)`→one token; safe plural fold (alpha, len>3, trailing `s`, **NOT** `ss` — keeps "truss", fixes BUG-7) with a `_R2_PLURAL_KEEP` set wired in; drop `_WA6_STOP`.
- `_r2_alias_map(self) -> dict` — `ormcache`'d; `{phrase: ('product',id)|('category',code)|('term',text)}`, `state='confirmed'` ONLY. **CONFIRMED-ONLY GATE #1.**
- `_r2_alias_expand(self, desc) -> (kind, value, new_desc)` — whole-word **plural-tolerant** (`(?<!\w)phrase s?(?!\w)`, fixes BUG-2/B2-plural), longest-first; product short-circuit gated to whole-desc-dominant (alias phrase covers desc minus stopwords).
- `_r2_pick_canonical(self, prods) -> product.template` — collapse pure casing/space dups → representative; distinct → first + flag (§4).
- `_r2_trgm_rank(self, query_norm, cand_ids, k=_WA6_SHORTLIST_K) -> [(id, sim)]` — §2 SQL, try/except→`[]`.
- `_r2_grounded_pick(self, desc, fam, ranked) -> {product_id, product_name, confident}|None` — §3.

**Changed:**
- `_wa6_match_one` — rewritten to the S0–S8 funnel; **`fam=""` initialised at top** (fixes B1/BUG-5); `hit()` defined before any return; calls the new helpers. The dimensional block (938–962) reused with the casing-dup canonicaliser inserted; the within-family token scorer (963–982) **REPLACED** by S6 trgm + S7 shortlist; the no-family branch (987–1007) **kept verbatim** as S8 discovery (lone winner already capped at `weak`/`strong` by `wscore3` — leave as-is, no no-family LLM).

**On `neon.equipment.alias` (`neon_equipment_alias.py`):** add `create`/`write`/`unlink`/`action_confirm`/`action_mark_open` overrides calling **`self.env.registry.clear_cache()`** (cross-worker; NOT the per-method `clear_cache`, fixes BUG-5/B5) so a freshly-confirmed alias is live without restart.

**Reused unchanged:** `_wa6_parse_qty` (+ the one new bare-leading-count branch, §5), `_wa6_parse_dims`, `_wa6_family_code`, `_wa6_norm_family`, `_wa6_in_family`, `_wa6_category_for`, `_WA6_CAT_SYNONYMS`, `_WA6_STOP`, `_wa12_llm_chat`, `_wa12_llm_json`. **Consumers `_wa12_match_slot_items`, `_wa12_match_text_items`, WA-8 — NO change.** `_wa12_run_price` — one gated line, §6.

## 9. GOLDEN TEST SET

`hit = _wa6_match_one(input)` asserting `(status, confidence, resolved name, qty)`. Build via the REAL dispatch path where a consumer is involved.

### (a) Buildable NOW — dimensional/exact/trgm + the 9 already-PROPOSED→confirmable rows, NO dependency on Robin's 6 OPEN answers

| Input | → product | qty | conf | Rule |
|---|---|---|---|---|
| `3 x 2 screen` | 3M X 2M LED SCREEN | 1 | exact | S3 visual + S4 dim-exact |
| `6m x 2m screen` | 6M X 2M LED SCREEN | 1 | exact | S4 dim-exact |
| `5m x 3m LED screen` | 5M X 3M LED SCREEN | 1 | exact | S4 dim-exact (regression) |
| `10m x 2m LED SCREEN` (casing dup) | canonical UPPER row | 1 | **exact** (NOT weak) | S4 casing-dup canonicalise (BUG-3 fix) |
| `screen` (bare) | a Visual product / shortlist | 1 | weak/strong | S3→S6 visual; **never a 360 BOOTH** (proof-#3 guard) |
| `4x100 molefay` | 4x100W INDOOR MOLEFAYS | 1 | exact/strong | spec masked, S4/S6 lighting |
| `4 blinders` | a lighting product (blinder∈lighting synonym) | **4** | weak | bare-leading-count guard → qty 4 (BUG-2 qty fix) |
| `RGBWAUV zoom can` | an LED zoom can (lighting) | 1 | strong/weak | S3 lighting (rgbwauv/zoom/can syn) + S6 |
| `stage` | a STAGE/decking product | 1 | weak/strong | S3 staging + S6 |
| `disco ball mirror thing` | (none) | 1 | none | no fam → S8 discovery, **never invents, never LLM** (B3 fix) |
| exact catalogue name e.g. `LOW FOGGER` | LOW FOGGER | 1 | exact | S5 exact-name |
| OPEN alias row present, its phrase typed | resolves by funnel **ignoring** the open alias | — | — | `_r2_alias_map` excludes non-confirmed (GATE #1) |
| LLM-down (monkeypatch `_wa12_llm_chat→None`) on a thin in-family phrase | falls to S8, `weak`/`none` | — | — | grounded-pick degrades, **never invents** |
| grounded-pick returns out-of-range/out-of-family index | rejected → S8 | — | — | §3 validation wall |
| `truss` (plural-fold safety) | a TRUSS product | 1 | strong/weak | `_r2_norm` must keep "truss" (NOT "trus") — BUG-7 |
| byte-compat: any matched hit | — | — | — | assert keys == {raw,qty,product_id,product_name,category,status,confidence,suggestions,family}; `category==""` |

### (b) BLOCKED on Robin confirming an OPEN alias row (cannot assert the resolved product until the row is `confirmed`)

| Input | → expected (once confirmed) | conf | OPEN row Robin must confirm |
|---|---|---|---|
| `totem` / `totems` | the chosen TRUSS TOTEM (2M PIN / 2M / 3M) | exact | **totem default size** → a `product_template_id` alias |
| `blinder` (singular, by name returns 0 today) | a MOLEFAY | weak | **blinder=molefay?** → `term` alias `blinder→molefay` (or `category`→lighting) |
| `wedge` | a floor monitor | weak/strong | **wedge=floor monitor?** → `term` or `product` alias |
| `smoke` / `smoke machine` | VERTICAL SMOKE MACHINE | weak/strong | **smoke=vert machine?** → `term`/`product` alias |
| `cans` | an LED CAN | strong | **cans=led can?** → `term` alias `cans→led can` (test with a confirmed fixture row) |
| `pa` (bare) | the default PA | weak/strong | **pa default?** → `product` alias |

Plus regression: `pwa6` (58), `pwa12`, `pwa8` unchanged (byte-compat proof). New tests are **additive**.

## 10. RISKS / OPEN

1. **⛔ MONEY HARD-GATE (`_wa12_run_price:2044`)** — must surface to Robin/Tatenda before build; the one-line confidence gate fix (§6) waits on approval. This is the only consumer edit and it is money-adjacent.
2. **trgm thresholds (0.55/0.12/0.30, K=6)** — starting values; lock against the golden corpus at build, record as a DECISION. Constants → tuning is non-structural.
3. **Multi-item compound input (`"4 blinders on totems"`)** — locked as single-item-resolver scope; the second product is the caller's/typist's responsibility. Robin's call on trainer guidance ("comma-separate compound gear"). Not coded around — flagged.
4. **`4x100` = spec not qty** — defensible default; Robin can override to qty with a one-line mask change.
5. **6 OPEN alias rows** — the (b) test cases and the slang they cover are inert until Robin confirms each in the UI; the matcher correctly degrades to discovery/synonym meanwhile (never a wrong silent answer).
6. **`ormcache` cross-worker invalidation** — `registry.clear_cache()` chosen (cross-worker signal) over the per-method `clear_cache` (per-process, would leave a confirm dead on other workers); a test confirms an alias then asserts the next match honours it.
7. **Spaced bare `N x N` with implausible operand (`"4 x 100 molefay"`)** — `_wa6_parse_dims` would read (4,100). Mitigated because the matching product `"4x100W INDOOR MOLEFAYS"` parses to the same (4,100) → still lands correctly; if a director types a spaced spec with no matching product, S4 nearest-by-area `weak` is the safe (confirm-gated) outcome. Flagged; not blocking.

**Files of record:** matcher + helpers + synonyms + parsers `C:\Users\Neon\neon-odoo\addons\neon_crew_comms\models\whatsapp_message_wa6.py`; alias model + cache-invalidation override `C:\Users\Neon\neon-odoo\addons\neon_crew_comms\models\neon_equipment_alias.py`; LLM rails reused `_wa12_llm_chat`/`_wa12_llm_json` and the gated money-path edit `_wa12_run_price:2044` in `C:\Users\Neon\neon-odoo\addons\neon_crew_comms\models\whatsapp_message_wa12.py`; `workshop_name` stored Char confirmed in `C:\Users\Neon\neon-odoo\addons\neon_jobs\models\product_template_extension.py:52`.
---

# ROBIN'S 6 OPEN RULINGS (2026-06-13, binding — supersedes the (b) "blocked" placeholders above)

These resolve the OPEN alias rows. Apply as alias-row confirmations + golden-set truth:

1. **blinder = molefay** — confirm `blinder`/`blinders` as a **term→"molefay"** (family expand, NOT a single
   product) because the exact variant is FLAGGED for Robin to pick in the UI. '4 blinders' = qty 4 (the new
   bare-leading-count guard, §5), 'on totems' = a separate TRUSS TOTEM line (single-item-resolver scope, §5).
2. **wedge = POWERWORKS MONITOR (floor, id 682)** — confirm `wedge`→product POWERWORKS MONITOR.
   **monitor = ASK** — bare 'monitor' stays OPEN; the funnel must SHORTLIST the 4 monitors, never auto-pick.
3. **smoke = VERTICAL SMOKE MACHINES (id 401)** — confirm. **cans/pars/parcans = LED CAN family** — confirm
   as term→'led can'.
4. **NO bare defaults** — bare `totem` and bare `pa`/`sound system` must NEVER auto-pick; the funnel SHORTLISTS
   the size/PAX options for the rep to choose. So `totem(s)`→category hint **trussing** (not a single product);
   `pa`/`sound system`→term 'pa system' but resolve via SHORTLIST (never a lone auto-pick).

## Resulting alias-row dispositions (the gated confirm write)
- CONFIRM (proposed→confirmed): screen, led screen, video wall (→Visual); stage, staging (→Staging);
  truss, trussing (→Trussing); fogger, fog machine (→LOW FOGGER).
- RE-TARGET + CONFIRM: cans/pars/parcans → term 'led can'; smoke → product VERTICAL SMOKE MACHINES;
  wedge → product POWERWORKS MONITOR; blinder/blinders → term 'molefay'.
- LEAVE OPEN (shortlist-only, never auto-pick): totem, totems (→ category trussing hint), pa, sound system
  (→ term 'pa system' but shortlist), monitor (→ shortlist the 4).

## Money hard-gate (BLOCKS the build until Robin/Tatenda approve)
`_wa12_run_price` line 2044 (verified) prices any status=='matched' item; line 2055 only suppresses
PLACEHOLDER rates. Resolver v2 adds LLM-grounded + trgm-weak to the matched set → a weak hit on a
REAL-rate product would quote a price over WhatsApp. Recommended one-line fix:
`matched = [it for it in items if it.get("status")=="matched" and it.get("confidence") in ("exact","strong")]`
This is the ONLY consumer edit outside whatsapp_message_wa6.py and it is money-adjacent → HARD GATE #3.
