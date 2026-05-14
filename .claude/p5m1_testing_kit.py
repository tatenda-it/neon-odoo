"""P5.M1 — local-only equipment testing kit.

CREATES on the local neon_crm database:
  * 46 product.template entries spanning all 9 workshop categories
    with realistic Neon-style names and ALL-CAPS workshop_name
    (the PHP workshop convention).
  * ~330 neon.equipment.unit records, distributed across the
    locked 9-state lifecycle (2026-05-14): 65% active, 12% draft,
    6% reserved, 6% checked_out, 3% returned, 3% maintenance,
    2% transferred, 2% damaged, 1% decommissioned. Every state
    gets at least a handful of representatives so the kanban /
    tree / form decorations are visible.

Every record carries the "[TEST-DELETE]" marker in name +
workshop_name so the symmetric teardown script can find and
remove the whole set with a single ilike scan.

CRITICAL — LOCAL ONLY
=====================
NEVER run this on Hetzner production (188.245.154.84 /
crm.neonhiring.com). Production receives equipment data from
real CSVs / the PHP migration when Tatenda greenlights B6.

INVOCATION
==========
  docker compose exec -T odoo odoo shell -d neon_crm \\
      < .claude/p5m1_testing_kit.py

IDEMPOTENCY
===========
Safe to re-run. Each product.template is created only if its
workshop_name doesn't already exist; existing types are skipped
along with their units. Re-running on a fully-seeded DB reports
zero creates.

TEARDOWN
========
  docker compose exec -T odoo odoo shell -d neon_crm \\
      < .claude/p5m1_testing_kit_teardown.py
"""
MARKER = "[TEST-DELETE]"


# ---------------------------------------------------------------
# ITEM CATALOGUE — (category_code, name, units, tracking_override)
# tracking_override is None when the item should follow the
# category default; set to "serial" or "quantity" when the
# spec D4 says the per-item override differs from the category.
# ---------------------------------------------------------------
ITEM_SPECS = [
    # Sound (8 types, 24 units): mixers serial; mics + speakers quantity
    ("sound", "QU16 Mixer",                    3, "serial"),
    ("sound", "SQ6 Mixer",                     3, "serial"),
    ("sound", "Behringer X32 Mixer",           3, "serial"),
    ("sound", "Shure SM58 Mic",                3, "quantity"),
    ("sound", "Shure Beta 58A Wireless Mic",   3, "quantity"),
    ("sound", "Yamaha DXR12 Speaker",          3, "quantity"),
    ("sound", "RCF EVOX 12 Column Array",      3, "quantity"),
    ("sound", "QSC K12.2 Monitor",             3, "quantity"),
    # Visual (4 types, 12 units): all serial
    ("visual", "Absen A3 LED Panel",           3, None),
    ("visual", "Roe Black Pearl LED Panel",    3, None),
    ("visual", "BenQ MH535 Projector",         3, None),
    ("visual", "Epson EB-2247U Projector",     3, None),
    # Lighting (6 types, 48 units): all serial (matches category)
    ("lighting", "Robe MegaPointe Beam",       8, None),
    ("lighting", "Martin MAC Aura PXL",        8, None),
    ("lighting", "ADJ Inno Pocket Spot",       8, None),
    ("lighting", "Cameo Studio PAR 64",        8, None),
    ("lighting", "Chauvet Intimidator Wash Zoom 450", 8, None),
    ("lighting", "Showtec Sunstrip Active MKII", 8, None),
    # Cabling and Accessories (10 types, 120 units): all quantity
    ("cabling", "XLR Cable 5m",                12, None),
    ("cabling", "XLR Cable 10m",               12, None),
    ("cabling", "XLR Cable 20m",               12, None),
    ("cabling", "DMX Cable 5m",                12, None),
    ("cabling", "DMX Cable 10m",               12, None),
    ("cabling", "Powercon Cable 3m",           12, None),
    ("cabling", "Powercon Cable 5m",           12, None),
    ("cabling", "IEC C13 Cable",               12, None),
    ("cabling", "HDMI Cable 5m",               12, None),
    ("cabling", "Cat6 Ethernet Cable 10m",     12, None),
    # Laptops (3 types, 6 units): all serial
    ("laptops", "Lenovo ThinkPad P72",         2, None),
    ("laptops", "Lenovo ThinkPad T490",        2, None),
    ("laptops", "Apple MacBook Pro 16",        2, None),
    # Staging (3 types, 18 units): all quantity
    ("staging", "Litedeck Stage Module 2x1m",  6, None),
    ("staging", "Litedeck Stage Module 1x1m",  6, None),
    ("staging", "Stage Step Unit",             6, None),
    # Dance Floor (2 types, 30 units): all quantity
    ("dance_floor", "White Dance Floor Panel 1x1m",    15, None),
    ("dance_floor", "LED Dance Floor Panel 0.5x0.5m",  15, None),
    # Effects (4 types, 12 units): fazer/jets serial; bubble/confetti quantity
    ("effects", "Antari Z350 Fazer",           3, "serial"),
    ("effects", "Antari B100 Bubble Machine",  3, "quantity"),
    ("effects", "CO2 Jet",                     3, "serial"),
    ("effects", "Confetti Cannon",             3, "quantity"),
    # Trussing (6 types, 60 units): all quantity
    ("trussing", "Global Truss F34 2m",        10, None),
    ("trussing", "Global Truss F34 1m",        10, None),
    ("trussing", "Global Truss F34 Corner Block", 10, None),
    ("trussing", "Genie ST24 Lift Tower",      10, None),
    ("trussing", "Truss Base Plate 75kg",      10, None),
    ("trussing", "Black Truss Pin",            10, None),
]


# ---------------------------------------------------------------
# STATE DISTRIBUTION — applied deterministically across the global
# unit index so the same input produces the same output. Locked
# 2026-05-14 to exercise all 9 states (the earlier 6-state
# distribution skipped 'returned', 'transferred', 'damaged' — the
# kanban couldn't show their decorations during browser smoke).
# ---------------------------------------------------------------
STATE_DISTRIBUTION = [
    ("active",         0.65),  # ~215 units — primary "available" pool
    ("draft",          0.12),  # ~40  units — newly enrolled
    ("reserved",       0.06),  # ~20  units — held for upcoming jobs
    ("checked_out",    0.06),  # ~20  units — currently on jobs
    ("returned",       0.03),  # ~10  units — back, pending check-in
    ("maintenance",    0.03),  # ~10  units — in repair
    ("transferred",    0.02),  # ~7   units — in transit between jobs
    ("damaged",        0.02),  # ~7   units — incident-flagged
    ("decommissioned", 0.01),  # ~3   units — retired
]


def state_for_index(idx, total):
    """Map a 0-indexed unit position to a state per the
    cumulative distribution. Deterministic, total-aware."""
    fraction = idx / max(total, 1)
    cumulative = 0.0
    for state, pct in STATE_DISTRIBUTION:
        cumulative += pct
        if fraction < cumulative:
            return state
    return "active"  # rounding safety


# ===============================================================
print("=" * 72)
print("P5.M1 TESTING KIT SEED — START")
print("=" * 72)

Category = env["neon.equipment.category"]
Product = env["product.template"]
Unit = env["neon.equipment.unit"]

# Resolve all 9 categories up front
cat_by_code = {
    c.code: c for c in Category.search([])
}
missing_codes = {spec[0] for spec in ITEM_SPECS} - set(cat_by_code)
if missing_codes:
    print("ABORT — missing categories:", missing_codes)
    print("Has the neon_equipment_category seed data loaded?")
    raise SystemExit(1)


# Compute the total unit count up front for state distribution
TOTAL_UNITS = sum(units for _, _, units, _ in ITEM_SPECS)
print("planned: %d types, %d units" % (len(ITEM_SPECS), TOTAL_UNITS))


# ---------------------------------------------------------------
# Walk the catalogue. Idempotency: per-type search by
# workshop_name. If the product exists, skip it AND its units.
# ---------------------------------------------------------------
results = {
    "types_created": 0,
    "types_skipped": 0,
    "units_created": 0,
    "state_counts": {state: 0 for state, _ in STATE_DISTRIBUTION},
}

# Global unit index drives state distribution
global_idx = 0

for cat_code, name, unit_count, tracking_override in ITEM_SPECS:
    full_name = "%s %s" % (MARKER, name)
    workshop_name = name.upper()
    category = cat_by_code[cat_code]

    existing = Product.sudo().search(
        [("workshop_name", "=", workshop_name)], limit=1)
    if existing:
        # Skip the type AND advance global_idx past its units so
        # state distribution stays deterministic.
        results["types_skipped"] += 1
        global_idx += unit_count
        continue

    tracking = tracking_override or category.default_tracking
    product = Product.sudo().create({
        "name": full_name,
        "is_workshop_item": True,
        "equipment_category_id": category.id,
        "workshop_name": workshop_name,
        "tracking_mode": tracking,
    })
    results["types_created"] += 1

    for unit_idx in range(unit_count):
        state = state_for_index(global_idx, TOTAL_UNITS)
        vals = {
            "product_template_id": product.id,
            "state": state,
            "workshop_location": "Workshop A — Shelf %s" % (
                chr(ord("A") + (global_idx // 30) % 26)),
        }
        # Serial-tracked items get a numbered serial; quantity
        # items get an asset_tag instead. Always-unique to honour
        # the model's UNIQUE constraints.
        if tracking == "serial":
            vals["serial_number"] = "%s #%d" % (workshop_name, unit_idx + 1)
        else:
            vals["asset_tag"] = "%s-%d" % (workshop_name.replace(" ", "_"), unit_idx + 1)
        Unit.sudo().create(vals)
        results["units_created"] += 1
        results["state_counts"][state] += 1
        global_idx += 1

env.cr.commit()


# ===============================================================
print()
print("=" * 72)
print("SEED COMPLETE — counts")
print("=" * 72)
print("types created: %d  (skipped %d)" % (
    results["types_created"], results["types_skipped"]))
print("units created: %d" % results["units_created"])
print()
print("state distribution:")
for state, pct in STATE_DISTRIBUTION:
    actual = results["state_counts"][state]
    target = int(round(TOTAL_UNITS * pct))
    print("  %-16s %4d  (target ~%d, %.0f%%)" % (
        state, actual, target, pct * 100))
print()
# Verification — query back the DB by category code
print("verification — units per category:")
all_seeded_products = Product.sudo().search(
    [("workshop_name", "ilike", "")])  # any workshop item
test_products = Product.sudo().search(
    [("name", "ilike", MARKER)])
print("  total TEST-DELETE products in DB: %d" % len(test_products))
for code, cat in sorted(cat_by_code.items()):
    units_in_cat = Unit.sudo().search([
        ("product_template_id.name", "ilike", MARKER),
        ("equipment_category_id", "=", cat.id),
    ])
    print("  %-13s %s : %d units" % (code, cat.name, len(units_in_cat)))

env.cr.commit()
