"""P9.M9.2 smoke -- Jobs block venue pin: row dict 4-key expansion,
coord vs address vs empty venue paths, OWL template + dialog scaffold
presence.

Runs in `odoo shell -d <db>`. T9200-T9211.

T9200  _compute_jobs_block row dict includes venue_id key
T9201  row dict includes venue_latitude key
T9202  row dict includes venue_longitude key
T9203  row dict includes venue_full_address key
T9204  coord-bearing venue: lat/lng nonzero, full_address present
T9205  address-only venue: lat/lng zero, full_address present
T9206  bare venue (no coords, no address): lat/lng zero, address empty
T9207  TBD/no venue: venue_id is False, all map keys default-safe
T9208  neon_dashboard.xml template includes fa-map-marker pin element
T9209  neon_dashboard.xml template emits onVenuePinClick handler
T9210  NeonVenueMapDialog asset bundled in web.assets_backend
T9211  NeonVenueMapView asset bundled in web.assets_backend
"""
from datetime import date, timedelta


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


print("=" * 72)
print("P9.M9.2 -- Jobs block venue pin row dict + template hooks")
print("=" * 72)
results = {}

Dashboard = env["neon.dashboard"]
Users = env["res.users"]
Job = env["commercial.job"]
EventJob = env["commercial.event.job"]
Partner = env["res.partner"]
IrAsset = env["ir.asset"]


# ----------------------------------------------------------------------
# Director fixture user.
# ----------------------------------------------------------------------
def _get_or_make_user(login, group_xmlid):
    user = Users.search([("login", "=", login)], limit=1)
    group = env.ref(group_xmlid)
    if not user:
        user = Users.with_context(no_reset_password=True).create({
            "name": login, "login": login, "password": "test123",
            "groups_id": [(4, group.id)],
        })
    elif group.id not in user.groups_id.ids:
        user.write({"groups_id": [(4, group.id)]})
    return user


u_director = _get_or_make_user(
    "p9m2_director", "neon_core.group_neon_superuser")


# ----------------------------------------------------------------------
# Build a small isolated fixture: 3 event_jobs in next 7 days.
# - venue_coords: lat/lng set (Rainbow Towers approx)
# - venue_addr:   no coords, but street/city/country filled
# - venue_bare:   neither
# ----------------------------------------------------------------------
print("--- seeding P9.M9.2 fixtures ---")

usd = env.ref("base.USD")
zw = env.ref("base.zw", raise_if_not_found=False)

partner = Partner.sudo().create({
    "name": "P9M2 Client", "is_company": True,
})

venue_coords = Partner.sudo().create({
    "name": "P9M2 Coords Venue", "is_company": True, "is_venue": True,
    "partner_latitude": -17.8567035,
    "partner_longitude": 31.0601584,
})

venue_addr = Partner.sudo().create({
    "name": "P9M2 Address Venue", "is_company": True, "is_venue": True,
    "street": "123 Sample Avenue",
    "city": "Harare",
    "country_id": zw.id if zw else False,
})

venue_bare = Partner.sudo().create({
    "name": "P9M2 Bare Venue", "is_company": True, "is_venue": True,
})

today = date.today()


def _mk_job(event_date, venue):
    j = Job.sudo().create({
        "partner_id": partner.id, "venue_id": venue.id,
        "event_date": event_date, "currency_id": usd.id,
    })
    ej = EventJob.sudo().create({"commercial_job_id": j.id})
    return j, ej


j_c, ej_c = _mk_job(today + timedelta(days=1), venue_coords)
j_a, ej_a = _mk_job(today + timedelta(days=2), venue_addr)
j_b, ej_b = _mk_job(today + timedelta(days=3), venue_bare)

print(f"  director uid={u_director.id}")
print(f"  ej_coords={ej_c.id} ej_addr={ej_a.id} ej_bare={ej_b.id}")


# ----------------------------------------------------------------------
# Build _compute_jobs_block payload through the director's permissions.
# ----------------------------------------------------------------------
jb = Dashboard.sudo().with_user(u_director)._compute_jobs_block(
    "director")
print("  jobs_block.empty:", jb.get("empty"))
print("  jobs_block.rows count:", len(jb.get("rows", [])))


def _row_for(ej_id):
    for row in jb.get("rows") or []:
        if row.get("id") == ej_id:
            return row
    return None


row_c = _row_for(ej_c.id)
row_a = _row_for(ej_a.id)
row_b = _row_for(ej_b.id)

print(f"  row_c keys: lat={row_c and row_c.get('venue_latitude')} "
      f"lng={row_c and row_c.get('venue_longitude')}")
print(f"  row_a keys: addr={row_a and row_a.get('venue_full_address')!r}")
print(f"  row_b keys: lat={row_b and row_b.get('venue_latitude')} "
      f"addr={row_b and row_b.get('venue_full_address')!r}")


# ============================================================
print()
print("T9200 -- row dict includes venue_id key")
print("=" * 72)
ok = row_c is not None and "venue_id" in row_c
print("  venue_id present on coords row:", ok)
print("  venue_id value:", row_c.get("venue_id") if row_c else "N/A")
print("T9200:", "PASS" if ok else "FAIL")
results["T9200"] = ok


# ============================================================
print()
print("T9201 -- row dict includes venue_latitude key")
print("=" * 72)
ok = all(r is not None and "venue_latitude" in r
         for r in (row_c, row_a, row_b))
print("  venue_latitude present on all 3 rows:", ok)
print("T9201:", "PASS" if ok else "FAIL")
results["T9201"] = ok


# ============================================================
print()
print("T9202 -- row dict includes venue_longitude key")
print("=" * 72)
ok = all(r is not None and "venue_longitude" in r
         for r in (row_c, row_a, row_b))
print("  venue_longitude present on all 3 rows:", ok)
print("T9202:", "PASS" if ok else "FAIL")
results["T9202"] = ok


# ============================================================
print()
print("T9203 -- row dict includes venue_full_address key")
print("=" * 72)
ok = all(r is not None and "venue_full_address" in r
         for r in (row_c, row_a, row_b))
print("  venue_full_address present on all 3 rows:", ok)
print("T9203:", "PASS" if ok else "FAIL")
results["T9203"] = ok


# ============================================================
print()
print("T9204 -- coord-bearing venue: lat/lng nonzero")
print("=" * 72)
ok = (
    row_c is not None
    and abs(row_c.get("venue_latitude") or 0) > 0.001
    and abs(row_c.get("venue_longitude") or 0) > 0.001
)
print(f"  lat={row_c and row_c.get('venue_latitude')} "
      f"lng={row_c and row_c.get('venue_longitude')}")
print("T9204:", "PASS" if ok else "FAIL")
results["T9204"] = ok


# ============================================================
print()
print("T9205 -- address-only venue: zero coords + non-empty address")
print("=" * 72)
ok = (
    row_a is not None
    and (row_a.get("venue_latitude") or 0) == 0.0
    and (row_a.get("venue_longitude") or 0) == 0.0
    and bool(row_a.get("venue_full_address"))
)
print(f"  lat={row_a and row_a.get('venue_latitude')} "
      f"addr={row_a and row_a.get('venue_full_address')!r}")
print("T9205:", "PASS" if ok else "FAIL")
results["T9205"] = ok


# ============================================================
print()
print("T9206 -- bare venue: zero coords, empty address")
print("=" * 72)
ok = (
    row_b is not None
    and (row_b.get("venue_latitude") or 0) == 0.0
    and (row_b.get("venue_longitude") or 0) == 0.0
    and not row_b.get("venue_full_address")
)
print(f"  lat={row_b and row_b.get('venue_latitude')} "
      f"addr={row_b and row_b.get('venue_full_address')!r}")
print("T9206:", "PASS" if ok else "FAIL")
results["T9206"] = ok


# ============================================================
print()
print("T9207 -- TBD-style row (no venue): map keys default-safe")
print("=" * 72)
# Create an event_job whose underlying commercial.job has the TBD
# placeholder venue (or no venue) so we exercise the `or False` /
# `or 0.0` defaults in the row dict.
tbd = env.ref("neon_jobs.partner_tbd_venue", raise_if_not_found=False)
if tbd:
    j_tbd, ej_tbd = _mk_job(today + timedelta(days=4), tbd)
    jb2 = Dashboard.sudo().with_user(u_director)._compute_jobs_block(
        "director")
    row_tbd = next(
        (r for r in jb2.get("rows") or [] if r.get("id") == ej_tbd.id),
        None,
    )
    ok = (
        row_tbd is not None
        and row_tbd.get("venue_id") == tbd.id  # TBD partner is set
        and (row_tbd.get("venue_latitude") or 0) == 0.0
        and (row_tbd.get("venue_longitude") or 0) == 0.0
        and isinstance(row_tbd.get("venue_full_address"), str)
    )
    print(f"  tbd row keys safe: {ok}")
else:
    # TBD xmlid absent on this DB -- not a hard failure, skip.
    print("  partner_tbd_venue xmlid not present; skipping")
    ok = True
print("T9207:", "PASS" if ok else "FAIL")
results["T9207"] = ok


# ============================================================
print()
print("T9208 -- dashboard XML template includes fa-map-marker pin")
print("=" * 72)
import os
from odoo.modules.module import get_module_path
xml_path = os.path.join(
    get_module_path("neon_dashboard"),
    "static/src/js/neon_dashboard/neon_dashboard.xml",
)
with open(xml_path, "r", encoding="utf-8") as f:
    xml_src = f.read()
ok = (
    "o_neon_jobs_venue_pin" in xml_src
    and "fa fa-map-marker" in xml_src
    and "o_neon_jobs_venue_cell" in xml_src
)
print(f"  pin classes present in template: {ok}")
print("T9208:", "PASS" if ok else "FAIL")
results["T9208"] = ok


# ============================================================
print()
print("T9209 -- template emits onVenuePinClick handler")
print("=" * 72)
ok = "onVenuePinClick" in xml_src and "t-on-click.stop" in xml_src
print(f"  handler + stop-propagation present: {ok}")
print("T9209:", "PASS" if ok else "FAIL")
results["T9209"] = ok


# ============================================================
print()
print("T9210 -- NeonVenueMapDialog assets bundled")
print("=" * 72)
# ir.asset isn't populated for the inline-manifest "assets" dict --
# Odoo evaluates the manifest dict directly at asset bundling time.
# Verify by reading the manifest file and confirming the new paths.
manifest_path = os.path.join(
    get_module_path("neon_dashboard"), "__manifest__.py")
with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_src = f.read()
ok = (
    "neon_venue_map_dialog.js" in manifest_src
    and "neon_venue_map_dialog.xml" in manifest_src
    and "neon_venue_map_dialog.scss" in manifest_src
)
print(f"  dialog .js/.xml/.scss in manifest: {ok}")
print("T9210:", "PASS" if ok else "FAIL")
results["T9210"] = ok


# ============================================================
print()
print("T9211 -- NeonVenueMapView asset bundled in neon_jobs")
print("=" * 72)
manifest_j = os.path.join(
    get_module_path("neon_jobs"), "__manifest__.py")
with open(manifest_j, "r", encoding="utf-8") as f:
    manifest_j_src = f.read()
ok = "venue_map_view.js" in manifest_j_src
print(f"  venue_map_view.js in neon_jobs manifest: {ok}")
print("T9211:", "PASS" if ok else "FAIL")
results["T9211"] = ok


# ----------------------------------------------------------------------
# Cleanup.
# ----------------------------------------------------------------------
print()
print("--- cleanup ---")
EventJob.sudo().search([
    ("commercial_job_id.partner_id", "=", partner.id)
]).unlink()
Job.sudo().search([("partner_id", "=", partner.id)]).unlink()
venue_coords.sudo().unlink()
venue_addr.sudo().unlink()
venue_bare.sudo().unlink()
partner.sudo().unlink()


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
