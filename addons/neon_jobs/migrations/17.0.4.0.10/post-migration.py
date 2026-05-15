# -*- coding: utf-8 -*-
"""P5.M8 — seed is_high_impact on the 9 workshop categories.

Runs on -u when the addon version bumps to 17.0.4.0.10. Idempotent
via the WHERE clause: only flips False → True on the four seeded
codes; if a manager has already toggled a category, the existing
value survives.
"""


def migrate(cr, version):
    if version is None:
        # Fresh install path is handled by the addon's normal data
        # load (the field default is False; install seeds happen via
        # post_init_hook on a separate code path if needed). This
        # migration is for the -u-from-prior-version case.
        return
    cr.execute("""
        UPDATE neon_equipment_category
           SET is_high_impact = TRUE
         WHERE code IN ('sound', 'visual', 'lighting', 'laptops')
           AND is_high_impact = FALSE
    """)
