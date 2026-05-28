"""P9.M9.3 smoke -- Venues · Map (multi-pin client action) ORM layer.

Runs in `odoo shell -d <db>`. T9300-T9309.

T9300  4 fixture venues created (2 mapped + 1 address-only + 1 empty)
T9301  search_read domain returns all 4 fixture venues
T9302  search_read excludes the TBD placeholder partner
T9303  search_read excludes TEST-DELETE-named venues
T9304  2 of the 4 fixture venues are mappable (lat/lng both set)
T9305  2 of the 4 fixture venues are unmappable (lat/lng zero)
T9306  manifest declares the 3 new asset paths
T9307  menu record neon_jobs.menu_neon_venue_multi_map exists
T9308  menu groups_id = base.group_system + manager + crew_leader (3)
T9309  client-action wrapper server action has matching groups_id
"""
import os

from odoo.modules.module import get_module_path


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


print("=" * 72)
print("P9.M9.3 -- Venues · Map multi-pin client action")
print("=" * 72)
results = {}

Partner = env["res.partner"]
IrAction = env["ir.actions.server"]
IrMenu = env["ir.ui.menu"]


# ----------------------------------------------------------------------
# Build fixture: 4 venues — 2 mapped, 1 address-only, 1 empty.
# Plus one TEST-DELETE-named venue to verify the exclusion filter.
# ----------------------------------------------------------------------
print("--- seeding P9.M9.3 fixtures ---")

zw = env.ref("base.zw", raise_if_not_found=False)

v_rainbow = Partner.sudo().create({
    "name": "P9M3 Rainbow", "is_venue": True, "is_company": True,
    "city": "Harare",
    "country_id": zw.id if zw else False,
    "partner_latitude": -17.85,
    "partner_longitude": 31.06,
})
v_meikles = Partner.sudo().create({
    "name": "P9M3 Meikles", "is_venue": True, "is_company": True,
    "city": "Harare",
    "country_id": zw.id if zw else False,
    "partner_latitude": -17.83,
    "partner_longitude": 31.05,
})
v_generic = Partner.sudo().create({
    "name": "P9M3 Generic Hall", "is_venue": True, "is_company": True,
    "street": "5 Sample Road", "city": "Bulawayo",
    "country_id": zw.id if zw else False,
})
v_empty = Partner.sudo().create({
    "name": "P9M3 Empty Venue", "is_venue": True, "is_company": True,
})
v_test_delete = Partner.sudo().create({
    "name": "P9M3 TEST-DELETE Venue", "is_venue": True, "is_company": True,
    "partner_latitude": -17.84,
    "partner_longitude": 31.07,
})

print(f"  created ids: rainbow={v_rainbow.id} meikles={v_meikles.id} "
      f"generic={v_generic.id} empty={v_empty.id} "
      f"test_delete={v_test_delete.id}")


# ============================================================
print()
print("T9300 -- 4 base venues + 1 test-delete venue created")
print("=" * 72)
ok = all(v.id for v in
         (v_rainbow, v_meikles, v_generic, v_empty, v_test_delete))
print(f"  all created: {ok}")
print("T9300:", "PASS" if ok else "FAIL")
results["T9300"] = ok


# ============================================================
print()
print("T9301 -- search_read domain returns the 4 fixture venues")
print("=" * 72)
domain = [
    ("is_venue", "=", True),
    ("name", "not ilike", "TEST-DELETE"),
    ("name", "!=", "TBD — Set Venue"),
]
rows = Partner.sudo().search_read(
    domain,
    ["id", "name", "city", "country_id",
     "partner_latitude", "partner_longitude", "coords_source"],
)
fixture_ids = {v_rainbow.id, v_meikles.id, v_generic.id, v_empty.id}
returned_ids = {r["id"] for r in rows}
ok = fixture_ids.issubset(returned_ids)
print(f"  fixture ids in result: {ok}")
print(f"  total rows: {len(rows)}")
print("T9301:", "PASS" if ok else "FAIL")
results["T9301"] = ok


# ============================================================
print()
print("T9302 -- search_read excludes TBD placeholder")
print("=" * 72)
tbd = env.ref("neon_jobs.partner_tbd_venue", raise_if_not_found=False)
if tbd:
    ok = tbd.id not in returned_ids
    print(f"  TBD id {tbd.id} NOT in result: {ok}")
else:
    print("  partner_tbd_venue xmlid absent; skipping")
    ok = True
print("T9302:", "PASS" if ok else "FAIL")
results["T9302"] = ok


# ============================================================
print()
print("T9303 -- search_read excludes TEST-DELETE venues")
print("=" * 72)
ok = v_test_delete.id not in returned_ids
print(f"  TEST-DELETE id {v_test_delete.id} NOT in result: {ok}")
print("T9303:", "PASS" if ok else "FAIL")
results["T9303"] = ok


# ============================================================
print()
print("T9304 -- 2 of 4 fixture venues are mappable")
print("=" * 72)
fixture_rows = [r for r in rows if r["id"] in fixture_ids]
mapped = [r for r in fixture_rows
          if r["partner_latitude"] and r["partner_longitude"]]
ok = len(mapped) == 2
print(f"  mapped count: {len(mapped)} (expected 2)")
print(f"  mapped names: {[r['name'] for r in mapped]}")
print("T9304:", "PASS" if ok else "FAIL")
results["T9304"] = ok


# ============================================================
print()
print("T9305 -- 2 of 4 fixture venues are unmappable")
print("=" * 72)
unmapped = [r for r in fixture_rows
            if not (r["partner_latitude"] and r["partner_longitude"])]
ok = len(unmapped) == 2
print(f"  unmapped count: {len(unmapped)} (expected 2)")
print(f"  unmapped names: {[r['name'] for r in unmapped]}")
print("T9305:", "PASS" if ok else "FAIL")
results["T9305"] = ok


# ============================================================
print()
print("T9306 -- manifest declares the 3 new asset paths")
print("=" * 72)
manifest_path = os.path.join(
    get_module_path("neon_jobs"), "__manifest__.py")
with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_src = f.read()
ok = (
    "venue_multi_map/venue_multi_map.js" in manifest_src
    and "venue_multi_map/venue_multi_map.xml" in manifest_src
    and "venue_multi_map/venue_multi_map.scss" in manifest_src
    and "17.0.4.4.0" in manifest_src
)
print(f"  3 asset paths + version in manifest: {ok}")
print("T9306:", "PASS" if ok else "FAIL")
results["T9306"] = ok


# ============================================================
print()
print("T9307 -- menu record exists")
print("=" * 72)
menu = env.ref("neon_jobs.menu_neon_venue_multi_map",
               raise_if_not_found=False)
ok = bool(menu)
print(f"  menu xmlid resolves: {ok}")
if menu:
    print(f"  menu name: {menu.name!r} sequence: {menu.sequence}")
print("T9307:", "PASS" if ok else "FAIL")
results["T9307"] = ok


# ============================================================
print()
print("T9308 -- menu groups_id triplet")
print("=" * 72)
if menu:
    g_admin = env.ref("base.group_system")
    g_mgr = env.ref("neon_jobs.group_neon_jobs_manager")
    g_lead = env.ref("neon_jobs.group_neon_jobs_crew_leader")
    expected = {g_admin.id, g_mgr.id, g_lead.id}
    actual = set(menu.groups_id.ids)
    ok = expected == actual
    print(f"  expected groups: {expected}")
    print(f"  actual groups:   {actual}")
else:
    ok = False
print("T9308:", "PASS" if ok else "FAIL")
results["T9308"] = ok


# ============================================================
print()
print("T9309 -- server action wrapper has matching groups_id")
print("=" * 72)
sa = env.ref("neon_jobs.action_neon_venue_multi_map_server",
             raise_if_not_found=False)
if sa:
    g_admin = env.ref("base.group_system")
    g_mgr = env.ref("neon_jobs.group_neon_jobs_manager")
    g_lead = env.ref("neon_jobs.group_neon_jobs_crew_leader")
    expected = {g_admin.id, g_mgr.id, g_lead.id}
    actual = set(sa.groups_id.ids)
    ok = expected == actual
    print(f"  server action groups: {actual}")
else:
    print("  server action xmlid missing")
    ok = False
print("T9309:", "PASS" if ok else "FAIL")
results["T9309"] = ok


# ----------------------------------------------------------------------
# Cleanup.
# ----------------------------------------------------------------------
print()
print("--- cleanup ---")
v_rainbow.sudo().unlink()
v_meikles.sudo().unlink()
v_generic.sudo().unlink()
v_empty.sudo().unlink()
v_test_delete.sudo().unlink()


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
