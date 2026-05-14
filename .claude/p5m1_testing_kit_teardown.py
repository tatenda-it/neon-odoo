"""P5.M1 — testing kit teardown.

Symmetric removal of the records created by
.claude/p5m1_testing_kit.py:

  * All neon.equipment.unit rows whose product_template_id.name
    contains "[TEST-DELETE]" — unlinked first to clear the
    Many2one references.
  * All product.template rows whose name contains "[TEST-DELETE]"
    AND is_workshop_item=True — unlinked second.

Idempotent — running twice on an already-clean DB reports zero
counts and exits.

INVOCATION
==========
  docker compose exec -T odoo odoo shell -d neon_crm \\
      < .claude/p5m1_testing_kit_teardown.py
"""
MARKER = "[TEST-DELETE]"


print("=" * 72)
print("P5.M1 TESTING KIT TEARDOWN — START")
print("=" * 72)

Product = env["product.template"]
Unit = env["neon.equipment.unit"]

# ---------------------------------------------------------------
# Step 1: count current state
# ---------------------------------------------------------------
products = Product.sudo().search([
    ("name", "ilike", MARKER),
    ("is_workshop_item", "=", True),
])
units = Unit.sudo().search([
    ("product_template_id", "in", products.ids)
])
print("to delete:")
print("  product.template (TEST-DELETE):  %d" % len(products))
print("  neon.equipment.unit (linked):    %d" % len(units))


# ---------------------------------------------------------------
# Step 2: unlink units first (cascade isn't enough — we want
# explicit reporting)
# ---------------------------------------------------------------
unit_count = len(units)
units.unlink()
env.cr.commit()
print()
print("units unlinked: %d" % unit_count)


# ---------------------------------------------------------------
# Step 3: unlink products. ondelete='restrict' on
# neon.equipment.unit.product_template_id means we couldn't
# unlink products with live units; step 2 cleared them, so this
# proceeds cleanly.
# ---------------------------------------------------------------
product_count = len(products)
products.unlink()
env.cr.commit()
print("products unlinked: %d" % product_count)


# ---------------------------------------------------------------
# Step 4: sanity check — zero remaining
# ---------------------------------------------------------------
print()
print("post-teardown state (should both be 0):")
print("  remaining TEST-DELETE products: %d" %
      Product.sudo().search_count([
          ("name", "ilike", MARKER),
          ("is_workshop_item", "=", True),
      ]))
print("  remaining linked units:         %d" %
      Unit.sudo().search_count([
          ("product_template_id.name", "ilike", MARKER),
      ]))

env.cr.commit()
