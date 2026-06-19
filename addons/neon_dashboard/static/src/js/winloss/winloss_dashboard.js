/** @odoo-module **/

/**
 * L2.3 — Realisation & Win/Loss dashboard (read-only).
 *
 * Standalone Owl client action (tag "neon_winloss_dashboard"): win-rate by
 * rep / category / period / client AND the quoted→won→invoiced realisation
 * flow, over neon.winloss.intel. One get_dashboard_data RPC on mount; embeds
 * the existing AI chat panel. Never writes — displays computed rollups only.
 */
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { NeonAiChat } from "@neon_dashboard/js/ai_chat/ai_chat";

export class NeonWinlossDashboard extends Component {
    static template = "neon_dashboard.NeonWinlossDashboard";
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
                    "neon.winloss.intel", "get_dashboard_data", []);
            } catch (e) {
                this.state.error =
                    (e && e.data && e.data.message) ||
                    (e && e.message && e.message.data &&
                        e.message.data.message) ||
                    "Unable to load win/loss & realisation.";
            }
            this.state.loading = false;
        });
    }

    get activeVariant() {
        return (this.state.data && this.state.data.variant) || "";
    }

    onChatToggle(nextExpanded) {
        this.state.chatExpanded = !!nextExpanded;
    }

    fmt(n) {
        return (n || 0).toLocaleString();
    }
}

registry.category("actions").add(
    "neon_winloss_dashboard", NeonWinlossDashboard);
