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
    """Return the float rate, or None for blank/unparseable input. None is a
    'no rate captured' signal (NOT 0.0) -- the caller then creates the product
    WITHOUT a rule (resolves no_rule -> the guard blocks) instead of minting a
    free $0 rule (review WA12LOAD-4). An explicit '0.00' parses to 0.0 and is
    treated the same as None by the caller (a $0 rule is never created)."""
    s = (s or "").upper().replace("USD", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


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
    """One active USD product-rule per product, flat 1.0 bracket. Idempotent,
    and HEALS a deactivated same-key row: the SQL unique key is
    UNIQUE(product, currency, effective_date) and does NOT include `active`, so
    a blind create would collide with a previously-deactivated rule (review
    WA12LOAD-5). We therefore match across inactive rows and reactivate +
    refresh rather than create. Never called with a None/<=0 rate (the caller
    skips the rule so the product resolves no_rule)."""
    if not APPLY:
        return
    rule = Rule.with_context(active_test=False).search(
        [("product_template_id", "=", product.id),
         ("currency_id", "=", USD.id)],
        order="effective_date desc, id desc", limit=1)
    if rule:
        rule.write({"base_rate": rate, "active": True})
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
n_create = n_map = n_skip = n_rename = n_unresolved = n_unpriced = 0


def _no_rate(rate):
    """A missing (None) or non-positive rate -> create the product but NO rule
    (resolves no_rule -> guard blocks), never a free $0 rule (WA12LOAD-4)."""
    return rate is None or rate <= 0

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
        n_create += 1
        if _no_rate(rate):
            n_unpriced += 1
            out("CREATE-UNPRICED: %r — product %s, NO rule (no rate captured; "
                "resolves no_rule -> guard blocks). FIX the worksheet rate." % (
                    name, "created" if created else "exists"))
        else:
            upsert_rule(p, rate)
            out("CREATE: %r @ $%.2f (%s)" % (
                name, rate, r.get("create_type") or "equipment"))
        continue

    if disp == "map":
        # rename-aware lookup so a RE-RUN re-finds the ALREADY-renamed product
        # (the worksheet peer is the PRE-rename name; review WA12LOAD-3).
        target = RENAMES.get(peer)
        if not target and any(peer.startswith(s) for s in SERIAL_DROP):
            target = next(s for s in SERIAL_DROP if peer.startswith(s))
        prod = find_product(peer) or (find_product(target) if target else None)
        if not prod:
            n_unresolved += 1
            out("MAP-UNRESOLVED: peer %r (target %r) not found (zoho %r)" % (
                peer, target, name))
            continue
        # rename only if the CURRENT name still differs from the target.
        new = RENAMES.get(prod.name)
        if not new and any(prod.name.startswith(s) for s in SERIAL_DROP):
            new = next(s for s in SERIAL_DROP if prod.name.startswith(s))
        # show the rate APPLY will write (the dry-run is the money-write gate).
        rate_txt = " @ $%.2f" % rate if not _no_rate(rate) else " (no rate)"
        if new and new != prod.name:
            n_rename += 1
            out("MAP+RENAME: %r -> %r%s" % (prod.name, new, rate_txt))
            if APPLY:
                prod.write({"name": new})
        else:
            out("MAP: %r%s" % (prod.name, rate_txt))
        if _no_rate(rate):
            n_unpriced += 1
            out("MAP-UNPRICED: %r — NO rule (no rate captured)." % prod.name)
        else:
            upsert_rule(prod, rate)
        n_map += 1
        continue

# binding (a): the placeholder CATEGORY rules -- deactivated ONLY on a CLEAN
# apply (so a product with no product rule resolves no_rule, never placeholder
# money). Reported always; written only inside the clean-apply branch below.
placeholders = Rule.search([("product_template_id", "=", False),
                            ("active", "=", True)])
out("\nDEACTIVATE (on clean apply) %d placeholder CATEGORY rule(s): %s" % (
    len(placeholders), placeholders.mapped("name")))

# count verification (always printed)
out("\n=== PLAN (%s) ===" % ("APPLY" if APPLY else "DRY-RUN"))
out("create=%d (of which UNPRICED/no-rule=%d)  map=%d  rename=%d  skip=%d  "
    "unresolved-maps=%d  rows=%d" % (
        n_create, n_unpriced, n_map, n_rename, n_skip, n_unresolved, len(rows)))
prod_rules = Rule.search_count([("product_template_id", "!=", False)])
out("product-scoped rules now in DB=%d" % prod_rules)
if n_unpriced:
    out("note: %d row(s) carry NO rate -> created WITHOUT a rule (resolve "
        "no_rule -> the guard blocks quoting them until a real rate is set; "
        "named LED size-variants + services awaiting a per-name rate from "
        "Robin -- ruling 3a: there is NO m2 rule, size-variants are priced "
        "by name)." % n_unpriced)

# HARD GATE (review WA12LOAD-2): unresolved MAP rows mean the worksheet peers
# don't match live product names -> a half-applied, partially-deactivated
# catalogue. ABORT the APPLY (rollback) rather than commit a broken load.
if APPLY and n_unresolved:
    env.cr.rollback()
    out("\n!! ABORTED: %d unresolved MAP row(s) -- NOTHING committed (no rules "
        "written, no category rules deactivated). Fix the peer names / RENAMES "
        "on this DB and re-run." % n_unresolved)
elif APPLY:
    placeholders.write({"active": False})
    out("DEACTIVATED %d placeholder CATEGORY rule(s)." % len(placeholders))
    env.cr.commit()
    out("\nAPPLIED + committed.")
else:
    out("\nDRY-RUN only -- no writes. Set WA12_APPLY=1 to apply after the gate.")

print("\n".join(log))
