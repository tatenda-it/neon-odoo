/** @odoo-module **/

/**
 * L2.2 — Demand & Seasonality dashboard (read-only).
 *
 * Standalone Owl client action (tag "neon_demand_dashboard"): the monthly
 * demand curve, seasonality (avg by calendar month), year-over-year totals,
 * and the recurring named-events list — over neon.demand.intel /
 * neon.demand.recurring. One get_dashboard_data RPC on mount; embeds the
 * existing AI chat panel. Never writes — displays the computed rollups only.
 */
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { NeonAiChat } from "@neon_dashboard/js/ai_chat/ai_chat";

export class NeonDemandDashboard extends Component {
    static template = "neon_dashboard.NeonDemandDashboard";
    static components = { NeonAiChat };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            error: null,
            data: null,
            chatExpanded: false,
        });
        onWillStart(async () => {
            try {
                this.state.data = await this.orm.call(
                    "neon.demand.intel", "get_dashboard_data", []);
            } catch (e) {
                this.state.error =
                    (e && e.data && e.data.message) ||
                    (e && e.message && e.message.data &&
                        e.message.data.message) ||
                    "Unable to load demand & seasonality.";
            }
            this.state.loading = false;
        });
    }

    get activeVariant() {
        return (this.state.data && this.state.data.variant) || "";
    }

    // max jobs in the seasonality set, for the bar widths
    get maxSeasonJobs() {
        const s = this.state.data && this.state.data.seasonality;
        if (!s || !s.length) {
            return 1;
        }
        return Math.max(1, ...s.map((m) => m.jobs_total));
    }

    barPct(v) {
        return Math.round((100 * (v || 0)) / this.maxSeasonJobs);
    }

    onChatToggle(nextExpanded) {
        this.state.chatExpanded = !!nextExpanded;
    }

    fmt(n) {
        return (n || 0).toLocaleString();
    }
}

registry.category("actions").add(
    "neon_demand_dashboard", NeonDemandDashboard);
