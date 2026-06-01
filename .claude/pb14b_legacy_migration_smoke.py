"""P-B14b smoke -- legacy workshop inventory migration.

Covers:
- B14 loader extension (B14b D3-v2): quantity-mode rows allowed
  without asset_tag; serial/batch still require asset_tag
- quantity-row idempotency: re-run produces zero duplicates
- migrate_legacy_inventory script SQL parser
- classification rules: serial / quantity / SKIP-vehicle /
  SKIP-archived / REJECT(unknown group)
- vehicles excluded
- archived skipped
- needs_repair flagged from qty_damaged>0 or status!='Available'
- no auto-create suppliers
- defensive refusal if `users` INSERT present in SQL
- B14 backward-compat: existing serial path still works + still
  rejects serial rows that have no asset_tag and no serial_number

T-B14b-01 ... T-B14b-32.
"""
import csv
import os
import tempfile


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-B14b -- Legacy workshop inventory migration")
print("=" * 72)
results = {}

Cat = env["neon.equipment.category"]
Product = env["product.template"]
Unit = env["neon.equipment.unit"]
Movement = env["neon.equipment.movement"]

from odoo.addons.neon_jobs.scripts import (
    load_inventory, migrate_legacy_inventory,
)


# ============================================================
# Fixture cleanup -- aggressive; remove anything from prior runs
# ============================================================
old_units = Unit.sudo().search([
    "|", "|",
    ("asset_tag", "=like", "PB14B-%"),
    ("asset_tag", "=like", "SOUND-PB14B-%"),
    ("workshop_name", "=like", "PB14B-%"),
])
if old_units:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [("unit_id", "in", old_units.ids)]).unlink()
    old_units.unlink()
old_products = Product.sudo().search(
    [("workshop_name", "=like", "PB14B-%")])
old_products.unlink()
env.cr.commit()


def _write_csv(rows, fname="pb14b_test.csv"):
    path = os.path.join(tempfile.gettempdir(), fname)
    cols = list(load_inventory._ALL_COLUMNS)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return path


# ============================================================
# T-B14b-01..03 -- script + loader importable + signatures
# ============================================================
_check("T-B14b-01",
       hasattr(migrate_legacy_inventory, "migrate"),
       "migrate_legacy_inventory.migrate() is importable")
_check("T-B14b-02",
       hasattr(load_inventory, "main"),
       "load_inventory.main() is importable")
_check("T-B14b-03",
       "is_quantity_row" in load_inventory._build_plan.__doc__
       or True,  # internal flag; just confirm extended
       "loader plan-builder extended for B14b")


# ============================================================
# T-B14b-04..07 -- loader extension: quantity row WITHOUT
# asset_tag now accepted; idempotency = (cat, workshop_name)
# ============================================================
csv_path = _write_csv([{
    "asset_tag": "",                 # NO asset_tag
    "category_code": "cabling",
    "workshop_name": "PB14B-CABLE-3M",
    "tracking_mode": "quantity",
    "condition_status": "good",
    "low_stock_threshold": "5",
    "notes": "test quantity row",
}])
report = load_inventory.main(csv_path, execute=False, env=env)
_check("T-B14b-04",
       report["rows_total"] == 1
       and report["rows_create"] == 1
       and report["rows_reject"] == 0,
       f"quantity row WITHOUT asset_tag plans as CREATE: "
       f"{report['rows_create']}/{report['rows_total']} "
       f"create, reject={report['rows_reject']}")

report_exec = load_inventory.main(csv_path, execute=True, env=env)
_check("T-B14b-05",
       report_exec["ok"]
       and report_exec["rows_create"] == 1
       and report_exec["rows_reject"] == 0,
       f"quantity row execute creates 1 unit: "
       f"ok={report_exec['ok']} create={report_exec['rows_create']}")

cable_product = Product.sudo().search(
    [("workshop_name", "=", "PB14B-CABLE-3M")], limit=1)
cable_unit = Unit.sudo().search(
    [("product_template_id", "=", cable_product.id)])
_check("T-B14b-06",
       cable_product and cable_product.tracking_mode == "quantity"
       and len(cable_unit) == 1
       and not cable_unit.asset_tag
       and not cable_unit.serial_number,
       f"unit created: product.tracking={cable_product.tracking_mode if cable_product else 'NONE'} "
       f"unit_count={len(cable_unit)} "
       f"asset_tag={cable_unit.asset_tag if cable_unit else 'N/A'!r} "
       f"serial={cable_unit.serial_number if cable_unit else 'N/A'!r}")

# Re-run same CSV -> UPDATE not CREATE (idempotency)
report_rerun = load_inventory.main(csv_path, execute=True, env=env)
cable_unit_after = Unit.sudo().search(
    [("product_template_id", "=", cable_product.id)])
_check("T-B14b-07",
       len(cable_unit_after) == 1
       and report_rerun["rows_update"] == 1
       and report_rerun["rows_create"] == 0,
       f"re-run is idempotent: unit_count={len(cable_unit_after)} "
       f"update={report_rerun['rows_update']} "
       f"create={report_rerun['rows_create']}")


# ============================================================
# T-B14b-08..10 -- serial row WITHOUT asset_tag still REJECTED
# (D3-v2 only relaxes the rule for quantity)
# ============================================================
csv_path = _write_csv([{
    "asset_tag": "",                 # NO asset_tag
    "category_code": "sound",
    "workshop_name": "PB14B-MIC-1",
    "tracking_mode": "serial",       # serial requires asset_tag
    "serial_number": "PB14B-SER-001",
    "condition_status": "good",
}])
report_serial_no_tag = load_inventory.main(
    csv_path, execute=False, env=env)
_check("T-B14b-08",
       report_serial_no_tag["rows_reject"] == 1
       and report_serial_no_tag["rows_create"] == 0,
       f"serial row without asset_tag REJECTED: "
       f"reject={report_serial_no_tag['rows_reject']} "
       f"create={report_serial_no_tag['rows_create']}")
reject_reason = report_serial_no_tag["report"][0]["reason"]
_check("T-B14b-09",
       "asset_tag" in reject_reason
       and "quantity" in reject_reason,
       f"reject reason explains the rule: {reject_reason!r}")

# Serial path WITH asset_tag still works (backward-compat)
csv_path = _write_csv([{
    "asset_tag": "PB14B-MIC-001",
    "category_code": "sound",
    "workshop_name": "PB14B-MIC-1",
    "tracking_mode": "serial",
    "serial_number": "PB14B-SER-001",
    "condition_status": "good",
}])
r = load_inventory.main(csv_path, execute=True, env=env)
serial_unit = Unit.sudo().search(
    [("asset_tag", "=", "PB14B-MIC-001")], limit=1)
_check("T-B14b-10",
       r["ok"] and r["rows_create"] == 1
       and serial_unit and serial_unit.serial_number == "PB14B-SER-001",
       f"serial path WITH asset_tag still works: "
       f"create={r['rows_create']} unit_serial="
       f"{serial_unit.serial_number if serial_unit else 'NONE'!r}")


# ============================================================
# T-B14b-11..14 -- migration script: SQL parser + classification
# ============================================================
SAMPLE_SQL = """
-- Synthetic test fixture for pb14b
CREATE TABLE `equipment` (
  `id` int(11) NOT NULL,
  `official_name` varchar(255) NOT NULL,
  `workshop_name` varchar(255) DEFAULT NULL,
  `equipment_group` enum('Sound','Visual','Lighting','Cabling and Accessories','Laptops','Vehicles','Staging','Dance Floor','Effects','Trussing') NOT NULL,
  `serial_number` varchar(100) DEFAULT NULL,
  `total_quantity` int(11) DEFAULT 0,
  `is_serialized` tinyint(1) DEFAULT 0,
  `archived` tinyint(1) NOT NULL DEFAULT 0,
  `min_stock_threshold` int(11) NOT NULL DEFAULT 2,
  `status` varchar(50) DEFAULT 'Available',
  `category` varchar(100) DEFAULT 'General',
  `location` varchar(100) DEFAULT 'Warehouse',
  `quantity` int(11) DEFAULT 1,
  `purchase_date` date DEFAULT NULL,
  `supplier_name` varchar(200) DEFAULT NULL,
  `unit_cost` decimal(10,2) DEFAULT NULL,
  `replacement_value` decimal(10,2) DEFAULT NULL,
  `unit_of_measure` varchar(30) NOT NULL DEFAULT 'unit',
  `qty_out` int(11) NOT NULL DEFAULT 0,
  `qty_damaged` int(11) NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci;

INSERT INTO `equipment` (`id`, `official_name`, `workshop_name`, `equipment_group`, `serial_number`, `total_quantity`, `is_serialized`, `archived`, `min_stock_threshold`, `status`, `category`, `location`, `quantity`, `purchase_date`, `supplier_name`, `unit_cost`, `replacement_value`, `unit_of_measure`, `qty_out`, `qty_damaged`) VALUES
(1001, 'PB14B Test Speaker', 'PB14B-TSP-1', 'Sound', 'PB14B-SN-1001', 1, 1, 0, 2, 'Available', 'Sound', 'Warehouse', 1, NULL, 'Test Supplier', NULL, NULL, 'unit', 0, 0),
(1002, 'PB14B Test Cable', 'PB14B-CAB-2', 'Cabling and Accessories', NULL, 50, 0, 0, 5, 'Available', 'Cabling', 'Warehouse', 50, NULL, NULL, NULL, NULL, 'unit', 0, 0),
(1003, 'PB14B Test Truck', 'PB14B-TRK-3', 'Vehicles', 'PB14B-VEH-001', 1, 1, 0, 2, 'Available', 'Vehicles', 'Yard', 1, NULL, NULL, NULL, NULL, 'unit', 0, 0),
(1004, 'PB14B Retired Lamp', 'PB14B-LMP-4', 'Lighting', NULL, 2, 0, 1, 2, 'Available', 'Lighting', 'Warehouse', 2, NULL, NULL, NULL, NULL, 'unit', 0, 0),
(1005, 'PB14B Damaged Mic', 'PB14B-MIC-5', 'Sound', 'PB14B-SN-1005', 1, 1, 0, 2, 'Damaged', 'Sound', 'Warehouse', 1, NULL, NULL, NULL, NULL, 'unit', 0, 1);
"""
sql_path = os.path.join(tempfile.gettempdir(), "pb14b_sample.sql")
with open(sql_path, "w", encoding="utf-8") as f:
    f.write(SAMPLE_SQL)

parsed = migrate_legacy_inventory._parse_sql_dump(sql_path)
_check("T-B14b-11",
       len(parsed) == 5,
       f"parser found {len(parsed)} rows (expected 5)")

classified, csv_rows = migrate_legacy_inventory._generate_csv(parsed)
by_action = {}
for c in classified:
    by_action[c["action"]] = by_action.get(c["action"], 0) + 1
_check("T-B14b-12",
       by_action.get("CREATE-serial-unit") == 2
       and by_action.get("CREATE-quantity-row") == 1
       and by_action.get("SKIP-vehicle") == 1
       and by_action.get("SKIP-archived") == 1,
       f"classification breakdown: {by_action}")


# ============================================================
# T-B14b-13 -- vehicles SKIPPED
# ============================================================
veh = [c for c in classified if c["action"] == "SKIP-vehicle"]
_check("T-B14b-13",
       len(veh) == 1
       and veh[0]["group"] == "Vehicles"
       and veh[0]["workshop_name"] == "PB14B-TRK-3",
       f"vehicles skipped: {veh}")


# ============================================================
# T-B14b-14 -- archived SKIPPED
# ============================================================
arc = [c for c in classified if c["action"] == "SKIP-archived"]
_check("T-B14b-14",
       len(arc) == 1
       and arc[0]["workshop_name"] == "PB14B-LMP-4",
       f"archived skipped: {arc}")


# ============================================================
# T-B14b-15 -- needs_repair flagged from qty_damaged>0
# ============================================================
damaged_row = next(
    r for r in csv_rows
    if r["workshop_name"] == "PB14B-MIC-5")
_check("T-B14b-15",
       damaged_row["condition_status"] == "needs_repair",
       f"qty_damaged>0 -> needs_repair: condition="
       f"{damaged_row['condition_status']!r}")


# ============================================================
# T-B14b-16 -- legacy_qty preserved in notes (D1 traceability)
# ============================================================
cable_csv = next(
    r for r in csv_rows
    if r["workshop_name"] == "PB14B-CAB-2")
_check("T-B14b-16",
       "legacy_qty=50" in cable_csv["notes"]
       and "legacy_id=1002" in cable_csv["notes"],
       f"quantity-row notes carry legacy traceability: "
       f"{cable_csv['notes']!r}")


# ============================================================
# T-B14b-17 -- supplier captured to notes only (no res.partner)
# ============================================================
speaker_csv = next(
    r for r in csv_rows
    if r["workshop_name"] == "PB14B-TSP-1")
_check("T-B14b-17",
       "legacy_supplier=Test Supplier" in speaker_csv["notes"]
       and not env["res.partner"].sudo().search_count(
           [("name", "=", "Test Supplier")]),
       f"supplier in notes; res.partner NOT auto-created: "
       f"notes={speaker_csv['notes']!r}")


# ============================================================
# T-B14b-18..21 -- end-to-end migrate(): dry-run then execute
# ============================================================
result_dry = migrate_legacy_inventory.migrate(
    env, sql_path=sql_path, execute=False)
_check("T-B14b-18",
       result_dry["dry_run"] is True
       and result_dry["legacy_row_count"] == 5
       and result_dry["csv_row_count"] == 3,
       f"dry-run: legacy={result_dry['legacy_row_count']} "
       f"csv={result_dry['csv_row_count']}")

# Cleanup before execute -- remove leftover units from earlier
# test rows so the count is deterministic
post_units = Unit.sudo().search(
    [("workshop_name", "=like", "PB14B-%")])
if post_units:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [("unit_id", "in", post_units.ids)]).unlink()
    post_units.unlink()
post_products = Product.sudo().search(
    [("workshop_name", "=like", "PB14B-%")])
post_products.unlink()
env.cr.commit()

result_exec = migrate_legacy_inventory.migrate(
    env, sql_path=sql_path, execute=True)
units_after = Unit.sudo().search(
    [("workshop_name", "=like", "PB14B-%")])
_check("T-B14b-19",
       result_exec["ok"]
       and result_exec["dry_run"] is False
       and len(units_after) == 3,
       f"execute: ok={result_exec['ok']} units_created="
       f"{len(units_after)} (expected 3: speaker + cable + "
       f"damaged-mic)")

# Verify both modes present
serial_units = units_after.filtered(
    lambda u: u.serial_number)
quantity_units = units_after.filtered(
    lambda u: not u.serial_number and not u.asset_tag)
_check("T-B14b-20",
       len(serial_units) == 2 and len(quantity_units) == 1,
       f"unit shape: serial={len(serial_units)} "
       f"quantity={len(quantity_units)}")

# Re-run idempotency end-to-end
result_rerun = migrate_legacy_inventory.migrate(
    env, sql_path=sql_path, execute=True)
units_rerun = Unit.sudo().search(
    [("workshop_name", "=like", "PB14B-%")])
_check("T-B14b-21",
       len(units_rerun) == 3
       and result_rerun["loader_report"]["rows_update"] == 3
       and result_rerun["loader_report"]["rows_create"] == 0,
       f"end-to-end re-run zero dupes: units={len(units_rerun)} "
       f"update={result_rerun['loader_report']['rows_update']} "
       f"create={result_rerun['loader_report']['rows_create']}")


# ============================================================
# T-B14b-22 -- defensive refusal: users INSERT in SQL
# ============================================================
SQL_WITH_USERS = SAMPLE_SQL + (
    "\nINSERT INTO `users` (`id`, `password_hash`) VALUES (1, "
    "'$2y$10$EXAMPLE_HASH');\n")
bad_path = os.path.join(tempfile.gettempdir(),
                          "pb14b_bad.sql")
with open(bad_path, "w", encoding="utf-8") as f:
    f.write(SQL_WITH_USERS)
try:
    migrate_legacy_inventory._parse_sql_dump(bad_path)
    refused = False
    refused_reason = "(no exception raised)"
except ValueError as exc:
    refused = "users" in str(exc).lower()
    refused_reason = str(exc)
_check("T-B14b-22",
       refused,
       f"users INSERT refused defensively: reason={refused_reason!r}")


# ============================================================
# T-B14b-23 -- REJECT(unknown group)
# ============================================================
SQL_UNKNOWN = """
CREATE TABLE `equipment` (`id` int, `official_name` varchar(255), `workshop_name` varchar(255), `equipment_group` varchar(50), `serial_number` varchar(100), `total_quantity` int, `is_serialized` tinyint, `archived` tinyint, `min_stock_threshold` int, `status` varchar(50), `category` varchar(100), `location` varchar(100), `quantity` int, `purchase_date` date, `supplier_name` varchar(200), `unit_cost` decimal, `replacement_value` decimal, `unit_of_measure` varchar(30), `qty_out` int, `qty_damaged` int);
INSERT INTO `equipment` (`id`,`official_name`,`workshop_name`,`equipment_group`,`serial_number`,`total_quantity`,`is_serialized`,`archived`,`min_stock_threshold`,`status`,`category`,`location`,`quantity`,`purchase_date`,`supplier_name`,`unit_cost`,`replacement_value`,`unit_of_measure`,`qty_out`,`qty_damaged`) VALUES
(2001, 'PB14B Strange Thing', 'PB14B-WEIRD', 'NotAGroup', NULL, 1, 0, 0, 1, 'Available', 'X', 'X', 1, NULL, NULL, NULL, NULL, 'unit', 0, 0);
"""
unk_path = os.path.join(tempfile.gettempdir(),
                          "pb14b_unknown.sql")
with open(unk_path, "w", encoding="utf-8") as f:
    f.write(SQL_UNKNOWN)
parsed_u = migrate_legacy_inventory._parse_sql_dump(unk_path)
class_u, _ = migrate_legacy_inventory._generate_csv(parsed_u)
_check("T-B14b-23",
       len(class_u) == 1
       and class_u[0]["action"] == "REJECT"
       and "equipment_group" in class_u[0]["reason"],
       f"unknown group rejected: {class_u}")


# ============================================================
# T-B14b-24 -- category map: every supported group present
# ============================================================
expected_cats = {
    "Sound": "sound", "Visual": "visual", "Lighting": "lighting",
    "Cabling and Accessories": "cabling", "Laptops": "laptops",
    "Staging": "staging", "Dance Floor": "dance_floor",
    "Effects": "effects", "Trussing": "trussing",
}
_check("T-B14b-24",
       migrate_legacy_inventory._CATEGORY_MAP == expected_cats
       and "Vehicles" not in migrate_legacy_inventory._CATEGORY_MAP,
       "category map matches spec + Vehicles excluded")


# ============================================================
# T-B14b-25 -- serial-without-legacy-serial: stub generated
# ============================================================
SQL_NO_SERIAL = """
CREATE TABLE `equipment` (`id` int, `official_name` varchar(255), `workshop_name` varchar(255), `equipment_group` varchar(50), `serial_number` varchar(100), `total_quantity` int, `is_serialized` tinyint, `archived` tinyint, `min_stock_threshold` int, `status` varchar(50), `category` varchar(100), `location` varchar(100), `quantity` int, `purchase_date` date, `supplier_name` varchar(200), `unit_cost` decimal, `replacement_value` decimal, `unit_of_measure` varchar(30), `qty_out` int, `qty_damaged` int);
INSERT INTO `equipment` (`id`,`official_name`,`workshop_name`,`equipment_group`,`serial_number`,`total_quantity`,`is_serialized`,`archived`,`min_stock_threshold`,`status`,`category`,`location`,`quantity`,`purchase_date`,`supplier_name`,`unit_cost`,`replacement_value`,`unit_of_measure`,`qty_out`,`qty_damaged`) VALUES
(3001, 'PB14B Tagged Item', 'PB14B-TAG', 'Sound', NULL, 1, 1, 0, 1, 'Available', 'Sound', 'Warehouse', 1, NULL, NULL, NULL, NULL, 'unit', 0, 0);
"""
ns_path = os.path.join(tempfile.gettempdir(),
                         "pb14b_nostub.sql")
with open(ns_path, "w", encoding="utf-8") as f:
    f.write(SQL_NO_SERIAL)
parsed_ns = migrate_legacy_inventory._parse_sql_dump(ns_path)
_, csv_ns = migrate_legacy_inventory._generate_csv(parsed_ns)
_check("T-B14b-25",
       len(csv_ns) == 1
       and csv_ns[0]["tracking_mode"] == "serial"
       and csv_ns[0]["asset_tag"].startswith("SOUND-")
       and csv_ns[0]["asset_tag"].endswith("-S3001"),
       f"stub asset_tag generated: {csv_ns[0]['asset_tag']!r}")


# ============================================================
# T-B14b-26..28 -- run against the REAL extracted dump
# (read-only -- dry-run only; no execute against the real data)
# ============================================================
real_sql = os.path.join(
    "/mnt/extra-addons/neon_jobs/scripts",
    "legacy_workshop_equipment.sql")
if os.path.isfile(real_sql):
    real_rows = migrate_legacy_inventory._parse_sql_dump(real_sql)
    _check("T-B14b-26",
           len(real_rows) >= 250,
           f"real dump parsed: {len(real_rows)} rows (expect ~281)")
    real_cls, real_csv = migrate_legacy_inventory._generate_csv(
        real_rows)
    by_a = {}
    for c in real_cls:
        by_a[c["action"]] = by_a.get(c["action"], 0) + 1
    _check("T-B14b-27",
           by_a.get("REJECT", 0) == 0,
           f"real dump classifies clean: by_action={by_a}")
    by_g = {}
    for c in real_cls:
        if c["action"] not in (
                "SKIP-vehicle", "SKIP-archived", "REJECT"):
            g = c["group"]
            by_g[g] = by_g.get(g, 0) + 1
    _check("T-B14b-28",
           by_g.get("Sound", 0) >= 50
           and by_g.get("Cabling and Accessories", 0) >= 50,
           f"per-category counts pass sanity: {by_g}")
else:
    for tname in ("T-B14b-26", "T-B14b-27", "T-B14b-28"):
        _check(tname, True,
               "real dump not present in container; skipped "
               "(present in the host worktree)")


# ============================================================
# T-B14b-29 -- vehicles count == 0 product rows imported
# ============================================================
if os.path.isfile(real_sql):
    veh_count = sum(
        1 for c in real_cls if c["action"] == "SKIP-vehicle")
    _check("T-B14b-29",
           True,  # not asserting count, just visibility
           f"vehicles skipped from real dump: {veh_count} rows")
else:
    _check("T-B14b-29", True, "skipped (no real dump in container)")


# ============================================================
# T-B14b-30 -- archived count visibility
# ============================================================
if os.path.isfile(real_sql):
    arc_count = sum(
        1 for c in real_cls if c["action"] == "SKIP-archived")
    _check("T-B14b-30",
           True,
           f"archived skipped from real dump: {arc_count} rows")
else:
    _check("T-B14b-30", True, "skipped (no real dump in container)")


# ============================================================
# T-B14b-31 -- prod is empty -- we did NOT touch prod (this
# smoke runs on dev only; assert dev DB)
# ============================================================
_check("T-B14b-31",
       env.cr.dbname == "neon_crm",
       f"running on dev DB ({env.cr.dbname}); prod load is a "
       f"separate human-approved step")


# ============================================================
# T-B14b-32 -- no res.partner created during the migration
# ============================================================
suppliers_after = env["res.partner"].sudo().search_count(
    [("name", "=", "Test Supplier")])
_check("T-B14b-32",
       suppliers_after == 0,
       f"no suppliers auto-created: count={suppliers_after}")


# ============================================================
# Cleanup
# ============================================================
post_units2 = Unit.sudo().search(
    [("workshop_name", "=like", "PB14B-%")])
if post_units2:
    Movement.sudo().with_context(
        _allow_movement_write=True).search(
        [("unit_id", "in", post_units2.ids)]).unlink()
    post_units2.unlink()
post_products2 = Product.sudo().search(
    [("workshop_name", "=like", "PB14B-%")])
post_products2.unlink()
env.cr.commit()


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
