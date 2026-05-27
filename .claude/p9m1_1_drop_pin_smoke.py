"""P9.M9.1.1 smoke -- Leaflet drop-pin vendoring + widget wiring.

T9110-T9115. File/manifest/view assertions + an M9.1 logic regression
subset (the drop-pin commits through the same write() path).
"""
import os

results = {}
print("=" * 72)
print("P9.M9.1.1 -- Leaflet drop-pin")
print("=" * 72)

Partner = env["res.partner"]
sp = env.cr.savepoint()
BASE = "/mnt/extra-addons/neon_jobs"
LIB = BASE + "/static/lib/leaflet"


def _check(tnum, cond, detail=""):
    results[tnum] = bool(cond)
    print(f"{tnum}: {'PASS' if cond else 'FAIL'} {detail}")


# T9110 -- vendored Leaflet files present (3 + 3 images).
need = [
    LIB + "/leaflet.js", LIB + "/leaflet.css", LIB + "/README.md",
    LIB + "/images/marker-icon.png", LIB + "/images/marker-icon-2x.png",
    LIB + "/images/marker-shadow.png",
]
missing = [p for p in need if not os.path.exists(p)]
_check("T9110", not missing, f"missing={missing}")

# T9111 -- manifest declares leaflet.js + leaflet.css in the bundle.
with open(BASE + "/__manifest__.py", "r", encoding="utf-8") as f:
    mani = f.read()
_check("T9111",
       "static/lib/leaflet/leaflet.js" in mani
       and "static/lib/leaflet/leaflet.css" in mani
       and "venue_pin/venue_pin.js" in mani
       and '"17.0.4.2.0"' in mani,
       "leaflet + pin assets + version in manifest")

# T9112 -- the venue widget registers in the JS source.
with open(BASE + "/static/src/js/venue_pin/venue_pin.js", "r",
          encoding="utf-8") as f:
    js = f.read()
_check("T9112",
       'view_widgets").add(' in js
       and "neon_venue_pin_picker" in js
       and "L.Icon.Default.imagePath" in js,
       "widget registered + imagePath set")

# T9113 -- res.partner inherit view carries the widget tag.
view = env.ref("neon_jobs.res_partner_view_form_inherit_neon_jobs",
               raise_if_not_found=False)
_check("T9113",
       bool(view) and "neon_venue_pin_picker" in (view.arch_db or ""),
       "pin widget in res.partner inherit view")

# T9114 -- M9.1 regression: direct lat/long edit flips coords_source.
zw = env.ref("base.zw", raise_if_not_found=False)
venue = Partner.create({
    "name": "P9.1.1 Venue", "is_venue": True, "is_company": True,
    "city": "Harare", "country_id": zw.id if zw else False,
})
venue.write({"partner_latitude": -17.83, "partner_longitude": 31.05})
_check("T9114", venue.coords_source == "manual",
       f"drop-pin commit path -> manual ({venue.coords_source})")

# T9115 -- M9.1 regression: manual pin survives an address change.
venue.write({"street": "New Street"})
_check("T9115",
       abs(venue.partner_latitude - (-17.83)) < 1e-6
       and venue.coords_source == "manual",
       f"snapshot-restore intact (lat={venue.partner_latitude})")

sp.close(rollback=True)
print("=" * 72)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{len(results)} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
