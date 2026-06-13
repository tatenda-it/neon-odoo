# -*- coding: utf-8 -*-
"""Resolver v2 SUPPORT (a) — seed the team-slang alias store as PROPOSED rows.

Robin's directive (13 Jun): seed the alias table FIRST so team slang is real,
reviewable data the golden tests lock against — not a guess baked into the
regression. EVERY row is PROPOSED (or OPEN where Robin must decide); NOTHING is
auto-confirmed. Robin confirms each in the Slang Aliases list; only CONFIRMED
rows are applied by the matcher.

Three target kinds (exactly one per row):
  * product_template_id — slang resolves straight to that product.
  * category_id          — slang scopes to a family.
  * term                 — canonical phrase substituted before matching.

Resolution is by NAME at runtime (no hardcoded ids). A product/category that
can't be found is written as OPEN with the reason in `note`, never skipped
silently and never guessed.

Idempotent: re-running fills only missing phrases; it never overwrites a row
Robin has already touched (any non-'proposed' state is left alone).

  docker compose exec -T odoo odoo shell -d neon_crm --no-http < scripts/seed_wa12_aliases.py            # DRY-RUN
  docker compose exec -T -e WA12_ALIAS_SEED_APPLY=1 odoo odoo shell -d neon_crm --no-http < scripts/seed_wa12_aliases.py
"""
import os

APPLY = os.environ.get("WA12_ALIAS_SEED_APPLY") == "1"

Alias = env["neon.equipment.alias"].sudo()
Cat = env["neon.equipment.category"].sudo()
PT = env["product.template"].sudo()
log = []


def out(m):
    log.append(m)


def find_cat(code):
    return Cat.search([("code", "=", code)], limit=1)


def find_product(*needles):
    """First active, NON-test product whose name contains ALL needles. Test
    residue ([TEST-*], P1.M1*, '... smoke test ...') is excluded so a stray
    fixture can never become a confirmed alias target -- the dry-run on the
    local DB caught exactly this ('monitor' -> '[TEST-DELETE] QSC K12.2
    Monitor'; 'smoke' -> 'P1.M1.5 smoke test')."""
    dom = [("active", "=", True),
           ("name", "not ilike", "[TEST"),
           ("name", "not ilike", "[P5M2"),
           ("name", "not ilike", "P1.M1"),
           ("name", "not ilike", "smoke test"),
           # exclude bundled PACKAGES/WEDDING/DJ kits -- a needle like 'smoke'
           # otherwise hits a DJ package whose name lists 'SMOKE MACHINE'.
           ("name", "not ilike", "PACKAGE"),
           ("name", "not ilike", "WEDDING")]
    for n in needles:
        dom.append(("name", "ilike", n))
    return PT.search(dom, order="name", limit=1)


def candidates(*needles):
    """Real product NAMES matching the needles (for an OPEN-row note when more
    than one genuine product matches and Robin must pick)."""
    dom = [("active", "=", True),
           ("name", "not ilike", "[TEST"), ("name", "not ilike", "[P5M2"),
           ("name", "not ilike", "P1.M1"), ("name", "not ilike", "smoke test"),
           ("name", "not ilike", "PACKAGE"), ("name", "not ilike", "WEDDING")]
    for n in needles:
        dom.append(("name", "ilike", n))
    return [p.name for p in PT.search(dom, order="name")]


# Seed plan. Each entry: (phrase, kind, key, state, note).
#   kind ∈ {'cat','term','product'}; key = category code / term string /
#   product needle-tuple. state seeded as 'proposed' unless it's a question only
#   Robin can settle -> 'open'.
PLAN = [
    # --- categories: confident family scoping the directors already use ---
    ("screen", "cat", "visual", "proposed",
     "LED screen family (Visual). Robin: confirm 'screen' always = LED video, "
     "never a projection/AV screen."),
    ("led screen", "cat", "visual", "proposed", "LED video wall family."),
    ("video wall", "cat", "visual", "proposed", "LED video wall family."),
    ("stage", "cat", "staging", "proposed", "Stage/decking family (Staging)."),
    ("staging", "cat", "staging", "proposed", "Staging family."),
    ("truss", "cat", "trussing", "proposed", "Trussing family."),
    ("trussing", "cat", "trussing", "proposed", "Trussing family."),

    # --- term substitutions: expand slang to a canonical search phrase ---
    ("cans", "term", "led can", "open",
     "LED par/can family. Robin: is 'cans' = LED PAR cans (uplighters), and is "
     "it ever used for something else on the floor?"),
    ("pars", "term", "led can", "open",
     "Same as 'cans'? Confirm 'pars'/'parcans' = LED PAR cans."),
    ("parcans", "term", "led can", "open", "Confirm = LED PAR cans."),
    ("pa", "term", "pa system", "open",
     "PA / sound system. Robin: should bare 'PA' map to the PA-system "
     "packages (sized by PAX), and which is the default if no size given?"),
    ("sound system", "term", "pa system", "open",
     "Same as 'PA' -> PA-system packages. Confirm."),

    # --- products: resolve straight to a single catalogue item. Where the real
    #     catalogue has >1 genuine match (sizes/variants), the row is OPEN with
    #     the candidate list appended so Robin picks (never auto-assumed).
    #     Prod catalogue confirmed 13 Jun: 3 totem sizes, 4 molefays, 4
    #     monitors, fog=LOW FOGGER, smoke=VERTICAL SMOKE MACHINES.
    ("totem", "product", ("truss totem", "with base"), "open",
     "TRUSS TOTEM family — 3 sizes exist. ROBIN: pick the DEFAULT bare 'totem' "
     "should resolve to (a size-bearing phrase like '3m totem' should override)."),
    ("totems", "product", ("truss totem", "with base"), "open",
     "Plural of 'totem' — same Q (pick default size)."),
    ("blinder", "product", ("molefay",), "open",
     "MOLEFAY family — 4 variants exist. ROBIN: is a 'blinder' a molefay at "
     "Neon (and which variant), or a distinct fixture? (In '4 blinders on "
     "totems', 4 = QUANTITY and 'on totems' = a separate TRUSS TOTEM line.)"),
    ("blinders", "product", ("molefay",), "open", "Plural of 'blinder' — same Q."),
    ("wedge", "product", ("monitor",), "open",
     "A 'wedge' is a FLOOR monitor (likely POWERWORKS MONITOR, not in-ear). "
     "ROBIN: pick the exact product."),
    ("monitor", "product", ("monitor",), "open",
     "Stage monitor — several exist (floor / in-ear / personal). ROBIN: pick "
     "the exact product bare 'monitor' should resolve to."),
    ("fogger", "product", ("low fogger",), "proposed",
     "-> LOW FOGGER (the only fogger product; 'LOWFOGGER REMOTES' is the "
     "remote accessory). Robin: confirm."),
    ("fog machine", "product", ("low fogger",), "proposed",
     "Same as 'fogger' -> LOW FOGGER. Robin: confirm."),
    ("smoke", "product", ("vertical smoke machine",), "open",
     "-> VERTICAL SMOKE MACHINES (the smoke-machine product; 'REMOTES' is the "
     "accessory). ROBIN: confirm 'smoke' = vertical smoke machine, not the "
     "LOW FOGGER or HAZER."),
]


existing = {a.phrase: a for a in Alias.with_context(active_test=False).search([])}
created, opened, skipped = [], [], []

for phrase, kind, key, state, note in PLAN:
    phrase = phrase.lower().strip()
    if phrase in existing:
        skipped.append((phrase, existing[phrase].state))
        continue

    vals = {"phrase": phrase, "note": note, "state": state}
    target_desc = ""
    if kind == "cat":
        rec = find_cat(key)
        if rec:
            vals["category_id"] = rec.id
            target_desc = "cat:%s" % rec.code
        else:
            vals["state"] = "open"
            vals["note"] = "Category code %r not found on prod — needs review. %s" % (key, note)
    elif kind == "term":
        vals["term"] = key
        target_desc = "term:%r" % key
    elif kind == "product":
        cands = candidates(*key)
        rec = find_product(*key)
        if rec:
            vals["product_template_id"] = rec.id
            target_desc = "product:%s" % rec.name
            # >1 genuine match -> force OPEN and list the choices for Robin.
            if len(cands) > 1:
                vals["state"] = "open"
                vals["note"] = "%s  CANDIDATES: %s" % (note, " | ".join(cands))
        else:
            vals["state"] = "open"
            vals["term"] = " ".join(key)  # fallback so the row is valid + matchable
            vals["note"] = "No product matched %r on prod — left as a TERM, OPEN. %s" % (
                " ".join(key), note)

    row = "%-12s -> %-22s [%s]" % (phrase, target_desc or "(unresolved)", vals["state"])
    if vals["state"] == "open":
        opened.append(row)
    else:
        created.append(row)

    if APPLY:
        Alias.create(vals)

out("=== ALIAS SEED (%s) ===" % ("APPLY" if APPLY else "DRY-RUN"))
out("plan: %d  |  already present (left untouched): %d" % (len(PLAN), len(skipped)))
out("\n-- PROPOSED (Robin: tick to Confirm) --")
for r in created:
    out("  " + r)
out("\n-- OPEN (needs Robin's decision before Confirm) --")
for r in opened:
    out("  " + r)
if skipped:
    out("\n-- already present (state shown; not re-created) --")
    for p, st in skipped:
        out("  %-12s [%s]" % (p, st))

if APPLY:
    env.cr.commit()
    out("\nAPPLIED + committed. Review at Operations -> Slang Aliases.")
else:
    out("\nDRY-RUN only — set WA12_ALIAS_SEED_APPLY=1 to write the PROPOSED/OPEN rows.")

print("\n".join(log))
