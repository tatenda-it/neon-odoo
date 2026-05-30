# -*- coding: utf-8 -*-
"""P-B14 -- equipment inventory CSV loader.

Idempotent loader for workshop equipment units. Reads a CSV with a
locked column schema, validates every row, classifies as
CREATE / UPDATE / REJECT, and (when execute=True) writes per-row
inside its own savepoint so a single bad row doesn't poison the
batch.

⚠️ DECISION (B14, D2): standalone script, NOT in the manifest, NOT
imported by the addon's __init__. Same shape as the P7e.M13
content migration pattern. Called via:
    docker compose exec -T odoo odoo shell -d neon_crm --no-http \\
        -c "exec(open('/mnt/extra-addons/neon_jobs/scripts/load_inventory.py').read())"
    main('/path/to/inventory.csv', execute=False)

⚠️ DECISION (B14, D3): idempotency key = asset_tag ONLY. Rows
without asset_tag are REJECTED. Forces good data hygiene and uses
the existing SQL UNIQUE constraint as the dedup contract.
NOTE-TO-OPS: bulk quantity-tracked items (cabling drums, truss
segments, mic packs) STILL need a per-unit asset tag in the source
CSV. Lisa should sign off on the tagging convention before the
real load.

⚠️ DECISION (B14, D5): top-level categories REJECT-on-unknown
(the 9 seeded codes are the contract); subcategories + products
AUTO-CREATE because the workshop is currently empty + the team's
CSV is the seed.

⚠️ DECISION (B14, D6): dry_run defaults to True. The execute path
runs only when dry_run=False AND zero rows were rejected (unless
force_with_rejects=True). Each row in the execute pass is wrapped
in its own savepoint -- one bad row rolls back to its savepoint
without poisoning the rest of the batch.
"""
import csv
import logging
import os


_logger = logging.getLogger(__name__)


# Locked CSV column schema (per gate-1 D4).
_REQUIRED_COLUMNS = (
    "asset_tag", "category_code", "workshop_name",
)
_OPTIONAL_COLUMNS = (
    "subcategory_code", "tracking_mode", "serial_number",
    "batch_code", "workshop_location", "condition_status",
    "purchase_date", "purchase_price", "currency",
    "low_stock_threshold", "notes",
)
_ALL_COLUMNS = _REQUIRED_COLUMNS + _OPTIONAL_COLUMNS

_VALID_TRACKING_MODES = ("serial", "quantity", "batch")
_VALID_CONDITIONS = ("good", "needs_repair", "written_off")

# Top-level categories that must already exist (seeded in
# data/neon_equipment_category_data.xml). Subcategories are
# auto-created under one of these.
_SEEDED_CATEGORY_CODES = (
    "sound", "visual", "lighting", "cabling", "laptops",
    "staging", "dance_floor", "effects", "trussing",
)

_SUPERUSER_GROUP = "neon_core.group_neon_superuser"
_MANAGER_GROUP = "neon_jobs.group_neon_jobs_manager"


# ============================================================
# Public API
# ============================================================


def main(csv_path, execute=False, force_with_rejects=False,
         env=None):
    """Entry point. Returns the report dict.

    When called from odoo shell, `env` is the shell's `env`
    global. When called from the @api.model wrapper, the wrapper
    passes its own env.

    Args:
        csv_path: absolute path inside the container.
        execute: False (default) = dry-run; True = real load.
        force_with_rejects: only honoured when execute=True;
            bypass the "zero rejects" guard. Use sparingly.
        env: Odoo Environment object (mandatory; passed in).

    Returns:
        dict (see module docstring).
    """
    if env is None:
        raise RuntimeError(
            "main(env=...) is required. Call from odoo shell.")

    _check_caller_authorized(env)
    _preflight(csv_path)

    rows, hdr_err = _load_rows(csv_path)
    if hdr_err:
        return _final_report(
            csv_path, [], execute=execute,
            preflight_error=hdr_err)

    plan = _build_plan(env, rows)
    has_rejects = any(p["action"] == "REJECT" for p in plan)

    if not execute:
        return _final_report(
            csv_path, plan, execute=False)

    if has_rejects and not force_with_rejects:
        _logger.warning(
            "load_inventory: %s rows rejected; execute aborted "
            "(use force_with_rejects=True to bypass).",
            sum(1 for p in plan if p["action"] == "REJECT"))
        return _final_report(
            csv_path, plan, execute=False,
            blocked_by_rejects=True)

    _execute_plan(env, plan)
    return _final_report(csv_path, plan, execute=True)


# ============================================================
# Authorization + preflight
# ============================================================


def _check_caller_authorized(env):
    if (env.user.has_group(_SUPERUSER_GROUP)
            or env.user.has_group(_MANAGER_GROUP)):
        return
    raise PermissionError(
        "Only Neon Superusers (OD/MD) or jobs Managers may load "
        "inventory. User %s has neither group." % env.user.login)


def _preflight(csv_path):
    if not csv_path or not isinstance(csv_path, str):
        raise ValueError("csv_path must be a non-empty string.")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            "Inventory CSV not found at %s. Path must be readable "
            "by the odoo container -- mount /tmp or place the file "
            "under /mnt/extra-addons/." % csv_path)
    if not os.access(csv_path, os.R_OK):
        raise PermissionError(
            "Inventory CSV at %s is not readable by the odoo "
            "container." % csv_path)


# ============================================================
# CSV parsing
# ============================================================


def _load_rows(csv_path):
    """Read the CSV. Return (rows, header_error_or_None)."""
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            missing = [c for c in _REQUIRED_COLUMNS
                        if c not in headers]
            if missing:
                return ([], (
                    "CSV header missing required columns: %s. "
                    "Expected: %s. Got: %s") % (
                        ", ".join(missing),
                        ", ".join(_REQUIRED_COLUMNS),
                        ", ".join(headers)))
            unknown = [c for c in headers if c not in _ALL_COLUMNS]
            if unknown:
                return ([], (
                    "CSV header has unknown columns: %s. "
                    "Allowed: %s.") % (
                        ", ".join(unknown),
                        ", ".join(_ALL_COLUMNS)))
            rows = [(i + 2, _strip_dict(r))
                    for i, r in enumerate(reader)]
            return (rows, None)
    except UnicodeDecodeError as exc:
        return ([], "CSV is not UTF-8 decodable: " + str(exc))


def _strip_dict(row):
    return {(k or "").strip(): ((v or "").strip()
                                   if isinstance(v, str)
                                   else v)
             for k, v in (row or {}).items()}


# ============================================================
# Plan building
# ============================================================


def _build_plan(env, rows):
    """For each (row_num, row_dict) pair, classify as
    CREATE / UPDATE / REJECT with a structured payload."""
    Cat = env["neon.equipment.category"].sudo()
    Product = env["product.template"].sudo()
    Unit = env["neon.equipment.unit"].sudo()

    seen_asset_tags_this_run = set()
    plan = []
    for row_num, row in rows:
        entry = {
            "row": row_num,
            "asset_tag": row.get("asset_tag", ""),
            "action": "REJECT", "reason": "",
            "row_data": row,
            "resolved_category_id": 0,
            "resolved_product_id": 0,
            "existing_unit_id": 0,
        }
        # Sequential validation: each failure short-circuits with
        # a clear reason.
        if not entry["asset_tag"]:
            entry["reason"] = (
                "no asset_tag (idempotency key required per B14 D3 "
                "-- assign one in the source CSV)")
            plan.append(entry); continue
        if entry["asset_tag"] in seen_asset_tags_this_run:
            entry["reason"] = (
                "asset_tag %r duplicated within this CSV "
                "(rows must be unique)") % entry["asset_tag"]
            plan.append(entry); continue
        seen_asset_tags_this_run.add(entry["asset_tag"])

        # Required fields
        if not row.get("category_code"):
            entry["reason"] = "category_code is required"
            plan.append(entry); continue
        if not row.get("workshop_name"):
            entry["reason"] = "workshop_name is required"
            plan.append(entry); continue

        # Category resolution (top-level)
        cat_code = row["category_code"]
        if cat_code not in _SEEDED_CATEGORY_CODES:
            entry["reason"] = (
                "unknown category_code %r -- must be one of: %s "
                "(top-level categories reject-on-unknown per B14 D5)"
            ) % (cat_code, ", ".join(_SEEDED_CATEGORY_CODES))
            plan.append(entry); continue
        top_cat = Cat.search([("code", "=", cat_code)], limit=1)
        if not top_cat:
            entry["reason"] = (
                "seeded category %r not in DB -- run -u neon_jobs "
                "to re-load category seed") % cat_code
            plan.append(entry); continue

        # Subcategory (auto-create per D5)
        resolved_cat = top_cat
        sub_code = row.get("subcategory_code") or ""
        if sub_code:
            sub_cat = Cat.search(
                [("code", "=", sub_code)], limit=1)
            if sub_cat:
                if sub_cat.parent_id and sub_cat.parent_id != top_cat:
                    entry["reason"] = (
                        "subcategory %r exists but its parent is "
                        "%r, not %r") % (
                            sub_code, sub_cat.parent_id.code,
                            cat_code)
                    plan.append(entry); continue
                resolved_cat = sub_cat
            else:
                # AUTO-CREATE deferred to execute pass; plan
                # records the intent.
                entry["create_subcategory"] = {
                    "code": sub_code,
                    "name": _humanize(sub_code),
                    "parent_code": cat_code,
                    "default_tracking": top_cat.default_tracking,
                }
                resolved_cat = None  # filled in at execute

        # Tracking mode resolution
        tm = (row.get("tracking_mode")
              or (resolved_cat or top_cat).default_tracking
              or "serial")
        if tm not in _VALID_TRACKING_MODES:
            entry["reason"] = (
                "tracking_mode %r invalid -- must be one of %s"
            ) % (tm, ", ".join(_VALID_TRACKING_MODES))
            plan.append(entry); continue
        if tm == "serial" and not row.get("serial_number"):
            entry["reason"] = (
                "tracking_mode='serial' requires serial_number")
            plan.append(entry); continue
        if tm == "batch" and not row.get("batch_code"):
            entry["reason"] = (
                "tracking_mode='batch' requires batch_code")
            plan.append(entry); continue

        # Condition + threshold + numeric fields
        cond = (row.get("condition_status") or "good").lower()
        if cond not in _VALID_CONDITIONS:
            entry["reason"] = (
                "condition_status %r invalid -- must be one of %s"
            ) % (cond, ", ".join(_VALID_CONDITIONS))
            plan.append(entry); continue
        entry["resolved_condition"] = cond

        thr = row.get("low_stock_threshold") or ""
        if thr:
            try:
                entry["resolved_threshold"] = int(thr)
                if entry["resolved_threshold"] < 0:
                    entry["reason"] = (
                        "low_stock_threshold cannot be negative")
                    plan.append(entry); continue
            except ValueError:
                entry["reason"] = (
                    "low_stock_threshold %r is not an integer"
                ) % thr
                plan.append(entry); continue
        purchase_price = row.get("purchase_price") or ""
        if purchase_price:
            try:
                entry["resolved_price"] = float(purchase_price)
                if entry["resolved_price"] < 0:
                    entry["reason"] = (
                        "purchase_price cannot be negative")
                    plan.append(entry); continue
            except ValueError:
                entry["reason"] = (
                    "purchase_price %r is not numeric"
                ) % purchase_price
                plan.append(entry); continue
        # purchase_date format (ISO yyyy-mm-dd)
        pd = row.get("purchase_date") or ""
        if pd:
            try:
                from datetime import date as _date
                _date.fromisoformat(pd)
                entry["resolved_purchase_date"] = pd
            except ValueError:
                entry["reason"] = (
                    "purchase_date %r is not ISO yyyy-mm-dd"
                ) % pd
                plan.append(entry); continue

        # Product resolution / auto-create intent
        # Look up by (resolved_cat, workshop_name) -- if cat is
        # being created, defer to execute pass.
        if resolved_cat:
            existing_product = Product.search([
                ("equipment_category_id", "=", resolved_cat.id),
                ("workshop_name", "=", row["workshop_name"]),
                ("is_workshop_item", "=", True),
            ], limit=1)
            if existing_product:
                entry["resolved_product_id"] = existing_product.id
            else:
                entry["create_product"] = {
                    "workshop_name": row["workshop_name"],
                    "tracking_mode": tm,
                }
            entry["resolved_category_id"] = resolved_cat.id
            entry["resolved_tracking_mode"] = tm
        else:
            # Subcategory create deferred -- product create
            # deferred too
            entry["create_product"] = {
                "workshop_name": row["workshop_name"],
                "tracking_mode": tm,
            }
            entry["resolved_tracking_mode"] = tm

        # Existing unit lookup by asset_tag
        existing_unit = Unit.search(
            [("asset_tag", "=", entry["asset_tag"])], limit=1)
        if existing_unit:
            entry["existing_unit_id"] = existing_unit.id
            entry["action"] = "UPDATE"
            entry["reason"] = (
                "asset_tag matches existing unit id=%s -- update "
                "mapped fields"
            ) % existing_unit.id
        else:
            entry["action"] = "CREATE"
            entry["reason"] = "new asset_tag -- create unit"
        plan.append(entry)
    return plan


# ============================================================
# Execute pass
# ============================================================


def _execute_plan(env, plan):
    """Walk the plan and apply CREATE / UPDATE per row. Each row
    is wrapped in its own savepoint so a single row failure does
    not roll back the batch."""
    Cat = env["neon.equipment.category"].sudo()
    Product = env["product.template"].sudo()
    Unit = env["neon.equipment.unit"].sudo()

    for entry in plan:
        if entry["action"] == "REJECT":
            continue
        try:
            with env.cr.savepoint():
                _apply_row(env, Cat, Product, Unit, entry)
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "load_inventory: row %s (asset_tag=%s) failed: %s",
                entry["row"], entry["asset_tag"], exc)
            entry["action"] = "FAILED"
            entry["reason"] = "execute error: %s: %s" % (
                type(exc).__name__, exc)


def _apply_row(env, Cat, Product, Unit, entry):
    row = entry["row_data"]
    # Resolve / create subcategory if planned. RE-CHECK whether
    # the subcategory now exists -- a prior row in this same
    # execute pass may have created it, in which case we reuse
    # instead of hitting the UNIQUE(code) constraint.
    cat_id = entry.get("resolved_category_id") or 0
    if not cat_id and entry.get("create_subcategory"):
        sub_meta = entry["create_subcategory"]
        existing_sub = Cat.search(
            [("code", "=", sub_meta["code"])], limit=1)
        if existing_sub:
            cat_id = existing_sub.id
        else:
            parent = Cat.search(
                [("code", "=", sub_meta["parent_code"])], limit=1)
            new_cat = Cat.create({
                "code": sub_meta["code"],
                "name": sub_meta["name"],
                "parent_id": parent.id,
                "default_tracking": sub_meta["default_tracking"],
            })
            cat_id = new_cat.id
        entry["resolved_category_id"] = cat_id
    if not cat_id:
        raise ValueError(
            "Internal: no category resolved for row %s"
            % entry["row"])

    # Resolve / create product
    product_id = entry.get("resolved_product_id") or 0
    if not product_id:
        # Re-check (the subcategory may have just been created)
        product = Product.search([
            ("equipment_category_id", "=", cat_id),
            ("workshop_name", "=", row["workshop_name"]),
            ("is_workshop_item", "=", True),
        ], limit=1)
        if product:
            product_id = product.id
        else:
            create_meta = entry["create_product"]
            new_product = Product.create({
                "name": create_meta["workshop_name"],
                "workshop_name": create_meta["workshop_name"],
                "is_workshop_item": True,
                "equipment_category_id": cat_id,
                "tracking_mode": create_meta["tracking_mode"],
                "type": "consu",
            })
            product_id = new_product.id
        entry["resolved_product_id"] = product_id

    # Build the unit vals
    vals = {
        "product_template_id": product_id,
        "asset_tag": entry["asset_tag"],
        "condition_status": entry["resolved_condition"],
    }
    if row.get("serial_number"):
        vals["serial_number"] = row["serial_number"]
    if row.get("batch_code"):
        vals["batch_code"] = row["batch_code"]
    if row.get("workshop_location"):
        vals["workshop_location"] = row["workshop_location"]
    if row.get("notes"):
        vals["notes"] = row["notes"]
    if "resolved_price" in entry:
        vals["purchase_price"] = entry["resolved_price"]
    if "resolved_purchase_date" in entry:
        vals["purchase_date"] = entry["resolved_purchase_date"]

    if entry["existing_unit_id"]:
        unit = Unit.browse(entry["existing_unit_id"])
        # Don't touch serial_number on UPDATE -- the SQL constraint
        # on (product, serial) would fire if we re-assigned.
        vals.pop("serial_number", None)
        # Bypass the state-machine readonly guard.
        unit.with_context(_allow_state_write=True).write(vals)
    else:
        new_unit = Unit.create(vals)
        entry["existing_unit_id"] = new_unit.id

    # Threshold writes to the CATEGORY (B1 field)
    if "resolved_threshold" in entry:
        cat_rec = Cat.browse(cat_id)
        if cat_rec.low_stock_threshold != entry["resolved_threshold"]:
            cat_rec.write({
                "low_stock_threshold":
                    entry["resolved_threshold"]})


# ============================================================
# Reporting
# ============================================================


def _final_report(csv_path, plan, execute, preflight_error=None,
                   blocked_by_rejects=False):
    if preflight_error:
        return {
            "ok": False,
            "csv_path": csv_path,
            "preflight_error": preflight_error,
            "rows_total": 0,
            "rows_create": 0, "rows_update": 0,
            "rows_skip": 0, "rows_reject": 0,
            "rows_failed": 0,
            "report": [],
            "dry_run": not execute,
        }
    cnt = {"CREATE": 0, "UPDATE": 0, "REJECT": 0,
           "SKIP": 0, "FAILED": 0}
    for p in plan:
        cnt[p["action"]] = cnt.get(p["action"], 0) + 1
    return {
        "ok": (cnt["REJECT"] == 0 and cnt["FAILED"] == 0),
        "csv_path": csv_path,
        "rows_total": len(plan),
        "rows_create": cnt["CREATE"],
        "rows_update": cnt["UPDATE"],
        "rows_skip": cnt["SKIP"],
        "rows_reject": cnt["REJECT"],
        "rows_failed": cnt["FAILED"],
        "blocked_by_rejects": blocked_by_rejects,
        "report": [{
            "row": p["row"],
            "asset_tag": p["asset_tag"],
            "action": p["action"],
            "reason": p["reason"],
            "unit_id": p.get("existing_unit_id") or None,
        } for p in plan],
        "dry_run": not execute,
    }


def _humanize(code):
    """wireless_mics -> Wireless Mics."""
    return " ".join(
        w.capitalize() for w in (code or "").replace("-", "_")
                                            .split("_") if w)
