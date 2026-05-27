/** @odoo-module **/

/**
 * P9.M9.1 -- neon_venue_map_iframe view-widget.
 *
 * Embedded Google Maps iframe on the commercial.event.job Venue page.
 * Reads venue_latitude / venue_longitude / venue_full_address off the
 * form datapoint and builds the keyless Maps Embed URL client-side
 * (D5). No API key: the /maps?q=...&output=embed form is free.
 */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class NeonVenueMap extends Component {
    static template = "neon_jobs.NeonVenueMapIframe";
    static props = { ...standardWidgetProps };

    get _data() {
        return (this.props.record && this.props.record.data) || {};
    }

    get hasCoords() {
        const d = this._data;
        // D5: lat==0 && lng==0 means "unset" (Harare venues are nowhere
        // near 0,0), so treat zero coords as no-fix and fall to address.
        return !!(d.venue_latitude && d.venue_longitude);
    }

    get hasLocation() {
        return this.hasCoords || !!this._data.venue_full_address;
    }

    get iframeUrl() {
        const d = this._data;
        if (this.hasCoords) {
            return (
                "https://www.google.com/maps?q=" +
                d.venue_latitude + "," + d.venue_longitude +
                "&z=15&output=embed"
            );
        }
        const addr = d.venue_full_address || "";
        return (
            "https://www.google.com/maps?q=" +
            encodeURIComponent(addr) + "&z=15&output=embed"
        );
    }

    get directionsUrl() {
        // D5/item7: "Get directions" deep-link. Prefer coords; else
        // fall back to the address query. Keyless Maps URL.
        const d = this._data;
        const dest = this.hasCoords
            ? d.venue_latitude + "," + d.venue_longitude
            : (d.venue_full_address || "");
        return (
            "https://www.google.com/maps/dir/?api=1&destination=" +
            encodeURIComponent(dest)
        );
    }
}

export const neonVenueMapIframe = {
    component: NeonVenueMap,
};

registry.category("view_widgets").add(
    "neon_venue_map_iframe", neonVenueMapIframe);
