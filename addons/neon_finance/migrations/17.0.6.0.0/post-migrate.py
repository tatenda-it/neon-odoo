# -*- coding: utf-8 -*-
"""
P6.M1 — backfill cost_strategy + auto-create day_multiplier rows.

Fires on the version jump 17.0.1.5.0 -> 17.0.6.0.0 when this
migration's directory version lands in the (old, new] range.

Two pieces:

1. cost_strategy: Odoo's ORM applies the column default
   ('owned_zero') when adding the new column to neon_equipment_category
   during the upgrade DDL pass. The explicit UPDATE here is a
   belt-and-braces guard so any row that landed with NULL — for
   example if the field default lookup raced with the data load —
   gets set deterministically.

2. day_multiplier: the override in
   addons/neon_finance/models/neon_equipment_category.py auto-spawns
   a multiplier row for every NEW category create. Existing
   categories on the upgrading database do not pass through create()
   on -u, so we seed them here. Idempotent: only inserts when no
   multiplier row exists for the category.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1. cost_strategy backfill (defensive).
    cr.execute("""
        UPDATE neon_equipment_category
           SET cost_strategy = 'owned_zero'
         WHERE cost_strategy IS NULL
    """)
    if cr.rowcount:
        _logger.info(
            "P6.M1 post-migrate: set cost_strategy='owned_zero' on "
            "%d category rows that were NULL.", cr.rowcount)

    # 2. day_multiplier seed for existing categories.
    Category = env["neon.equipment.category"].sudo()
    DayMultiplier = env["neon.finance.day.multiplier"].sudo()
    categories = Category.search([])
    seeded = 0
    skipped = 0
    for cat in categories:
        existing = DayMultiplier.search_count(
            [("category_id", "=", cat.id)])
        if existing:
            skipped += 1
            continue
        DayMultiplier.create({"category_id": cat.id})
        seeded += 1
    _logger.info(
        "P6.M1 post-migrate: day_multiplier seed — %d created, "
        "%d already present (skipped).", seeded, skipped)
