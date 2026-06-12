# -*- coding: utf-8 -*-
"""
WA-12 / WA-12.1 — one-shot pricing catalogue load (run at the DEPLOY gate).

Reads the ticked WA12_pricing_decision_worksheet.csv and, for the 314 Zoho
items, materialises the per-product pricing model:

  * CREATE (271): a product.template (workshop / service) + a per-product
    pricing.rule (flat 1.0 bracket) at the worksheet rate (USD v1).
  * MAP (41): resolve the EXISTING Odoo product by its worksheet peer, apply the
    listed RENAME, and set/refresh its per-product rule at the worksheet rate.
  * SKIP (2): SHURE / INNOPOW receivers — add-ons, NO rule (so quoting one alone
    -> no_rule -> the guard blocks; correct).
  * 3 user rate-corrections (12-Jun): LOW FOGGER $150, POWERWORKS MONITOR
    $45/unit (the Zoho $180 group-of-4 -> per-unit), POWERWORKS INEAR MONITOR
    $20/unit (new; never in Zoho).
  * Binding (a): DEACTIVATE the P6 placeholder CATEGORY rules so a product with
    no product rule resolves no_rule (never placeholder money). The category
    tier stays as architecture for future real category rates.
  * Binding (b): every per-product rule gets a single flat bracket
    (day_from=1, day_to=-1, multiplier=1.0).

Run (DEPLOY gate, two-step):
  docker compose cp docs/phase-11/WA12_pricing_decision_worksheet.csv odoo:/tmp/wa12.csv
  # 1) DRY-RUN (default) — prints the full plan + count verification, NO writes:
  docker compose exec -T odoo odoo shell -d neon_crm --no-http < scripts/load_wa12_pricing_catalogue.py
  # 2) APPLY (after the human gate on the printed plan):
  docker compose exec -T -e WA12_APPLY=1 odoo odoo shell -d neon_crm --no-http < scripts/load_wa12_pricing_catalogue.py

Idempotent: re-running upserts (get-or-create products, get-or-create one active
USD rule per product, idempotent renames). Money-adjacent prod write -> the apply
is the human gate per the data-load ritual.
"""
import csv
import os
import re

APPLY = os.environ.get("WA12_APPLY") == "1"
CSV_PATH = os.environ.get("WA12_WORKSHEET", "/tmp/wa12.csv")
EFFECTIVE = "2020-01-01"   # any past date; the resolver takes latest <= today

# The 5 MAP renames (current Odoo name -> corrected name), per the worksheet.
RENAMES = {
    "POWERWORKS ZETHIUS-210BPW SUBS": "POWERWORKS ZETHUS-210BPW SUBS",
    "CAN RGB LED (old)": "RGB LED CAN",
    "SQ6 MIXER": "ALLEN & HEATH SQ6 MIXER",
    "361 BOOTH": "360 BOOTH",
}
# serial-drop rename matched by prefix (the peer carries a SR# suffix).
SERIAL_DROP = ("AVOLITES TITAN MOBILE LIGHTING DESK",)

PLACEHOLDER = 1.0
log = []


def out(msg):
    log.append(msg)


def parse_rate(s):
    s = (s or "").upper().replace("USD", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def clean_name(full, category):
    cat = (category or "").strip()
    if cat and full.startswith(cat + " - "):
        return full[len(cat) + 3:].strip()
    return full.strip()


def strip_score(peer):
    return re.sub(r"\s*\(~[0-9.]+\)\s*$", "", peer or "").strip()


PT = env["product.template"].sudo()
Rule = env["neon.finance.pricing.rule"].sudo()
Brk = env["neon.finance.pricing.bracket"].sudo()
ECat = env["neon.equipment.category"].sudo()
USD = env.ref("base.USD")


def find_product(name):
    return PT.with_context(active_test=False).search(
        [("name", "=", name)], limit=1)


def upsert_rule(product, rate):
    """One active USD product-rule per product, flat 1.0 bracket. Idempotent."""
    if not APPLY:
        return
    rule = Rule.search([("product_template_id", "=", product.id),
                        ("currency_id", "=", USD.id), ("active", "=", True)],
                       limit=1)
    if rule:
        rule.write({"base_rate": rate})
    else:
        rule = Rule.create({
            "product_template_id": product.id, "currency_id": USD.id,
            "base_rate": rate, "effective_date": EFFECTIVE})
    if not rule.bracket_ids:
        Brk.create({"rule_id": rule.id, "sequence": 1, "day_from": 1,
                    "day_to": -1, "multiplier": 1.0})


def ensure_product(name, ctype):
    p = find_product(name)
    if p:
        return p, False
    if not APPLY:
        return PT, True  # placeholder; dry-run reports a create
    p = PT.create({
        "name": name, "sale_ok": True,
        "is_workshop_item": (ctype != "service"),
        "type": "service" if ctype == "service" else "consu",
    })
    return p, True

# ---------------------------------------------------------------- load
rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))
n_create = n_map = n_skip = n_rename = n_unresolved = 0

for r in rows:
    disp = r["disposition"].strip()
    rate = parse_rate(r["rate"])
    name = clean_name(r["zoho_full_name"], r["category"])
    peer = strip_score(r["proposed_odoo_peer"])
    note = r.get("OVERRIDE_note", "")

    if "RESTRUCTURE" in note:   # #27 monitor split (special)
        p, created = ensure_product("POWERWORKS MONITOR", "equipment")
        upsert_rule(p, 45.0)
        n_create += 1 if created else 0
        out("MONITOR: create 'POWERWORKS MONITOR' @ $45/unit %s" % (
            "(new)" if created else "(exists)"))
        inear = find_product("POWERWORKS INEAR MONITOR")
        if inear:
            upsert_rule(inear, 20.0)
            out("MONITOR: 'POWERWORKS INEAR MONITOR' -> $20/unit")
        else:
            out("MONITOR: !! 'POWERWORKS INEAR MONITOR' not found -- check name")
        continue

    if disp == "skip":
        n_skip += 1
        out("SKIP: %s (no rule -- add-on)" % name)
        continue

    if disp == "create":
        p, created = ensure_product(name, r.get("create_type") or "equipment")
        upsert_rule(p, rate)
        n_create += 1
        out("CREATE: %r @ $%.2f (%s)" % (name, rate, r.get("create_type") or "equipment"))
        continue

    if disp == "map":
        prod = find_product(peer)
        if not prod:
            n_unresolved += 1
            out("MAP-UNRESOLVED: peer %r not found (zoho %r @ $%.2f)" % (peer, name, rate))
            continue
        # rename?
        new = RENAMES.get(prod.name)
        if not new and any(prod.name.startswith(s) for s in SERIAL_DROP):
            new = next(s for s in SERIAL_DROP if prod.name.startswith(s))
        if new and new != prod.name:
            n_rename += 1
            out("MAP+RENAME: %r -> %r @ $%.2f" % (prod.name, new, rate))
            if APPLY:
                prod.write({"name": new})
        else:
            out("MAP: %r @ $%.2f" % (prod.name, rate))
        upsert_rule(prod, rate)
        n_map += 1
        continue

# binding (a): deactivate the placeholder CATEGORY rules
placeholders = Rule.search([("product_template_id", "=", False),
                            ("active", "=", True)])
out("\nDEACTIVATE %d placeholder CATEGORY rule(s): %s" % (
    len(placeholders), placeholders.mapped("name")))
if APPLY:
    placeholders.write({"active": False})

# count verification
out("\n=== PLAN (%s) ===" % ("APPLY" if APPLY else "DRY-RUN"))
out("create=%d  map=%d  rename=%d  skip=%d  unresolved-maps=%d  rows=%d" % (
    n_create, n_map, n_rename, n_skip, n_unresolved, len(rows)))
out("placeholder category rules deactivated=%d" % len(placeholders))
prod_rules = Rule.search_count([("product_template_id", "!=", False)])
out("product-scoped rules now in DB=%d (expect ~312 after a clean apply)" % prod_rules)
if n_unresolved:
    out("!! %d MAP rows unresolved -- resolve before APPLY (names differ from "
        "the worksheet peers on this DB)." % n_unresolved)

if APPLY:
    env.cr.commit()
    out("\nAPPLIED + committed.")
else:
    out("\nDRY-RUN only -- no writes. Set WA12_APPLY=1 to apply after the gate.")

print("\n".join(log))
