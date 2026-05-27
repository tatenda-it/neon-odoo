/** @odoo-module **/

/**
 * P9.M9.1.1 -- neon_venue_pin_picker view-widget.
 *
 * Interactive Leaflet drop-pin on the venue partner form. Three ways to
 * set coords (D7): click the map, drag the marker, or pick a Nominatim
 * search result. Each calls record.update({partner_latitude,
 * partner_longitude}) -> Float fields go dirty -> Save persists ->
 * M9.1's write() flips coords_source to 'manual'. Two-way sync (D9):
 * pasting into the lat/long fields repositions the marker.
 *
 * Uses the global `L` from the vendored leaflet.js (loaded earlier in
 * web.assets_backend). OSM tiles (D2) with mandatory attribution.
 */
import {
    Component, onMounted, onWillUnmount, useRef, useState, useEffect,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

const HARARE = [-17.8252, 31.0335];   // D5 default centre
const TOL = 1e-6;                     // ~10cm; D9 loop short-circuit
const NOMINATIM = "https://nominatim.openstreetmap.org/search";

export class NeonVenuePinPicker extends Component {
    static template = "neon_jobs.NeonVenuePinPicker";
    static props = { ...standardWidgetProps };

    setup() {
        this.mapRef = useRef("mapContainer");
        this.state = useState({
            query: "", results: [], searching: false, interacted: false,
        });
        this._map = null;
        this._marker = null;
        this._searchTimer = null;
        this._abort = null;

        onMounted(() => this._initMap());
        onWillUnmount(() => {
            if (this._searchTimer) {
                clearTimeout(this._searchTimer);
            }
            if (this._abort) {
                this._abort.abort();
            }
            if (this._map) {
                this._map.remove();
                this._map = null;
            }
        });

        // D9 direction 1: external lat/long edits (paste-from-Google)
        // reposition the marker. Short-circuits when the marker is
        // already there (within TOL) so map-driven updates don't loop.
        useEffect(
            (lat, lng) => {
                if (!this._map || !lat || !lng) {
                    return;
                }
                if (this._markerFar(lat, lng)) {
                    this._setMarker(lat, lng);
                    this._map.setView([lat, lng], 16);
                }
            },
            () => [this._lat, this._lng],
        );
    }

    get _data() {
        return (this.props.record && this.props.record.data) || {};
    }
    get _lat() { return this._data.partner_latitude || 0; }
    get _lng() { return this._data.partner_longitude || 0; }
    get hasCoords() { return !!(this._lat && this._lng); }

    _markerFar(lat, lng) {
        if (!this._marker) {
            return true;
        }
        const p = this._marker.getLatLng();
        return Math.abs(p.lat - lat) > TOL || Math.abs(p.lng - lng) > TOL;
    }

    _initMap() {
        const L = window.L;
        // D3: explicit imagePath so the default marker resolves inside
        // Odoo's asset bundle (Leaflet's auto-detection fails there).
        L.Icon.Default.imagePath = "/neon_jobs/static/lib/leaflet/images/";
        const center = this.hasCoords ? [this._lat, this._lng] : HARARE;
        const zoom = this.hasCoords ? 16 : 11;
        this._map = L.map(this.mapRef.el).setView(center, zoom);
        L.tileLayer(
            "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            {
                maxZoom: 19,
                attribution:
                    '© <a href="https://www.openstreetmap.org/copyright">'
                    + "OpenStreetMap</a> contributors",
            },
        ).addTo(this._map);
        if (this.hasCoords) {
            this._setMarker(this._lat, this._lng);
        }
        this._map.on("click", (e) => this._onMapClick(e));
        // Map mounts inside a form group that may size late; recompute
        // tile layout after first paint.
        setTimeout(() => this._map && this._map.invalidateSize(), 200);
    }

    _setMarker(lat, lng) {
        const L = window.L;
        if (this._marker) {
            this._marker.setLatLng([lat, lng]);
            return;
        }
        this._marker = L.marker([lat, lng], { draggable: true })
            .addTo(this._map);
        this._marker.on("dragend", () => {
            const p = this._marker.getLatLng();
            this._commit(p.lat, p.lng);
        });
    }

    _commit(lat, lng) {
        this.state.interacted = true;
        // Round to 7 dp (matches base partner_latitude digits=(10,7)).
        const rlat = Math.round(lat * 1e7) / 1e7;
        const rlng = Math.round(lng * 1e7) / 1e7;
        this.props.record.update({
            partner_latitude: rlat,
            partner_longitude: rlng,
        });
    }

    _onMapClick(e) {
        this._setMarker(e.latlng.lat, e.latlng.lng);
        this._commit(e.latlng.lat, e.latlng.lng);
    }

    onSearchInput(ev) {
        this.state.query = ev.target.value;
        if (this._searchTimer) {
            clearTimeout(this._searchTimer);
        }
        // D8: 1000ms debounce -> stays under Nominatim's 1 req/sec.
        this._searchTimer = setTimeout(() => this._runSearch(), 1000);
    }

    async _runSearch() {
        const q = (this.state.query || "").trim();
        if (!q) {
            this.state.results = [];
            return;
        }
        if (this._abort) {
            this._abort.abort();  // D8: cancel in-flight on new keystroke
        }
        this._abort = new AbortController();
        this.state.searching = true;
        try {
            // Note (DECISION M9.1.1.1): Nominatim's policy asks for a
            // User-Agent, but browsers FORBID setting User-Agent on
            // fetch. The request carries the browser UA + the
            // crm.neonhiring.com Referer, which identifies the app --
            // the closest honour of the policy available client-side.
            const url = `${NOMINATIM}?format=json&limit=5`
                + `&q=${encodeURIComponent(q)}`;
            const resp = await fetch(url, {
                signal: this._abort.signal,
                headers: { Accept: "application/json" },
            });
            const data = await resp.json();
            this.state.results = (data || []).slice(0, 5).map((r) => ({
                label: r.display_name,
                lat: parseFloat(r.lat),
                lng: parseFloat(r.lon),
            }));
        } catch (e) {
            if (e.name !== "AbortError") {
                this.state.results = [];
            }
        } finally {
            this.state.searching = false;
        }
    }

    onResultClick(r) {
        this.state.results = [];
        this.state.query = r.label;
        this._map.setView([r.lat, r.lng], 16);
        this._setMarker(r.lat, r.lng);
        this._commit(r.lat, r.lng);
    }
}

export const neonVenuePinPicker = { component: NeonVenuePinPicker };
registry.category("view_widgets").add(
    "neon_venue_pin_picker", neonVenuePinPicker);
