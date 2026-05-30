"""P-B14 smoke -- equipment inventory CSV loader.

Runs in `odoo shell -d <db>`. T-B14-01 ... T-B14-25.

Covers:
- @api.model wrapper resolves + executes
- header validation (missing required column / unknown column)
- preflight (file not found / unreadable)
- dry-run writes NOTHING
- 12-row sample classifies to 11 CREATE + 1 REJECT (asset_tag missing)
- subcategory auto-create (B14 D5)
- product.template auto-create with is_workshop_item=True
- condition_status defaults to 'good'
- low_stock_threshold writes to CATEGORY (B1 field)
- execute pass with rejects is BLOCKED (unless force_with_rejects)
- re-run after execute is fully idempotent (zero new rows)
- malformed row reasons surface clearly per row
- ACL: non-manager rejected
- post-execute: units present with mapped fields
"""
import os
from datetime import date


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-B14 -- equipment inventory CSV loader")
print("=" * 72)
results = {}

Users = env["res.users"]
Unit = env["neon.equipment.unit"]
Cat = env["neon.equipment.category"]
Product = env["product.template"]

# Grant admin the superuser group so loader ACL passes.
admin = env.ref("base.user_admin")
admin.sudo().write({
    "groups_id": [
        (4, env.ref("neon_core.group_neon_superuser").id),
        (4, env.ref("neon_jobs.group_neon_jobs_manager").id),
    ],
})
env = env(user=admin.id)

from odoo.modules.module import get_module_path
sample_csv = os.path.join(
    get_module_path("neon_jobs"),
    "data", "sample_inventory.csv")


# ============================================================
# Cleanup: ensure a clean slate for THIS sample's asset tags
# + categories. We don't touch other data.
# ============================================================
def _wipe_sample():
    sample_tags = (
        "MIC-001", "MIC-002", "LED-001", "MBP-001",
        "SWITCH-001", "LIGHT-001",
        "CABLE-001", "CABLE-002",
        "TRUSS-001", "TRUSS-002", "GEL-001",
    )
    Unit.sudo().search(
        [("asset_tag", "in", list(sample_tags))]).unlink()
    # Wipe the products we auto-created (lookup by workshop_name)
    sample_products = (
        "Shure SLX-D Handheld", "Absen A3 Pro 3.9mm",
        "MacBook Pro 16 M3", "Roland V-1HD Switcher",
        "Chauvet Maverick Storm 1 Wash", "XLR Drum 25m",
        "F34 Square 2m Section", "Lee 201 Full CTB Pack",
    )
    Product.sudo().search([
        ("workshop_name", "in", list(sample_products))]).unlink()
    # Wipe the subcategories we may have auto-created (they'll be
    # re-created by the loader). Top-level seeds untouched.
    Cat.sudo().search([
        ("code", "in", ["wireless_mics", "led_walls",
                         "moving_heads", "xlr", "gels"])]).unlink()
    env.cr.commit()


_wipe_sample()


# ============================================================
# T-B14-01 -- @api.model wrapper exists + dry-run signature
# ============================================================
_check("T-B14-01",
       hasattr(Unit, "import_inventory_csv")
       and callable(getattr(Unit, "import_inventory_csv")),
       "neon.equipment.unit.import_inventory_csv is callable")


# ============================================================
# T-B14-02 -- preflight: missing file raises clean FileNotFoundError
# ============================================================
try:
    Unit.import_inventory_csv("/tmp/does_not_exist_pb14.csv",
                               dry_run=True)
    raised = None
except Exception as exc:  # noqa: BLE001
    raised = type(exc).__name__
_check("T-B14-02",
       raised == "FileNotFoundError",
       f"missing file -> FileNotFoundError; got={raised}")


# ============================================================
# T-B14-03 -- preflight: empty path raises ValueError
# ============================================================
try:
    Unit.import_inventory_csv("", dry_run=True)
    raised = None
except Exception as exc:  # noqa: BLE001
    raised = type(exc).__name__
_check("T-B14-03",
       raised == "ValueError",
       f"empty path -> ValueError; got={raised}")


# ============================================================
# T-B14-04 -- header validation: missing required column
# ============================================================
import tempfile
bad_csv = os.path.join(tempfile.gettempdir(),
                        "pb14_bad_header.csv")
with open(bad_csv, "w", encoding="utf-8") as f:
    # asset_tag missing from header
    f.write("category_code,workshop_name\n")
    f.write("sound,Shure\n")
bad_report = Unit.import_inventory_csv(bad_csv, dry_run=True)
_check("T-B14-04",
       not bad_report["ok"]
       and bad_report.get("preflight_error", "")
            .startswith("CSV header missing"),
       f"missing-column header -> preflight_error: "
       f"{bad_report.get('preflight_error', '')[:80]}")


# ============================================================
# T-B14-05 -- header validation: unknown column
# ============================================================
unk_csv = os.path.join(tempfile.gettempdir(),
                       "pb14_unknown_col.csv")
with open(unk_csv, "w", encoding="utf-8") as f:
    f.write("asset_tag,category_code,workshop_name,bogus_col\n")
    f.write("X-001,sound,Shure,whatever\n")
unk_report = Unit.import_inventory_csv(unk_csv, dry_run=True)
_check("T-B14-05",
       not unk_report["ok"]
       and "unknown columns" in unk_report.get(
            "preflight_error", ""),
       f"unknown column -> preflight_error: "
       f"{unk_report.get('preflight_error', '')[:80]}")


# ============================================================
# T-B14-06 -- DRY-RUN: writes nothing
# ============================================================
unit_count_before = Unit.sudo().search_count([])
product_count_before = Product.sudo().search_count([
    ("is_workshop_item", "=", True)])
dry_report = Unit.import_inventory_csv(sample_csv, dry_run=True)
unit_count_after_dry = Unit.sudo().search_count([])
product_count_after_dry = Product.sudo().search_count([
    ("is_workshop_item", "=", True)])
_check("T-B14-06",
       unit_count_before == unit_count_after_dry
       and product_count_before == product_count_after_dry,
       f"dry-run: units {unit_count_before}->{unit_count_after_dry}, "
       f"products {product_count_before}->{product_count_after_dry}")


# ============================================================
# T-B14-07 -- DRY-RUN: report shape correct
# ============================================================
_check("T-B14-07",
       isinstance(dry_report, dict)
       and "rows_total" in dry_report
       and "rows_create" in dry_report
       and "rows_update" in dry_report
       and "rows_reject" in dry_report
       and "report" in dry_report
       and dry_report["dry_run"] is True,
       f"dry-run report shape ok; rows_total={dry_report['rows_total']}")


# ============================================================
# T-B14-08 -- DRY-RUN: classifies 12 rows correctly
# (11 CREATE + 1 REJECT for the untagged row)
# ============================================================
_check("T-B14-08",
       dry_report["rows_total"] == 12
       and dry_report["rows_create"] == 11
       and dry_report["rows_reject"] == 1,
       f"counts: total={dry_report['rows_total']} "
       f"create={dry_report['rows_create']} "
       f"reject={dry_report['rows_reject']}")


# ============================================================
# T-B14-09 -- REJECT reason names asset_tag missing
# ============================================================
reject_entries = [r for r in dry_report["report"]
                   if r["action"] == "REJECT"]
_check("T-B14-09",
       len(reject_entries) == 1
       and "asset_tag" in reject_entries[0]["reason"].lower(),
       f"reject reason: {reject_entries[0]['reason'][:80]!r}")


# ============================================================
# T-B14-10 -- execute with rejects is BLOCKED
# ============================================================
blocked_report = Unit.import_inventory_csv(sample_csv,
                                            dry_run=False)
unit_count_after_blocked = Unit.sudo().search_count([])
_check("T-B14-10",
       blocked_report.get("blocked_by_rejects") is True
       and unit_count_before == unit_count_after_blocked,
       f"blocked_by_rejects={blocked_report.get('blocked_by_rejects')} "
       f"units unchanged: {unit_count_before}=={unit_count_after_blocked}")


# ============================================================
# T-B14-11 -- execute with force_with_rejects creates units
# (the 1 REJECT row stays rejected; 11 CREATE rows go through)
# ============================================================
exec_report = Unit.import_inventory_csv(
    sample_csv, dry_run=False, force_with_rejects=True)
env.cr.commit()
unit_count_after_exec = Unit.sudo().search_count([])
_check("T-B14-11",
       exec_report["rows_create"] == 11
       and exec_report["rows_failed"] == 0
       and unit_count_after_exec == unit_count_before + 11,
       f"executed: create={exec_report['rows_create']} "
       f"failed={exec_report['rows_failed']} "
       f"new units={unit_count_after_exec - unit_count_before}")


# ============================================================
# T-B14-12 -- created units carry correct asset tags
# ============================================================
sample_tags = ("MIC-001", "MIC-002", "LED-001", "MBP-001",
                "SWITCH-001", "LIGHT-001",
                "CABLE-001", "CABLE-002",
                "TRUSS-001", "TRUSS-002", "GEL-001")
created_units = Unit.sudo().search(
    [("asset_tag", "in", list(sample_tags))])
_check("T-B14-12",
       len(created_units) == 11,
       f"{len(created_units)}/11 sample units present by asset_tag")


# ============================================================
# T-B14-13 -- condition_status defaults to 'good'
# ============================================================
non_good = created_units.filtered(
    lambda u: u.condition_status != "good")
_check("T-B14-13",
       not non_good,
       f"all created units condition=good; bad={non_good.ids}")


# ============================================================
# T-B14-14 -- serial_number set for serial-tracked rows
# ============================================================
mic_001 = Unit.sudo().search(
    [("asset_tag", "=", "MIC-001")], limit=1)
_check("T-B14-14",
       mic_001 and mic_001.serial_number == "SLXD-001-2024"
       and mic_001.workshop_location == "Sound Rack A",
       f"MIC-001: serial={mic_001.serial_number!r} "
       f"loc={mic_001.workshop_location!r}")


# ============================================================
# T-B14-15 -- subcategory auto-created (B14 D5)
# ============================================================
wireless_mics = Cat.sudo().search(
    [("code", "=", "wireless_mics")], limit=1)
sound_cat = Cat.sudo().search([("code", "=", "sound")], limit=1)
_check("T-B14-15",
       bool(wireless_mics)
       and wireless_mics.parent_id.id == sound_cat.id,
       f"wireless_mics auto-created: id={wireless_mics.id if wireless_mics else 0} "
       f"parent={wireless_mics.parent_id.code if wireless_mics else 'NONE'}")


# ============================================================
# T-B14-16 -- subcategory parent_path chain (B1)
# ============================================================
_check("T-B14-16",
       wireless_mics.parent_path
       and str(sound_cat.id) in wireless_mics.parent_path,
       f"wireless_mics.parent_path={wireless_mics.parent_path!r}")


# ============================================================
# T-B14-17 -- product.template auto-created with
# is_workshop_item=True under the subcategory
# ============================================================
shure_product = Product.sudo().search([
    ("workshop_name", "=", "Shure SLX-D Handheld"),
    ("is_workshop_item", "=", True),
], limit=1)
_check("T-B14-17",
       bool(shure_product)
       and shure_product.equipment_category_id.id == wireless_mics.id
       and shure_product.tracking_mode == "serial",
       f"Shure product: id={shure_product.id if shure_product else 0} "
       f"cat={shure_product.equipment_category_id.code if shure_product else 'NONE'} "
       f"tracking={shure_product.tracking_mode if shure_product else 'NONE'}")


# ============================================================
# T-B14-18 -- low_stock_threshold written to CATEGORY (B1 field)
# (MIC-001 row sets threshold=2 -- should be on wireless_mics cat)
# ============================================================
_check("T-B14-18",
       wireless_mics.low_stock_threshold == 2,
       f"wireless_mics.low_stock_threshold="
       f"{wireless_mics.low_stock_threshold} (want 2)")


# ============================================================
# T-B14-19 -- quantity-tracked rows still create units
# ============================================================
cable_001 = Unit.sudo().search(
    [("asset_tag", "=", "CABLE-001")], limit=1)
cable_002 = Unit.sudo().search(
    [("asset_tag", "=", "CABLE-002")], limit=1)
xlr_cat = Cat.sudo().search([("code", "=", "xlr")], limit=1)
_check("T-B14-19",
       bool(cable_001) and bool(cable_002)
       and bool(xlr_cat)
       and cable_001.product_template_id.equipment_category_id.id == xlr_cat.id
       and cable_001.product_template_id.tracking_mode == "quantity"
       and not cable_001.serial_number
       and cable_001.condition_status == "good",
       f"CABLE-001: cat={cable_001.product_template_id.equipment_category_id.code} "
       f"tracking={cable_001.product_template_id.tracking_mode} "
       f"serial={cable_001.serial_number!r}")


# ============================================================
# T-B14-20 -- batch-tracked row creates unit with batch_code
# ============================================================
gel_001 = Unit.sudo().search(
    [("asset_tag", "=", "GEL-001")], limit=1)
_check("T-B14-20",
       bool(gel_001)
       and gel_001.batch_code == "BATCH-2025-Q1"
       and gel_001.product_template_id.tracking_mode == "batch",
       f"GEL-001: batch={gel_001.batch_code!r} "
       f"tracking={gel_001.product_template_id.tracking_mode}")


# ============================================================
# T-B14-21 -- IDEMPOTENT re-run: zero new units, zero updates
# of consequence (mapped fields are the same)
# ============================================================
unit_count_before_rerun = Unit.sudo().search_count([])
rerun_report = Unit.import_inventory_csv(
    sample_csv, dry_run=False, force_with_rejects=True)
env.cr.commit()
unit_count_after_rerun = Unit.sudo().search_count([])
_check("T-B14-21",
       unit_count_after_rerun == unit_count_before_rerun
       and rerun_report["rows_create"] == 0
       and rerun_report["rows_update"] == 11
       and rerun_report["rows_reject"] == 1,
       f"idempotent re-run: units {unit_count_before_rerun}->"
       f"{unit_count_after_rerun} (delta=0); "
       f"create={rerun_report['rows_create']} "
       f"update={rerun_report['rows_update']}")


# ============================================================
# T-B14-22 -- DRY-RUN with mapped change shows UPDATE intent
# without writing
# ============================================================
# Modify the in-DB unit so the dry-run sees a diff path; we don't
# need to write the dry-run to test that it doesn't write.
mod_csv = os.path.join(tempfile.gettempdir(), "pb14_modified.csv")
with open(mod_csv, "w", encoding="utf-8") as f:
    f.write("asset_tag,category_code,workshop_name,tracking_mode,"
            "serial_number,workshop_location,condition_status,notes\n")
    f.write("MIC-001,sound,Shure SLX-D Handheld,serial,"
            "SLXD-001-2024,Sound Rack B,needs_repair,"
            "Moved to repair queue\n")
mod_dry = Unit.import_inventory_csv(mod_csv, dry_run=True)
mic_001.invalidate_recordset()
_check("T-B14-22",
       mod_dry["rows_update"] == 1
       and mic_001.workshop_location == "Sound Rack A"
       and mic_001.condition_status == "good",
       f"dry-run of modified row: action=UPDATE but no write; "
       f"location stays {mic_001.workshop_location!r}")


# ============================================================
# T-B14-23 -- ACL: non-superuser/manager rejected
# ============================================================
crew_user = Users.sudo().search(
    [("login", "=", "pb14_crew_test")], limit=1)
if not crew_user:
    crew_user = Users.sudo().with_context(
        no_reset_password=True).create({
        "name": "pb14_crew_test", "login": "pb14_crew_test",
        "password": "test123",
        "groups_id": [(6, 0, [env.ref("base.group_user").id])],
    })
try:
    Unit.with_user(crew_user).import_inventory_csv(
        sample_csv, dry_run=True)
    acl_err = None
except Exception as exc:  # noqa: BLE001
    acl_err = type(exc).__name__
_check("T-B14-23",
       acl_err in ("PermissionError", "AccessError"),
       f"non-superuser rejected; got={acl_err}")


# ============================================================
# T-B14-24 -- duplicate asset_tag within one CSV rejected
# ============================================================
dup_csv = os.path.join(tempfile.gettempdir(), "pb14_dup.csv")
with open(dup_csv, "w", encoding="utf-8") as f:
    f.write("asset_tag,category_code,workshop_name,tracking_mode,"
            "serial_number\n")
    f.write("DUP-001,sound,Shure,serial,SR-001\n")
    f.write("DUP-001,sound,Shure,serial,SR-002\n")
dup_report = Unit.import_inventory_csv(dup_csv, dry_run=True)
_check("T-B14-24",
       dup_report["rows_reject"] == 1
       and dup_report["rows_create"] == 1
       and any("duplicated" in r["reason"]
                for r in dup_report["report"]),
       f"in-CSV dup: create={dup_report['rows_create']} "
       f"reject={dup_report['rows_reject']}")


# ============================================================
# T-B14-25 -- malformed numeric field rejected with reason
# ============================================================
mal_csv = os.path.join(tempfile.gettempdir(), "pb14_mal.csv")
with open(mal_csv, "w", encoding="utf-8") as f:
    f.write("asset_tag,category_code,workshop_name,tracking_mode,"
            "serial_number,purchase_price\n")
    f.write("MAL-001,sound,Shure,serial,SR-MAL,not_a_number\n")
mal_report = Unit.import_inventory_csv(mal_csv, dry_run=True)
mal_reject = [r for r in mal_report["report"]
               if r["action"] == "REJECT"]
_check("T-B14-25",
       mal_report["rows_reject"] == 1
       and len(mal_reject) == 1
       and "purchase_price" in mal_reject[0]["reason"],
       f"malformed price rejected; "
       f"reason={mal_reject[0]['reason'][:80]!r}")


# ============================================================
# Cleanup
# ============================================================
_wipe_sample()


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
