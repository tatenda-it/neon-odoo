/** @odoo-module **/

/**
 * P9.M9.3 -- NeonVenueMultiPinMap.
 *
 * Two-pane "Venues · Map" client action. Left pane: filterable
 * venue list (search + Mapped/Unmapped/All chips). Right pane:
 * Leaflet multi-pin map with bindPopup-based pin -> partner form
 * navigation.
 *
 * Architecture (D6, locked): fork — NOT extending NeonVenuePinPicker.
 * Phase 9 is sealing; refactoring M9.1.1 (3/3 browser smokes green)
 * carries unacceptable regression risk. ~30 LOC of Leaflet bootstrap
 * (tile layer URL, attribution, imagePath, HARARE constant,
 * invalidateSize) duplicate from venue_pin.js. Consolidation deferred
 * to Phase 10 hardening (memory tag: leaflet-bootstrap-consolidation-
 * deferred).
 */
import {
    Component, onMounted, onWillUnmount, useEffect, useRef, useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const HARARE = [-17.8252, 31.0335];   // default centre (matches M9.1.1)
const SEARCH_DEBOUNCE_MS = 200;       // D9

export class NeonVenueMultiPinMap extends Component {
    static template = "neon_jobs.NeonVenueMultiPinMap";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            venues: [],
            search: "",
            filter: "all",       // "all" | "mapped" | "unmapped"
            selectedId: null,
            loading: true,
            error: null,
        });

        this.mapRef = useRef("map");
        this._map = null;
        this._markers = [];
        this._featureGroup = null;
        this._searchTimer = null;
        this._popupClickHandler = null;

        onMounted(() => this._loadData());

        // ⚠️ DECISION (M9.3, marker 2): _initMap runs through a
        // useEffect keyed on (loading=false, mapRef.el present)
        // because the <div t-ref="map"> is rendered inside a
        // <t t-if="!state.loading">. The map ref is null on first
        // mount and only becomes the DOM node on the re-render
        // after _loadData flips loading=false. Calling _initMap
        // inline after the await would hit a null ref.
        useEffect(
            (el, loading) => {
                if (el && !loading && !this._map) {
                    this._initMap();
                    this._renderMarkers();
                }
            },
            () => [this.mapRef.el, this.state.loading],
        );

        onWillUnmount(() => {
            if (this._searchTimer) {
                clearTimeout(this._searchTimer);
            }
            if (this._popupClickHandler && this.mapRef.el) {
                this.mapRef.el.removeEventListener(
                    "click", this._popupClickHandler);
            }
            if (this._map) {
                this._map.remove();
                this._map = null;
            }
        });
    }

    // ==================================================================
    // Data loading -- D10.
    // ==================================================================
    async _loadData() {
        try {
            // D5: exclude the TBD placeholder + TEST-DELETE venues.
            // ref() isn't available client-side, so we match the TBD
            // partner by its literal name.
            this.state.venues = await this.orm.searchRead(
                "res.partner",
                [
                    ["is_venue", "=", true],
                    ["name", "not ilike", "TEST-DELETE"],
                    ["name", "!=", "TBD — Set Venue"],
                ],
                [
                    "id", "name", "city", "country_id",
                    "partner_latitude", "partner_longitude",
                    "coords_source",
                ],
            );
        } catch (e) {
            this.state.error = (e && e.message) || String(e);
        }
        this.state.loading = false;
        // _initMap runs via the useEffect keyed on (mapRef.el,
        // state.loading) once the template re-render mounts the
        // map div.
    }

    // ==================================================================
    // Leaflet bootstrap -- duplicates ~30 LOC from venue_pin.js per
    // D6 fork architecture. Consolidation deferred.
    // ==================================================================
    _initMap() {
        const L = window.L;
        if (!L || !this.mapRef.el) {
            return;
        }
        // Inherit imagePath set by venue_pin.js earlier in the bundle.
        // Set it again defensively in case load order ever shifts.
        L.Icon.Default.imagePath = "/neon_jobs/static/lib/leaflet/images/";
        this._map = L.map(this.mapRef.el).setView(HARARE, 11);
        L.tileLayer(
            "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            {
                maxZoom: 19,
                attribution:
                    '© <a href="https://www.openstreetmap.org/copyright">'
                    + "OpenStreetMap</a> contributors",
            },
        ).addTo(this._map);

        // D3 popup link click via event delegation. Leaflet popups
        // mount into the same .leaflet-popup-pane inside the map
        // container, so a single delegated handler covers all of them.
        this._popupClickHandler = (ev) => {
            const a = ev.target.closest(".o_neon_venue_popup_open");
            if (!a) {
                return;
            }
            ev.preventDefault();
            const pid = parseInt(a.dataset.partnerId, 10);
            if (pid) {
                this._openPartner(pid);
            }
        };
        this.mapRef.el.addEventListener("click", this._popupClickHandler);

        // Recompute tiles after first paint (matches M9.1.1 line 109).
        setTimeout(() => this._map && this._map.invalidateSize(), 200);
    }

    // ==================================================================
    // Marker rendering -- D7.
    // ==================================================================
    _renderMarkers() {
        if (!this._map) {
            return;
        }
        const L = window.L;
        // Clear previous markers + featureGroup.
        if (this._featureGroup) {
            this._featureGroup.clearLayers();
            this._map.removeLayer(this._featureGroup);
            this._featureGroup = null;
        }
        this._markers = [];

        const visible = this.getFilteredVenues();
        const mappable = visible.filter(
            (v) => v.partner_latitude && v.partner_longitude);

        for (const v of mappable) {
            const m = L.marker([v.partner_latitude, v.partner_longitude]);
            m.bindPopup(this._popupHtml(v));
            // Track which venue this marker corresponds to so list-row
            // clicks can open its popup.
            m._neonVenueId = v.id;
            this._markers.push(m);
        }

        if (mappable.length === 0) {
            // Nothing to fit; centre on Harare default.
            this._map.setView(HARARE, 11);
            return;
        }
        this._featureGroup = L.featureGroup(this._markers).addTo(this._map);
        if (mappable.length === 1) {
            const v = mappable[0];
            this._map.setView(
                [v.partner_latitude, v.partner_longitude], 14);
        } else {
            this._map.fitBounds(
                this._featureGroup.getBounds().pad(0.1));
        }
    }

    _popupHtml(venue) {
        // D3 popup markup. Inline strings -- Leaflet's bindPopup takes
        // an HTML string. We sanitise by template-literal interpolation
        // of plain text only (no user-supplied HTML); names/cities are
        // text-safe at the DB layer.
        const safeName = this._escape(venue.name || "");
        const safeCity = this._escape(venue.city || "");
        const cityLine = safeCity
            ? `<div class="o_neon_venue_popup_city">${safeCity}</div>`
            : "";
        return (
            `<div class="o_neon_venue_popup">`
            + `<strong>${safeName}</strong>`
            + cityLine
            + `<a href="#" class="o_neon_venue_popup_open" `
            + `data-partner-id="${venue.id}">Open venue →</a>`
            + `</div>`
        );
    }

    _escape(s) {
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    // ==================================================================
    // Filtering -- D9.
    // ==================================================================
    isMapped(v) {
        return !!(v.partner_latitude && v.partner_longitude);
    }

    getFilteredVenues() {
        const q = (this.state.search || "").trim().toLowerCase();
        return (this.state.venues || []).filter((v) => {
            if (q) {
                const name = (v.name || "").toLowerCase();
                const city = (v.city || "").toLowerCase();
                if (!name.includes(q) && !city.includes(q)) {
                    return false;
                }
            }
            if (this.state.filter === "mapped" && !this.isMapped(v)) {
                return false;
            }
            if (this.state.filter === "unmapped" && this.isMapped(v)) {
                return false;
            }
            return true;
        });
    }

    get mappedCount() {
        return (this.state.venues || []).filter(
            (v) => this.isMapped(v)).length;
    }

    get unmappedCount() {
        return (this.state.venues || []).length - this.mappedCount;
    }

    get hasUnmappedSelection() {
        if (!this.state.selectedId) {
            return false;
        }
        const v = (this.state.venues || []).find(
            (x) => x.id === this.state.selectedId);
        return !!(v && !this.isMapped(v));
    }

    coordState(v) {
        if (this.isMapped(v)) {
            return "mapped";
        }
        if (v.city || (v.country_id && v.country_id.length)) {
            return "address";
        }
        return "empty";
    }

    coordBadgeLabel(v) {
        const s = this.coordState(v);
        if (s === "mapped") return "Mapped";
        if (s === "address") return "Address only";
        return "No location";
    }

    cityCountry(v) {
        const city = v.city || "";
        const country = (v.country_id && v.country_id.length === 2)
            ? v.country_id[1] : "";
        if (city && country) return `${city}, ${country}`;
        return city || country || "";
    }

    // ==================================================================
    // Event handlers.
    // ==================================================================
    onSearchInput(ev) {
        const value = ev.target.value;
        if (this._searchTimer) {
            clearTimeout(this._searchTimer);
        }
        this._searchTimer = setTimeout(() => {
            this.state.search = value;
            this._renderMarkers();
        }, SEARCH_DEBOUNCE_MS);
    }

    onChipClick(chip) {
        this.state.filter = chip;
        this._renderMarkers();
    }

    onListRowClick(venue) {
        this.state.selectedId = venue.id;
        if (this.isMapped(venue)) {
            // Pan+zoom to the marker and open its popup. We search
            // _markers (the rendered set after filter) so the popup
            // exists; if the active filter hides this venue's marker
            // we re-render before opening.
            let marker = this._markers.find(
                (m) => m._neonVenueId === venue.id);
            if (!marker) {
                // Force the marker into view by widening to "all".
                this.state.filter = "all";
                this._renderMarkers();
                marker = this._markers.find(
                    (m) => m._neonVenueId === venue.id);
            }
            if (marker && this._map) {
                this._map.setView(
                    [venue.partner_latitude, venue.partner_longitude],
                    15);
                marker.openPopup();
            }
        }
        // Unmappable selections trigger the hint overlay via
        // hasUnmappedSelection (template-driven, no JS action needed).
    }

    onPopupLinkClick(partnerId) {
        // Reserved for unit tests; live popup clicks go through the
        // delegated handler in _initMap.
        this._openPartner(partnerId);
    }

    _openPartner(partnerId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: partnerId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    onOpenSelectedClick() {
        // Hint-state CTA: open the form for the currently-selected
        // unmapped venue so the user can geocode it.
        if (this.state.selectedId) {
            this._openPartner(this.state.selectedId);
        }
    }
}

registry.category("actions").add(
    "neon_venue_multi_map", NeonVenueMultiPinMap);
