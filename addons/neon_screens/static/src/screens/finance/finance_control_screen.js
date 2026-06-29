/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Finance Control — design-deck screen #4. Read-only presentation over the REAL
 * live finance data, read under the user's own finance ACL (no sudo). Panels:
 * KPI row + Weekly Cash Planning board (neon.weekly.budget), Event Costing
 * Variance (commercial.event.job costing fields), Approvals
 * (neon.finance.approval), and a static Governance/Controls card.
 */
export class FinanceControlScreen extends Component {
    static template = "neon_screens.FinanceControlScreen";
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
            this.state.data = await this.orm.call(
                "neon.finance.control.screen", "get_data", []);
        } catch (e) {
            this.state.error = (e && e.message) || String(e);
        }
        this.state.loading = false;
    }

    get d() { return this.state.data || {}; }
    get constants() { return this.d.constants || {}; }
    get counts() { return this.d.counts || {}; }

    toneClass(tone) {
        return {
            ok: "text-bg-success", warn: "text-bg-warning", alert: "text-bg-danger",
            muted: "text-bg-secondary", info: "text-bg-info", dark: "text-bg-dark",
        }[tone] || "text-bg-secondary";
    }

    openEventJob(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "commercial.event.job",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }
    openApproval(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "neon.finance.approval",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("neon_finance_control_screen", FinanceControlScreen);
