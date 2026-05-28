/** @odoo-module **/

/**
 * P9.M9.1 -- neon_venue_map_iframe view-widget (form widget).
 *
 * P9.M9.2 refactor: render logic lifted into NeonVenueMapView. This
 * class now just resolves form-record fields into View props so the
 * M9.2 dashboard modal can reuse the same view component without
 * dragging a form record through.
 */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { NeonVenueMapView } from "@neon_jobs/js/venue_map/venue_map_view";

export class NeonVenueMap extends Component {
    static template = "neon_jobs.NeonVenueMapIframe";
    static components = { NeonVenueMapView };
    static props = { ...standardWidgetProps };

    get _data() {
        return (this.props.record && this.props.record.data) || {};
    }

    get latitude() {
        return this._data.venue_latitude || 0;
    }

    get longitude() {
        return this._data.venue_longitude || 0;
    }

    get fullAddress() {
        return this._data.venue_full_address || "";
    }
}

export const neonVenueMapIframe = {
    component: NeonVenueMap,
};

registry.category("view_widgets").add(
    "neon_venue_map_iframe", neonVenueMapIframe);
