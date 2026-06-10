# -*- coding: utf-8 -*-
"""P5.M11 post-migrate — quantity-aware reservation engine data fix.

Applies the idempotent cleanup defined on neon.equipment.reservation:
  1) recompute product_template_id on product-less but line/unit-linked
     reservations (the related -> computed-stored switch);
  2) collapse the pre-M11 N-soft_hold pattern on quantity-tracked lines
     into ONE COUNT reservation (quantity=quantity_planned), cancelling
     the extras + releasing any bogus unit binding back to 'active';
  3) cancel true-orphan reservations (no unit AND no line).

The SAME method runs with dry_run=True for the pre-apply prod row report
(via odoo shell) so the exact touched rows are reviewed BEFORE this fires.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    report = env["neon.equipment.reservation"]._p5m11_reservation_cleanup(
        dry_run=False)
    _logger.info(
        "P5.M11 reservation cleanup applied: recompute_product=%s "
        "collapse=%s orphan_cancel=%s",
        report.get("recompute_product"), report.get("collapse"),
        report.get("orphan_cancel"))
