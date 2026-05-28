/** @odoo-module **/

/**
 * P9.M9.2 -- NeonVenueMapView presentational component.
 *
 * Stateless OWL component that renders a Google Maps embed iframe
 * (when coords or address are present) or an inline placeholder
 * (when neither is set). Same hasCoords / hasLocation gating as
 * the M9.1 NeonVenueMap form widget, lifted out so both the form
 * widget and the M9.2 dashboard modal can share one render path.
 *
 * Props: latitude (Number), longitude (Number), fullAddress (String).
 */
import { Component } from "@odoo/owl";

export class NeonVenueMapView extends Component {
    static template = "neon_jobs.NeonVenueMapView";
    static props = {
        latitude: { type: Number, optional: true },
        longitude: { type: Number, optional: true },
        fullAddress: { type: String, optional: true },
    };

    get hasCoords() {
        // D5 (M9.1): lat==0 && lng==0 means "unset" (Harare venues
        // are nowhere near 0,0), so treat zero coords as no-fix.
        return !!(this.props.latitude && this.props.longitude);
    }

    get hasLocation() {
        return this.hasCoords || !!this.props.fullAddress;
    }

    get iframeUrl() {
        if (this.hasCoords) {
            return (
                "https://www.google.com/maps?q=" +
                this.props.latitude + "," + this.props.longitude +
                "&z=15&output=embed"
            );
        }
        const addr = this.props.fullAddress || "";
        return (
            "https://www.google.com/maps?q=" +
            encodeURIComponent(addr) + "&z=15&output=embed"
        );
    }

    get directionsUrl() {
        const dest = this.hasCoords
            ? this.props.latitude + "," + this.props.longitude
            : (this.props.fullAddress || "");
        return (
            "https://www.google.com/maps/dir/?api=1&destination=" +
            encodeURIComponent(dest)
        );
    }
}
