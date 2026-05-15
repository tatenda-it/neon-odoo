"""P5.M3 smoke — tracking-mode validators on neon.equipment.unit.

T280 serial-tracked unit blank serial state='active' raises
T281 same product + same serial raises (existing SQL UNIQUE)
T282 quantity-tracked 5 units blank serial state='active' OK
T283 batch-tracked unit blank batch_code state='active' raises
T284 batch-tracked 3 units sharing batch_code='BATCH-A' OK
T285 draft bypasses serial validation
T286 decommissioned bypasses serial validation
T287 product.tracking_mode quantity -> serial with blank-serial unit raises
T288 product.tracking_mode serial -> quantity always allowed (loosens)
"""
from odoo.exceptions import ValidationError
from psycopg2 import IntegrityError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Unit = env["neon.equipment.unit"]
Product = env["product.template"]
sound_cat = env.ref("neon_jobs.equipment_category_sound")
cabling_cat = env.ref("neon_jobs.equipment_category_cabling")
effects_cat = env.ref("neon_jobs.equipment_category_effects")


def _get_or_make_product(workshop_name, name, tracking_mode, category):
    p = Product.sudo().search(
        [("workshop_name", "=", workshop_name)], limit=1)
    if not p:
        p = Product.sudo().create({
            "name": name,
            "is_workshop_item": True,
            "equipment_category_id": category.id,
            "workshop_name": workshop_name,
            "tracking_mode": tracking_mode,
        })
    else:
        # Ensure clean state even on rerun
        p.write({"tracking_mode": tracking_mode,
                 "equipment_category_id": category.id})
    return p


serial_product = _get_or_make_product(
    "P5M3_SERIAL_TEST", "[P5M3] Serial Test Product",
    "serial", sound_cat)
quantity_product = _get_or_make_product(
    "P5M3_QUANTITY_TEST", "[P5M3] Quantity Test Product",
    "quantity", cabling_cat)
batch_product = _get_or_make_product(
    "P5M3_BATCH_TEST", "[P5M3] Batch Test Product",
    "batch", effects_cat)

# Clean prior P5M3 units so reruns don't trip UNIQUE constraints
for prod in (serial_product, quantity_product, batch_product):
    Unit.sudo().search(
        [("product_template_id", "=", prod.id)]).unlink()
env.cr.commit()
print("products: serial=", serial_product.tracking_mode,
      " quantity=", quantity_product.tracking_mode,
      " batch=", batch_product.tracking_mode)


def _try(fn):
    """Run fn inside a savepoint so IntegrityError / ValidationError
    don't abort the outer transaction. Returns (exception, value)."""
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001 — broad on purpose for smoke
        return (e, None)


# ============================================================
print()
print("=" * 72)
print("T280 - serial-tracked, blank serial, state='active' raises")
print("=" * 72)
err, _v = _try(lambda: Unit.sudo().create({
    "product_template_id": serial_product.id,
    "state": "active",
    # no serial_number
}))
ok = isinstance(err, ValidationError) and "serial" in str(err).lower()
print("  raised:", type(err).__name__ if err else None)
print("  msg excerpt:", (str(err) or "")[:120])
print("T280:", "PASS" if ok else "FAIL")
results["T280"] = ok


# ============================================================
print()
print("=" * 72)
print("T281 - same product + same serial raises (SQL UNIQUE)")
print("=" * 72)
u281a = Unit.sudo().create({
    "product_template_id": serial_product.id,
    "state": "active",
    "serial_number": "T281-SN-A",
})
err, _v = _try(lambda: Unit.sudo().create({
    "product_template_id": serial_product.id,
    "state": "active",
    "serial_number": "T281-SN-A",
}))
ok = isinstance(err, IntegrityError) or (
    isinstance(err, Exception)
    and "unique" in str(err).lower())
print("  raised:", type(err).__name__ if err else None)
print("T281:", "PASS" if ok else "FAIL")
results["T281"] = ok


# ============================================================
print()
print("=" * 72)
print("T282 - quantity-tracked 5 units blank serial state='active' OK")
print("=" * 72)
err, units = _try(lambda: Unit.sudo().create([{
    "product_template_id": quantity_product.id,
    "state": "active",
    "asset_tag": "T282-Q-%d" % i,  # unique to satisfy asset_tag UNIQUE
    # no serial_number — should be fine for quantity-tracked
} for i in range(5)]))
ok = err is None and len(units) == 5 and all(
    u.state == "active" and not u.serial_number for u in units)
print("  err:", type(err).__name__ if err else None)
print("  created:", len(units) if units else 0)
print("T282:", "PASS" if ok else "FAIL")
results["T282"] = ok


# ============================================================
print()
print("=" * 72)
print("T283 - batch-tracked, blank batch_code, state='active' raises")
print("=" * 72)
err, _v = _try(lambda: Unit.sudo().create({
    "product_template_id": batch_product.id,
    "state": "active",
    "asset_tag": "T283-B-1",
    # no batch_code
}))
ok = isinstance(err, ValidationError) and "batch" in str(err).lower()
print("  raised:", type(err).__name__ if err else None)
print("  msg excerpt:", (str(err) or "")[:120])
print("T283:", "PASS" if ok else "FAIL")
results["T283"] = ok


# ============================================================
print()
print("=" * 72)
print("T284 - batch-tracked 3 units same batch_code OK")
print("=" * 72)
err, units = _try(lambda: Unit.sudo().create([{
    "product_template_id": batch_product.id,
    "state": "active",
    "asset_tag": "T284-B-%d" % i,
    "batch_code": "BATCH-A",
} for i in range(3)]))
ok = err is None and len(units) == 3 and all(
    u.batch_code == "BATCH-A" for u in units)
print("  err:", type(err).__name__ if err else None)
print("  created:", len(units) if units else 0,
      " batch_codes:",
      [u.batch_code for u in units] if units else [])
print("T284:", "PASS" if ok else "FAIL")
results["T284"] = ok


# ============================================================
print()
print("=" * 72)
print("T285 - serial-tracked blank serial state='draft' bypasses")
print("=" * 72)
err, u285 = _try(lambda: Unit.sudo().create({
    "product_template_id": serial_product.id,
    "state": "draft",
    "asset_tag": "T285-D-1",
    # no serial_number — but state='draft' bypasses
}))
ok = err is None and u285 and u285.state == "draft"
print("  err:", type(err).__name__ if err else None)
print("  state:", u285.state if u285 else None)
print("T285:", "PASS" if ok else "FAIL")
results["T285"] = ok


# ============================================================
print()
print("=" * 72)
print("T286 - serial-tracked blank serial state='decommissioned' bypasses")
print("=" * 72)
err, u286 = _try(lambda: Unit.sudo().create({
    "product_template_id": serial_product.id,
    "state": "decommissioned",
    "asset_tag": "T286-X-1",
    # no serial_number
}))
ok = err is None and u286 and u286.state == "decommissioned"
print("  err:", type(err).__name__ if err else None)
print("  state:", u286.state if u286 else None)
print("T286:", "PASS" if ok else "FAIL")
results["T286"] = ok


# ============================================================
print()
print("=" * 72)
print("T287 - tracking_mode tightening (quantity -> serial) raises")
print("=" * 72)
# Build a dedicated quantity product so we don't disturb earlier tests
T287_WORKSHOP = "P5M3_T287_TIGHTEN"
Unit.sudo().search([
    ("product_template_id.workshop_name", "=", T287_WORKSHOP)]).unlink()
Product.sudo().search([
    ("workshop_name", "=", T287_WORKSHOP)]).unlink()
p287 = Product.sudo().create({
    "name": "[P5M3] T287 Tighten Test",
    "is_workshop_item": True,
    "equipment_category_id": cabling_cat.id,
    "workshop_name": T287_WORKSHOP,
    "tracking_mode": "quantity",
})
u287 = Unit.sudo().create({
    "product_template_id": p287.id,
    "state": "active",
    "asset_tag": "T287-A",
    # no serial_number — fine for quantity
})
err, _v = _try(lambda: p287.write({"tracking_mode": "serial"}))
ok = isinstance(err, ValidationError) and "serial" in str(err).lower()
print("  raised:", type(err).__name__ if err else None)
print("  msg excerpt:", (str(err) or "")[:140])
print("T287:", "PASS" if ok else "FAIL")
results["T287"] = ok


# ============================================================
print()
print("=" * 72)
print("T288 - tracking_mode loosening (serial -> quantity) OK")
print("=" * 72)
T288_WORKSHOP = "P5M3_T288_LOOSEN"
Unit.sudo().search([
    ("product_template_id.workshop_name", "=", T288_WORKSHOP)]).unlink()
Product.sudo().search([
    ("workshop_name", "=", T288_WORKSHOP)]).unlink()
p288 = Product.sudo().create({
    "name": "[P5M3] T288 Loosen Test",
    "is_workshop_item": True,
    "equipment_category_id": sound_cat.id,
    "workshop_name": T288_WORKSHOP,
    "tracking_mode": "serial",
})
Unit.sudo().create([{
    "product_template_id": p288.id,
    "state": "active",
    "serial_number": "T288-SN-%d" % i,
} for i in range(3)])
err, _v = _try(lambda: p288.write({"tracking_mode": "quantity"}))
ok = err is None and p288.tracking_mode == "quantity"
print("  err:", type(err).__name__ if err else None)
print("  tracking_mode after:", p288.tracking_mode, "(want quantity)")
print("T288:", "PASS" if ok else "FAIL")
results["T288"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T280", "T281", "T282", "T283", "T284", "T285", "T286",
         "T287", "T288"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()  # discard all fixtures
