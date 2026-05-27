# Vendored Leaflet 1.9.4

**First vendored third-party library in this repo** — establishes
`static/lib/` as a legitimate pattern (per pre-check 2026-05-27: no
prior precedent; `web_map`/Leaflet absent in this Community Odoo 17
build).

- **Version:** Leaflet 1.9.4 (current stable 1.x)
- **Source:** https://unpkg.com/leaflet@1.9.4/dist/
- **Pulled:** 2026-05-27, verbatim (unmodified)
- **License:** BSD-2-Clause (Leaflet)

## Files
- `leaflet.js` — minified library (~150 KB)
- `leaflet.css` — stylesheet (~14 KB)
- `images/marker-icon.png`, `marker-icon-2x.png`, `marker-shadow.png`
  — default blue marker assets

## Usage
Loaded via `web.assets_backend` in `neon_jobs/__manifest__.py` for the
`neon_venue_pin_picker` OWL view-widget (P9.M9.1.1 — interactive
drop-pin on the venue partner form). `leaflet.js` exposes the global
`L`; the widget sets `L.Icon.Default.imagePath` to this folder's
`images/` so the marker renders inside Odoo's asset bundle context.
Tiles come from OpenStreetMap (attribution required, set in the widget).

To upgrade: re-pull the same 5 files from the new version's
`unpkg.com/leaflet@<ver>/dist/` and update this README.
