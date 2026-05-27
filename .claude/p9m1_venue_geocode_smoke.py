"""P9.M9.1 smoke -- venue geocode plumbing + manual-override (D6).

T9100-T9106 (7 assertions per the revised M9.1 prompt). geo_localize
is exercised with a MOCKED base.geocoder (no Nominatim network call);
everything else is pure model logic.
"""
from unittest.mock import patch

results = {}
print("=" * 72)
print("P9.M9.1 -- Venue Maps Step 1 (geocode + manual override)")
print("=" * 72)

Partner = env["res.partner"]
EventJob = env["commercial.event.job"]
Job = env["commercial.job"]
Geocoder = type(env["base.geocoder"])
sp = env.cr.savepoint()


def _check(tnum, cond, detail=""):
    results[tnum] = bool(cond)
    print(f"{tnum}: {'PASS' if cond else 'FAIL'} {detail}")


zw = env.ref("base.zw", raise_if_not_found=False) \
    or env["res.country"].search([("code", "=", "ZW")], limit=1)

# T9100 -- coords_source defaults to 'geocoded' on a new partner;
# base_geolocalize installed + fields present.
venue = Partner.create({
    "name": "P9 Venue", "is_venue": True, "is_company": True,
    "street": "1 Pennefather Avenue", "city": "Harare",
    "country_id": zw.id if zw else False,
})
_check("T9100",
       venue.coords_source == "geocoded"
       and "partner_latitude" in Partner._fields
       and env["ir.module.module"].search(
           [("name", "=", "base_geolocalize"),
            ("state", "=", "installed")], limit=1),
       f"default coords_source={venue.coords_source}")

# T9101 -- geo_localize() (mocked geocoder) sets coords_source='geocoded'.
with patch.object(Geocoder, "geo_query_address", return_value="q"), \
     patch.object(Geocoder, "geo_find", return_value=(-17.8312, 31.0451)):
    venue.with_context(force_geo_localize=True).geo_localize()
_check("T9101",
       venue.coords_source == "geocoded"
       and abs(venue.partner_latitude - (-17.8312)) < 1e-6,
       f"after geocode: src={venue.coords_source} "
       f"lat={venue.partner_latitude}")

# T9102 -- direct lat/long edit flips coords_source to 'manual'.
venue.write({"partner_latitude": -17.7800, "partner_longitude": 31.0900})
_check("T9102", venue.coords_source == "manual",
       f"src after manual edit={venue.coords_source}")

# T9103 -- manual pin PRESERVED across an address change (snapshot-restore).
venue.write({"street": "Off Borrowdale Road"})
_check("T9103",
       abs(venue.partner_latitude - (-17.7800)) < 1e-6
       and abs(venue.partner_longitude - 31.0900) < 1e-6
       and venue.coords_source == "manual",
       f"lat={venue.partner_latitude} lng={venue.partner_longitude} "
       f"src={venue.coords_source}")

# T9104 -- GEOCODED pin is zeroed on address change (stock base behaviour
# preserved -- only manual pins are protected).
geo_v = Partner.create({
    "name": "P9 Geo Venue", "is_venue": True, "is_company": True,
    "city": "Harare", "country_id": zw.id if zw else False,
})
geo_v.write({"partner_latitude": -17.8, "partner_longitude": 31.0,
             "coords_source": "geocoded"})  # explicit src -> no manual flip
geo_v.write({"street": "Samora Machel Avenue"})
_check("T9104",
       geo_v.partner_latitude == 0.0 and geo_v.partner_longitude == 0.0,
       f"geocoded zeroed on address change: lat={geo_v.partner_latitude}")

# T9105 -- venue_full_address compute joins parts, skips empties.
addr_v = Partner.create({
    "name": "P9 Addr Venue", "is_venue": True, "is_company": True,
    "street": "1 Pennefather Avenue", "city": "Harare",
    "country_id": zw.id if zw else False,
})
job = Job.search([], limit=1)
if job:
    job.venue_id = addr_v.id
    ej = EventJob.new({"commercial_job_id": job.id})
    addr = ej.venue_full_address
    expected = "1 Pennefather Avenue, Harare" + (", Zimbabwe" if zw else "")
    _check("T9105", addr == expected, f"got={addr!r} expected={expected!r}")
else:
    _check("T9105", False, "no commercial.job to attach venue")

# T9106 -- partner_tbd_venue ref resolves (form invisible domain dep).
tbd = env.ref("neon_jobs.partner_tbd_venue", raise_if_not_found=False)
_check("T9106", bool(tbd) and tbd.is_venue, f"tbd id={tbd.id if tbd else None}")

sp.close(rollback=True)
print("=" * 72)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{len(results)} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
