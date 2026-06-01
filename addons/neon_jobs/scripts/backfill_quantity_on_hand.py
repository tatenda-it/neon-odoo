# -*- coding: utf-8 -*-
"""P-B14c -- Back-fill quantity_on_hand from legacy_qty=N notes.

Reads the unit.notes blob (where the B14b migration parked
'legacy_qty=N' on quantity-mode units) and writes the parsed
integer to product.template.quantity_on_hand. Idempotent: re-runs
on the same data write the same value, no drift.

⚠️ DECISION (B14c, D0): standalone script, NOT in manifest, NOT
imported by addon __init__, NOT cron. Same pattern as B14 /
B14b. Called via odoo shell:
    from odoo.addons.neon_jobs.scripts import \\
        backfill_quantity_on_hand
    backfill_quantity_on_hand.backfill(env)                # dry-run
    backfill_quantity_on_hand.backfill(env, execute=True)  # write

⚠️ DECISION (B14c, D4): the back-fill is the ONLY mechanism that
populates quantity_on_hand on legacy data. New products created
manually after the legacy load get quantity_on_hand from the user
in the form, not from this script. Re-running this script after
manual edits will OVERWRITE manual values with the legacy_qty=N
from notes -- so the back-fill is a ONE-SHOT post-load tool.
A second-run guard (`force=False` by default; `force=True` to
overwrite already-populated values) prevents accidental clobber.
"""
import logging
import re


_logger = logging.getLogger(__name__)


_LEGACY_QTY_RE = re.compile(r"legacy_qty=(\d+)")


def _parse_legacy_qty(notes):
    """Return the legacy_qty integer parsed from a notes blob,
    or None if not present / unparseable."""
    if not notes:
        return None
    m = _LEGACY_QTY_RE.search(notes)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (ValueError, TypeError):
        return None


def backfill(env, execute=False, force=False):
    """Walk quantity/batch products + read legacy_qty=N from their
    unit notes; write product.template.quantity_on_hand. Returns
    a structured report.

    Dry-run by default. `execute=True` writes. `force=True` will
    overwrite an already-populated quantity_on_hand (default is to
    skip products that already have a non-zero value -- prevents
    clobbering manual edits on a second run)."""
    Product = env["product.template"].sudo()
    Unit = env["neon.equipment.unit"].sudo()

    products = Product.search([
        ("is_workshop_item", "=", True),
        ("tracking_mode", "in", ("quantity", "batch")),
    ])

    plan = []
    for product in products:
        # Find a unit with parseable legacy_qty
        units = Unit.search([
            ("product_template_id", "=", product.id),
            ("active", "=", True),
        ])
        # Prefer the FIRST unit with a parseable legacy_qty=N
        # (quantity products canonically have one unit row; if a
        # rogue extra row exists with a different qty, we log it
        # and take the first).
        legacy_qtys = []
        for u in units:
            qty = _parse_legacy_qty(u.notes)
            if qty is not None:
                legacy_qtys.append((u.id, qty))
        entry = {
            "product_id": product.id,
            "workshop_name": product.workshop_name or "",
            "tracking_mode": product.tracking_mode,
            "current_quantity_on_hand": int(
                product.quantity_on_hand or 0),
            "legacy_qtys_seen": legacy_qtys,
            "action": "SKIP",
            "reason": "",
            "new_value": None,
        }
        if not legacy_qtys:
            entry["reason"] = (
                "no unit with legacy_qty=N in notes; left as-is")
            plan.append(entry); continue
        # Disagreement among units: take MAX, log it
        qtys = [q for _, q in legacy_qtys]
        new_value = max(qtys)
        if len(set(qtys)) > 1:
            entry["reason"] = (
                "multiple units disagreed on legacy_qty (%s); "
                "took MAX=%d") % (qtys, new_value)
        # NO-OP path FIRST: if current already matches the
        # legacy value, classify as idempotent NO-OP regardless of
        # force (re-running on already-correct data shouldn't
        # require force=True).
        if entry["current_quantity_on_hand"] == new_value:
            entry["action"] = "NO-OP"
            entry["reason"] = (
                "already at %d -- idempotent no-op") % new_value
            plan.append(entry); continue
        # Else, if current is non-zero and DIFFERS, require force
        # to overwrite (protects manual edits).
        if (entry["current_quantity_on_hand"] > 0
                and not force):
            entry["reason"] = (
                "current quantity_on_hand=%d > 0 -- skipped (use "
                "force=True to overwrite). Legacy says %d.") % (
                    entry["current_quantity_on_hand"], new_value)
            plan.append(entry); continue
        entry["action"] = "WRITE"
        entry["new_value"] = new_value
        if not entry["reason"]:
            entry["reason"] = (
                "set quantity_on_hand=%d from legacy_qty"
            ) % new_value
        plan.append(entry)

    # Execute
    if execute:
        for entry in plan:
            if entry["action"] != "WRITE":
                continue
            product = Product.browse(entry["product_id"])
            try:
                product.write(
                    {"quantity_on_hand": entry["new_value"]})
            except Exception as exc:  # noqa: BLE001
                _logger.exception(
                    "backfill: product %s write failed: %s",
                    entry["product_id"], exc)
                entry["action"] = "FAILED"
                entry["reason"] = "write error: %s: %s" % (
                    type(exc).__name__, exc)

    # Roll up counts
    by_action = {}
    for p in plan:
        by_action[p["action"]] = by_action.get(p["action"], 0) + 1
    return {
        "ok": by_action.get("FAILED", 0) == 0,
        "products_total": len(products),
        "by_action": by_action,
        "plan": plan,
        "dry_run": not execute,
        "force": force,
    }
