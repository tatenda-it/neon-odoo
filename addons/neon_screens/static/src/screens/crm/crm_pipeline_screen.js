/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * CRM Pipeline — design-deck screen #5. Read-only kanban over the REAL live
 * crm.lead / crm.stage pipeline, grouped by the LIVE stages (never hardcoded),
 * read under the user's own CRM ACL. Source shown as a per-card badge where set
 * (verified empty today) + an honest coverage chip. No crm.stage change.
 */
export class CrmPipelineScreen extends Component {
    static template = "neon_screens.CrmPipelineScreen";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, loading: true, error: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("neon.crm.pipeline.screen", "get_data", []);
        } catch (e) {
            this.state.error = (e && e.message) || String(e);
        }
        this.state.loading = false;
    }

    get d() { return this.state.data || {}; }
    get totals() { return this.d.totals || {}; }

    openLead(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "crm.lead",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("neon_crm_pipeline_screen", CrmPipelineScreen);
