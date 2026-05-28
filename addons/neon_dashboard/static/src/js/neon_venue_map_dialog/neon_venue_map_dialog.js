/** @odoo-module **/

/**
 * P9.M9.2 -- NeonVenueMapDialog. Wraps the NeonVenueMapView render
 * component inside an Odoo Dialog so the dashboard Jobs block pin
 * can open a mini-map popup without leaving the dashboard. First
 * Dialog-service consumer in neon_dashboard; future modal needs
 * (e.g. M9.3 multi-pin overview) can mirror this pattern.
 */
import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { NeonVenueMapView } from "@neon_jobs/js/venue_map/venue_map_view";

export class NeonVenueMapDialog extends Component {
    static template = "neon_dashboard.NeonVenueMapDialog";
    static components = { Dialog, NeonVenueMapView };
    static props = {
        close: Function,
        title: { type: String, optional: true },
        latitude: { type: Number, optional: true },
        longitude: { type: Number, optional: true },
        fullAddress: { type: String, optional: true },
    };
    static defaultProps = {
        title: "Venue",
        latitude: 0,
        longitude: 0,
        fullAddress: "",
    };
}
