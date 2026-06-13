# -*- coding: utf-8 -*-
"""Resolver v2 KEYSTONE — write equipment_category_id to every catalogue-loaded
orphan, FROM ROBIN'S CSV `category` column + his gate decisions (13 Jun).

Root cause (verified on prod): ~272 products had NO equipment_category_id (the
CSV creates), so category-scoped matching was impossible for half the inventory
("6M X 2M LED SCREEN" -> category NONE -> booth-for-a-screen).

Robin's gate (13 Jun):
  * 192 rows -> their real Zoho section (AUDIO->sound, VISUAL->visual, etc.;
    STAGING/FLOORING rows whose NAME hits floor/vinyl/infinity -> dance_floor).
  * 7 NEW equipment-section categories: Packages / Power / Logistics /
    Interactive / Livestream / Set Build / Tent Draping.
  * 3 NEW non-equipment categories so non-gear hire scopes cleanly:
    Furniture / Catering & Décor / Services (leaving them loose recreates the
    booth-for-a-screen problem in a new corner).
  * The 2 DEPOSITS (DEPOSIT / REFUNDABLE DEPOSIT) -> NO category + flagged for
    removal (accounting artifacts, never a hireable line).

Two-step, gated like the catalogue load:
  docker compose cp docs/phase-11/WA12_pricing_decision_worksheet.csv odoo:/tmp/wa12.csv
  docker compose exec -T odoo odoo shell -d neon_crm --no-http < scripts/categorize_wa12_catalogue.py            # DRY-RUN
  docker compose exec -T -e WA12_CATEGORIZE_APPLY=1 odoo odoo shell -d neon_crm --no-http < scripts/categorize_wa12_catalogue.py
"""
import csv
import os

APPLY = os.environ.get("WA12_CATEGORIZE_APPLY") == "1"
CSV_PATH = os.environ.get("WA12_WORKSHEET", "/tmp/wa12.csv")

Cat = env["neon.equipment.category"].sudo()
PT = env["product.template"].sudo()
M = env["neon.whatsapp.message"].sudo()
log = []


def out(m):
    log.append(m)


def clean_name(full, category):
    cat = (category or "").strip()
    if cat and full.startswith(cat + " - "):
        return full[len(cat) + 3:].strip()
    return full.strip()


def ns(s):
    return " ".join((s or "").strip().upper().split())


SEEDED = {"sound", "visual", "lighting", "cabling", "laptops", "staging",
          "dance_floor", "effects", "trussing"}
SECTION_TO_CODE = {
    "AUDIO EQUIPMENT": "sound", "VISUAL EQUIPMENT": "visual",
    "LIGHTING EQUIPMENT": "lighting", "SPECIAL EFFECTS EQUIPMENT": "effects",
    "TRUSSING EQUIPMENT": "trussing",
    "STAGING AND TRUSSING EQUIPMENT": "trussing",
    "TRUSSING AND STAGING EQUIPMENT": "trussing",
    "STAGING AND FLOORING EQUIPMENT": "staging",
    "STAGING AND FLOORING": "staging",
    "STAGING AND FLOORING EQUIPMENT ACCESSORIES": "staging",
    "STAGING EQUIPMENT": "staging",
}
# new categories to create (code -> name). 7 equipment-section + 3 non-equipment.
NEW_CATS = {
    "packages": "Packages", "power": "Power", "logistics": "Logistics",
    "interactive": "Interactive", "livestream": "Livestream",
    "set_build": "Set Build", "tent_draping": "Tent Draping",
    "furniture": "Furniture", "catering_decor": "Catering & Décor",
    "services": "Services",
}
NEW_SECTIONS = {
    "PACKAGES": "packages", "POWER EQUIPMENT": "power", "INTERACTIVE": "interactive",
    "INTERACTIVE EQUIPMENT": "interactive", "LOGISTICS": "logistics",
    "LIVESTREAM": "livestream", "SET BUILD": "set_build",
    "TENT DRAPING SERVICES": "tent_draping", "TENT DRAPING": "tent_draping",
}
DANCE_TOKENS = ("dancefloor", "dance floor", "vinyl", "infinity")
# non-equipment classifier (Robin's buckets); ordered — first hit wins.
NONEQ_RULES = [
    ("services", ["management", "service", "photograph", "video recording",
                  "editing", "transcription", "exhibition", "meeting", "golf",
                  "symposium", "accomod", "sustenan", "transport",
                  "installation", "install"]),
    ("catering_decor", ["glass", "cutlery", "plate", "napkin", "runner",
                        "underplate", "snack", "savoury", "balloon", "garland",
                        "vase", "flower", "lining", "tent", "canvas", "drap"]),
    ("furniture", ["chair", "banqueting", "table", "cover", "counter",
                   "podium", "stool", "couch"]),
    ("cabling", ["hdmi", "splitter"]),
]


def resolve_code(section, name):
    """The category code for a product, applying Robin's gate + the dance
    override; ('DEPOSIT', None) flags an accounting artifact for removal."""
    n = name.lower()
    if "deposit" in n:
        return "DEPOSIT"
    if any(t in n for t in DANCE_TOKENS):
        return "dance_floor"
    sec = ns(section)
    if sec in SECTION_TO_CODE:
        return SECTION_TO_CODE[sec]
    if sec in NEW_SECTIONS:
        return NEW_SECTIONS[sec]
    # blank / not-in-CSV -> POWERWORKS PA monitoring is sound; then the
    # equipment-family keyword rule; then the non-equipment buckets.
    if "powerworks" in n or "mixer" in n or "pax" in n or "backline" in n \
            or "pa system" in n:
        return "sound"
    fam = M._wa6_family_code(name)
    if fam:
        return fam
    if n.strip() == "livestream":
        return "livestream"
    if "logistic" in n:
        return "logistics"
    for code, kws in NONEQ_RULES:
        if any(k in n for k in kws):
            return code
    return None


rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))
name_to_section = {clean_name(r["zoho_full_name"], r.get("category")):
                   (r.get("category") or "").strip() for r in rows}

# ALL uncategorised products, not just is_workshop_item (proof-#3 verify found
# non-workshop hire items -- FLOOR BOARDS INSTALLATION (service), "Speaker" --
# that the workshop-only filter had skipped). resolve_code returns a category
# for hire items; the 2 deposits resolve to DEPOSIT (no category, removal).
orphans = PT.with_context(active_test=False).search(
    [("equipment_category_id", "=", False)])
by_code = {}
deposits = []
unclassified = []
for p in orphans:
    code = resolve_code(name_to_section.get(p.name, ""), p.name)
    if code == "DEPOSIT":
        deposits.append(p)
    elif code:
        by_code.setdefault(code, []).append(p)
    else:
        unclassified.append(p)

out("=== CATEGORIZE PLAN (%s) ===" % ("APPLY" if APPLY else "DRY-RUN"))
out("orphans: %d" % len(orphans))
for code in sorted(by_code):
    tag = " (NEW)" if code in NEW_CATS else ""
    out("  %-14s%s <- %d  e.g. %s" % (
        code, tag, len(by_code[code]), [p.name for p in by_code[code][:3]]))
out("DEPOSITS -> NO category, FLAG FOR REMOVAL (%d): %s" % (
    len(deposits), [p.name for p in deposits]))
if unclassified:
    out("!! UNCLASSIFIED (must be 0): %s" % [p.name for p in unclassified])

if not APPLY:
    out("\nDRY-RUN only -- set WA12_CATEGORIZE_APPLY=1 after Robin's gate.")
else:
    code_rec = {c.code: c for c in Cat.search([])}
    for code, prods in by_code.items():
        rec = code_rec.get(code)
        if not rec:
            rec = Cat.create({"code": code,
                              "name": NEW_CATS.get(code, code.title())})
            code_rec[code] = rec
            out("CREATED category %s (%s)" % (code, rec.name))
        for p in prods:
            p.write({"equipment_category_id": rec.id})
        out("ASSIGNED %d -> %s" % (len(prods), code))
    env.cr.commit()
    still = PT.with_context(active_test=False).search_count(
        [("equipment_category_id", "=", False)])
    out("\nAPPLIED + committed. Orphans remaining: %d (the %d deposits, "
        "left uncategorised pending Robin's removal)." % (still, len(deposits)))

print("\n".join(log))
