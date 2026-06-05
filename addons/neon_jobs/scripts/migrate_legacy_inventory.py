# -*- coding: utf-8 -*-
"""P-B14b -- Legacy workshop inventory migration.

Reads the legacy MySQL `equipment` table (exported as SQL dump from
neoneybb_workshop) and feeds it into B14's load_inventory.py via an
on-the-fly generated CSV. Dry-run default; same dry-run -> review ->
execute discipline as B14.

⚠️ DECISION (B14b, D0): standalone script, NOT in manifest, NOT
imported by addon __init__. Reuses B14's load_inventory module
in-process via `from ... import load_inventory`. Same shape as the
B14 + P7e.M13 standalone-loader pattern.

⚠️ DECISION (B14b, D1 -- interpretation note): the Phase-5 spec
says "QUANTITY items: ONE row carrying a quantity/count -- NOT N
tagged rows". The model neon.equipment.unit has NO count field
(no `quantity_on_hand` etc.) so the literal "1 row carrying
count" semantics yield a single unit row whose count is lost
(stored in notes for traceability). Downstream B2 reads
`len(units)` as available_qty -- a quantity-product loaded this
way will report available_qty=1 regardless of legacy
total_quantity. Future B1/B2 enhancement needed to wire the count
through; B14b ships the loader+migration WITHOUT touching B1/B2
per spec.

⚠️ DECISION (B14b, D2 -- asset_tag generation): SERIAL rows get
their asset_tag from legacy `serial_number` when present, else
auto-generated as `<CAT>-<SLUG>-<legacy_id>` (stable, idempotent
across re-runs). QUANTITY rows have no asset_tag (loader extension
D3-v2). Vehicles + archived rows are SKIPPED.

⚠️ DECISION (B14b, D3 -- condition mapping): legacy `status` !=
'Available' OR `qty_damaged` > 0 maps to condition_status =
'needs_repair'. We NEVER infer 'written_off' from legacy data --
write-off is a deliberate decommissioning act, not a status flag.

⚠️ DECISION (B14b, D4 -- threshold): legacy `min_stock_threshold`
writes to the CATEGORY low_stock_threshold (B1 field on category,
not unit). If multiple legacy rows in the same category disagree,
take MAX (conservative; nobody gets a smaller alert).

⚠️ DECISION (B14b, D5 -- supplier): legacy `supplier_name` is
stored in unit notes only (informational). DO NOT auto-create
res.partner -- supplier creation is a human/OD action.

⚠️ DECISION (B14b, D6 -- vehicles): legacy `equipment_group =
'Vehicles'` is SKIPPED. Vehicles are R3a fleet, not workshop.
Reported in dry-run.

⚠️ DECISION (B14b, D7 -- archived): `archived=1` rows are SKIPPED.
Retired gear stays retired.
"""
import logging
import os
import re
import sys
import tempfile
import csv


_logger = logging.getLogger(__name__)


# ============================================================
# Locked mappings (do NOT auto-decide)
# ============================================================
_CATEGORY_MAP = {
    "Sound": "sound",
    "Visual": "visual",
    "Lighting": "lighting",
    "Cabling and Accessories": "cabling",
    "Laptops": "laptops",
    "Staging": "staging",
    "Dance Floor": "dance_floor",
    "Effects": "effects",
    "Trussing": "trussing",
    # "Vehicles" -> SKIP (per B14b D6)
}

_SKIP_VEHICLES = "Vehicles"

_CSV_HEADER = [
    "asset_tag", "category_code", "workshop_name",
    "subcategory_code", "tracking_mode", "serial_number",
    "batch_code", "workshop_location", "condition_status",
    "purchase_date", "purchase_price", "currency",
    "low_stock_threshold", "notes",
]


# ============================================================
# SQL parser -- limited to `equipment` INSERT VALUES tuples
# ============================================================
_INSERT_HEADER_RE = re.compile(
    r"^INSERT INTO `equipment`\s*\(([^)]+)\)\s*VALUES",
    re.IGNORECASE | re.MULTILINE)


def _parse_sql_dump(sql_path):
    """Return list of dicts: one per legacy equipment row.

    Robust against multi-line VALUES blocks. Skips any other table's
    INSERTs defensively (we extract equipment-only upstream but a
    belt-and-braces filter here protects against accidental wider
    dumps).
    """
    if not os.path.isfile(sql_path):
        raise FileNotFoundError(
            "Legacy SQL file not found: %s" % sql_path)
    with open(sql_path, "r", encoding="utf-8",
                errors="replace") as f:
        text = f.read()
    # Defensive: refuse the dump if it contains a users INSERT --
    # B14b is equipment-only; users with password hashes must NEVER
    # be touched.
    if re.search(r"INSERT INTO `users`", text, re.IGNORECASE):
        raise ValueError(
            "Legacy SQL contains an `users` INSERT -- B14b is "
            "equipment-only; sensitive data must be filtered out "
            "upstream before passing to this script.")
    header_match = _INSERT_HEADER_RE.search(text)
    if not header_match:
        raise ValueError(
            "No INSERT INTO `equipment` (...) VALUES found in "
            "%s -- is this the right file?" % sql_path)
    columns = [c.strip().strip("`")
                for c in header_match.group(1).split(",")]
    rows = []
    # Find every VALUES tuple across every INSERT block.
    for insert_match in re.finditer(
            r"INSERT INTO `equipment`\s*\([^)]+\)\s*VALUES\s*"
            r"(.+?);", text, re.DOTALL | re.IGNORECASE):
        values_blob = insert_match.group(1)
        for tup in _split_tuples(values_blob):
            parsed = _parse_tuple(tup)
            if len(parsed) != len(columns):
                _logger.warning(
                    "Skipping malformed tuple (got %d cols, "
                    "expected %d): %s",
                    len(parsed), len(columns), tup[:80])
                continue
            rows.append(dict(zip(columns, parsed)))
    return rows


def _split_tuples(blob):
    """Split a VALUES blob `(a,b), (c,d), ...` into individual
    tuple strings (without the outer parens). Respects quoted
    strings + escaped quotes."""
    tuples = []
    depth = 0
    in_str = False
    cur = []
    i = 0
    while i < len(blob):
        ch = blob[i]
        if in_str:
            cur.append(ch)
            if ch == "\\" and i + 1 < len(blob):
                # MySQL escape -- consume the next char verbatim
                cur.append(blob[i + 1])
                i += 2
                continue
            if ch == "'":
                in_str = False
        else:
            if ch == "'":
                in_str = True
                cur.append(ch)
            elif ch == "(":
                if depth == 0:
                    cur = []  # reset for this tuple
                else:
                    cur.append(ch)
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    tuples.append("".join(cur))
                    cur = []
                else:
                    cur.append(ch)
            else:
                cur.append(ch)
        i += 1
    return tuples


def _parse_tuple(tup):
    """Parse a single VALUES tuple body into Python primitives."""
    out = []
    cur = []
    in_str = False
    i = 0
    while i < len(tup):
        ch = tup[i]
        if in_str:
            if ch == "\\" and i + 1 < len(tup):
                cur.append(tup[i + 1])
                i += 2
                continue
            if ch == "'":
                in_str = False
            else:
                cur.append(ch)
        else:
            if ch == "'":
                in_str = True
            elif ch == ",":
                out.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
        i += 1
    if cur:
        out.append("".join(cur).strip())
    # Normalize NULL -> "" (CSV-empty)
    return [("" if v.upper() == "NULL" else v) for v in out]


# ============================================================
# Classification + CSV generation
# ============================================================
_SLUG_RE = re.compile(r"[^A-Z0-9]+")


def _slugify(text):
    """ALL-CAPS underscore slug, e.g. 'P10 SUBS' -> 'P10_SUBS'."""
    if not text:
        return "X"
    return _SLUG_RE.sub("_", text.upper()).strip("_")[:40] or "X"


def _classify_row(row):
    """Return (action, csv_row_or_None, reason). action in
    CREATE-serial-unit / CREATE-quantity-row / SKIP-archived /
    SKIP-vehicle / REJECT(reason)."""
    legacy_id = row.get("id") or ""
    group = (row.get("equipment_group") or "").strip()
    archived = (row.get("archived") or "0") == "1"
    is_serial = (row.get("is_serialized") or "0") == "1"
    official = (row.get("official_name") or "").strip()
    workshop = (row.get("workshop_name") or "").strip() or official
    serial_no = (row.get("serial_number") or "").strip()
    total_qty = row.get("total_quantity") or "0"
    qty_damaged = row.get("qty_damaged") or "0"
    status = (row.get("status") or "").strip()
    location = (row.get("location") or "").strip()
    supplier = (row.get("supplier_name") or "").strip()
    purchase_date = (row.get("purchase_date") or "").strip()
    purchase_price = (row.get("unit_cost")
                       or row.get("replacement_value") or "")
    min_threshold = row.get("min_stock_threshold") or ""

    if not official and not workshop:
        return ("REJECT", None,
                "missing both official_name and workshop_name "
                "(legacy id=%s) -- not a usable row" % legacy_id)

    if archived:
        return ("SKIP-archived", None,
                "archived=1 (legacy id=%s, %r)" % (legacy_id,
                                                      workshop))

    if group == _SKIP_VEHICLES:
        return ("SKIP-vehicle", None,
                "Vehicles group -> R3a fleet, not workshop "
                "(legacy id=%s, %r)" % (legacy_id, workshop))

    if group not in _CATEGORY_MAP:
        return ("REJECT", None,
                "unknown equipment_group %r (legacy id=%s) -- "
                "not in B14b category map" % (group, legacy_id))
    cat_code = _CATEGORY_MAP[group]

    # Condition mapping (B14b D3): qty_damaged>0 OR
    # status != 'Available' -> needs_repair
    cond = "good"
    try:
        if int(qty_damaged or "0") > 0:
            cond = "needs_repair"
    except (ValueError, TypeError):
        pass
    if status and status.lower() not in ("available", ""):
        cond = "needs_repair"

    # Notes block: keep legacy traceability + supplier (no auto-
    # create per B14b D5) + total_quantity (lost in the per-row
    # model -- see B14b D1).
    note_parts = ["legacy_id=" + str(legacy_id)]
    try:
        if int(total_qty) > 1:
            note_parts.append("legacy_qty=" + str(total_qty))
    except (ValueError, TypeError):
        pass
    if supplier:
        note_parts.append("legacy_supplier=" + supplier)
    if status and status.lower() != "available":
        note_parts.append("legacy_status=" + status)
    notes_str = "; ".join(note_parts)

    # purchase_date may be the literal '0000-00-00' on some legacy
    # rows -- B14 loader will REJECT non-ISO. Filter.
    if purchase_date in ("0000-00-00", "0000-00-00 00:00:00"):
        purchase_date = ""

    # CSV row template
    csv_row = {
        "asset_tag": "",
        "category_code": cat_code,
        "workshop_name": workshop,
        "subcategory_code": "",
        "tracking_mode": "",
        "serial_number": "",
        "batch_code": "",
        "workshop_location": location,
        "condition_status": cond,
        "purchase_date": purchase_date,
        "purchase_price": purchase_price,
        "currency": "",
        "low_stock_threshold": min_threshold,
        "notes": notes_str,
    }

    if is_serial or serial_no:
        # SERIAL path -- 1 row per legacy unit. asset_tag from
        # legacy serial if present, else generated stable key.
        csv_row["tracking_mode"] = "serial"
        if serial_no:
            csv_row["serial_number"] = serial_no
            csv_row["asset_tag"] = serial_no
        else:
            # Serial-required without legacy serial -- generate
            # placeholder serial too (the loader rejects serial
            # rows missing serial_number).
            stub = "%s-%s-S%s" % (
                cat_code.upper(), _slugify(workshop), legacy_id)
            csv_row["serial_number"] = stub
            csv_row["asset_tag"] = stub
        return ("CREATE-serial-unit", csv_row, "")
    else:
        # QUANTITY path -- 1 row, NO asset_tag, NO serial.
        # Idempotency = (product, no asset_tag, no serial) per
        # the B14 loader's B14b D3-v2 extension.
        csv_row["tracking_mode"] = "quantity"
        return ("CREATE-quantity-row", csv_row, "")


def _generate_csv(legacy_rows):
    """Walk the legacy rows, classify each, and build the staging
    CSV + the classification report."""
    classified = []
    csv_rows = []
    for legacy in legacy_rows:
        action, csv_row, reason = _classify_row(legacy)
        classified.append({
            "legacy_id": legacy.get("id") or "",
            "group": legacy.get("equipment_group") or "",
            "official_name": legacy.get("official_name") or "",
            "workshop_name": (legacy.get("workshop_name")
                                or legacy.get("official_name")
                                or ""),
            "action": action,
            "reason": reason,
        })
        if csv_row is not None:
            csv_rows.append(csv_row)
    return classified, csv_rows


def _write_staging_csv(csv_rows, csv_path):
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_HEADER)
        writer.writeheader()
        for r in csv_rows:
            writer.writerow(r)


# ============================================================
# Public entry point
# ============================================================
def migrate(env, sql_path=None, execute=False,
              keep_staging_csv=False):
    """Run the legacy migration. Dry-run by default.

    sql_path defaults to <addon>/scripts/legacy_workshop_equipment.sql
    -- the safe extract written by the relay (never the raw dump
    which contains the users table).
    """
    if sql_path is None:
        sql_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "legacy_workshop_equipment.sql")
    legacy_rows = _parse_sql_dump(sql_path)
    classified, csv_rows = _generate_csv(legacy_rows)
    # Per-category breakdown (counts PRODUCT rows = legacy rows)
    by_cat = {}
    by_action = {}
    for c in classified:
        by_action[c["action"]] = by_action.get(c["action"], 0) + 1
        if c["action"] not in ("SKIP-vehicle", "SKIP-archived",
                                 "REJECT"):
            g = c["group"]
            by_cat[g] = by_cat.get(g, 0) + 1

    # Lazy import to keep migrate_legacy_inventory.py loadable in
    # contexts where load_inventory hasn't been imported yet.
    from . import load_inventory  # noqa: E402

    loader_report = {"skipped_loader": True,
                       "reason": "no csv_rows to load"}
    staging_csv_path = None
    if csv_rows:
        if keep_staging_csv:
            staging_csv_path = os.path.join(
                tempfile.gettempdir(),
                "b14b_staging.csv")
        else:
            staging_csv_path = os.path.join(
                tempfile.gettempdir(),
                "b14b_staging_dryrun.csv")
        _write_staging_csv(csv_rows, staging_csv_path)
        loader_report = load_inventory.main(
            staging_csv_path, execute=execute, env=env)

    return {
        "ok": loader_report.get("ok", True)
                and by_action.get("REJECT", 0) == 0,
        "sql_path": sql_path,
        "staging_csv_path": staging_csv_path,
        "legacy_row_count": len(legacy_rows),
        "csv_row_count": len(csv_rows),
        "classification_by_action": by_action,
        "classification_by_category": by_cat,
        "classification_detail": classified,
        "loader_report": loader_report,
        "dry_run": not execute,
    }
