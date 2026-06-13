# -*- coding: utf-8 -*-
"""Resolver v2 KEYSTONE — write equipment_category_id to the catalogue-loaded
orphans FROM ROBIN'S CSV `category` column (worksheet e6a4e77).

Root cause (verified on prod): the catalogue load created ~272 products without
equipment_category_id, so category-scoped matching is impossible for half the
inventory ("6M X 2M LED SCREEN" -> category NONE -> booth-for-a-screen). This
re-maps each orphan from the real Zoho section in the CSV, NOT keyword-guessing.

Run (two-step, gated like the catalogue load):
  docker compose cp docs/phase-11/WA12_pricing_decision_worksheet.csv odoo:/tmp/wa12.csv
  # DRY-RUN (default) — prints the plan + row-list, NO writes:
  docker compose exec -T odoo odoo shell -d neon_crm --no-http < scripts/categorize_wa12_catalogue.py
  # APPLY (after the human gate on the printed plan):
  docker compose exec -T -e WA12_CATEGORIZE_APPLY=1 odoo odoo shell -d neon_crm --no-http < scripts/categorize_wa12_catalogue.py

Idempotent: only fills products whose equipment_category_id is EMPTY (the
orphans); never overwrites an already-categorised product. NEW Zoho sections
(PACKAGES / POWER / INTERACTIVE / LOGISTICS / LIVESTREAM / SET BUILD / TENT
DRAPING) get PROPOSED new equipment.category rows -- flagged in the dry-run,
created only on APPLY. Blank-category rows fall back to the keyword family rule
and are flagged for Robin. This is a PROD DATA WRITE -> the apply is the gate.
"""
import csv
import os
import re

APPLY = os.environ.get("WA12_CATEGORIZE_APPLY") == "1"
CSV_PATH = os.environ.get("WA12_WORKSHEET", "/tmp/wa12.csv")

Cat = env["neon.equipment.category"].sudo()
PT = env["product.template"].sudo()
log = []


def out(m):
    log.append(m)


def clean_name(full, category):
    """Mirror the catalogue load: strip a leading '<category> - ' prefix."""
    cat = (category or "").strip()
    if cat and full.startswith(cat + " - "):
        return full[len(cat) + 3:].strip()
    return full.strip()


def norm_section(s):
    return " ".join((s or "").strip().upper().split())


# Existing seeded category codes (resolved to records at run time).
SEEDED = {"sound", "visual", "lighting", "cabling", "laptops", "staging",
          "dance_floor", "effects", "trussing"}

# CSV Zoho section (normalised UPPER) -> existing category code.
SECTION_TO_CODE = {
    "AUDIO EQUIPMENT": "sound",
    "VISUAL EQUIPMENT": "visual",
    "LIGHTING EQUIPMENT": "lighting",
    "SPECIAL EFFECTS EQUIPMENT": "effects",
    "TRUSSING EQUIPMENT": "trussing",
    "STAGING AND TRUSSING EQUIPMENT": "trussing",
    "TRUSSING AND STAGING EQUIPMENT": "trussing",
    "STAGING AND FLOORING EQUIPMENT": "staging",
    "STAGING AND FLOORING": "staging",
    "STAGING AND FLOORING EQUIPMENT ACCESSORIES": "staging",
    "STAGING EQUIPMENT": "staging",
}
# NEW sections -> (proposed code, proposed name). Created on APPLY, flagged.
NEW_SECTIONS = {
    "PACKAGES": ("packages", "Packages"),
    "POWER EQUIPMENT": ("power", "Power"),
    "INTERACTIVE EQUIPMENT": ("interactive", "Interactive"),
    "INTERACTIVE": ("interactive", "Interactive"),
    "LOGISTICS": ("logistics", "Logistics"),
    "LIVESTREAM": ("livestream", "Livestream"),
    "SET BUILD": ("set_build", "Set Build"),
    "TENT DRAPING SERVICES": ("tent_draping", "Tent Draping"),
    "TENT DRAPING": ("tent_draping", "Tent Draping"),
}
# a Staging row whose NAME hits one of these -> Dance Floor (so "dance floor"
# requests scope to a real category).
DANCE_TOKENS = ("floor", "dancefloor", "dance floor", "vinyl", "infinity")


def code_for(section, prod_name):
    sec = norm_section(section)
    if sec in SECTION_TO_CODE:
        code = SECTION_TO_CODE[sec]
        if code == "staging" and any(t in (prod_name or "").lower()
                                     for t in DANCE_TOKENS):
            return "dance_floor", "staging-floor-exception"
        return code, "section"
    if sec in NEW_SECTIONS:
        return NEW_SECTIONS[sec][0], "new-section"
    return None, "unmapped"


# build {clean_name(zoho) -> section} from the CSV.
rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))
name_to_section = {}
blank_names = set()
for r in rows:
    nm = clean_name(r["zoho_full_name"], r.get("category"))
    sec = (r.get("category") or "").strip()
    if sec:
        name_to_section[nm] = sec
    else:
        blank_names.add(nm)

# resolve the existing category records by code.
code_rec = {c.code: c for c in Cat.search([("code", "in", list(SEEDED))])}

# the orphans: workshop products with no category.
orphans = PT.search([("is_workshop_item", "=", True),
                     ("equipment_category_id", "=", False)])

plan = {}          # code -> [product names]
proposed_new = {}  # new code -> (name, [products])
blank_fb = []      # (product, fallback code | None)
unresolved = []
for p in orphans:
    sec = name_to_section.get(p.name)
    if sec:
        code, why = code_for(sec, p.name)
        if code in SEEDED:
            plan.setdefault(code, []).append(p)
        elif code:  # new section
            nm = NEW_SECTIONS[norm_section(sec)][1]
            proposed_new.setdefault(code, (nm, []))[1].append(p)
        else:
            unresolved.append((p, sec))
    elif p.name in blank_names or True:
        # blank CSV category OR not found in the CSV -> keyword family rule.
        fam = env["neon.whatsapp.message"].sudo()._wa6_family_code(p.name)
        blank_fb.append((p, fam))

out("=== CATEGORIZE PLAN (%s) ===" % ("APPLY" if APPLY else "DRY-RUN"))
out("orphans (no category): %d" % len(orphans))
for code in sorted(plan):
    out("  %-12s <- %d products  e.g. %s" % (
        code, len(plan[code]), [p.name for p in plan[code][:3]]))
out("PROPOSED NEW categories (flag for Robin): %s" % (
    {c: (v[0], len(v[1])) for c, v in proposed_new.items()} or "(none)"))
out("BLANK-category / not-in-CSV -> keyword fallback (flag): %d" % len(blank_fb))
for p, fam in blank_fb[:20]:
    out("    %-9s ? %s" % (fam or "NONE", p.name))
if unresolved:
    out("!! UNRESOLVED sections: %s" % [(s, p.name) for p, s in unresolved[:10]])

if not APPLY:
    out("\nDRY-RUN only -- no writes. Set WA12_CATEGORIZE_APPLY=1 after the gate.")
else:
    # create the proposed new categories, then assign.
    for code, (nm, prods) in proposed_new.items():
        rec = Cat.search([("code", "=", code)], limit=1) or Cat.create(
            {"code": code, "name": nm})
        rec.write({})  # noop touch
        for p in prods:
            p.write({"equipment_category_id": rec.id})
        out("CREATED category %s (%s) + assigned %d" % (code, nm, len(prods)))
    for code, prods in plan.items():
        rec = code_rec.get(code) or Cat.search([("code", "=", code)], limit=1)
        for p in prods:
            p.write({"equipment_category_id": rec.id})
        out("ASSIGNED %d -> %s" % (len(prods), code))
    for p, fam in blank_fb:
        if fam:
            rec = code_rec.get(fam) or Cat.search([("code", "=", fam)], limit=1)
            if rec:
                p.write({"equipment_category_id": rec.id})
    env.cr.commit()
    still = PT.search_count([("is_workshop_item", "=", True),
                             ("equipment_category_id", "=", False)])
    out("\nAPPLIED + committed. Orphans remaining: %d" % still)

print("\n".join(log))
