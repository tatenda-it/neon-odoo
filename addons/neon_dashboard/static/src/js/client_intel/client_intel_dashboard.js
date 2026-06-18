/** @odoo-module **/

/**
 * L2.1 — Client / Account Intelligence dashboard (read-only).
 *
 * A standalone Owl client action (tag "neon_client_intel_dashboard") rendering
 * the five ranking blocks over neon.client.intel, with the existing AI chat
 * panel embedded. Reads via a single get_dashboard_data RPC on mount; the
 * server gates the sensitive outstanding block + the chat-eligibility flag.
 * This component never writes — it only displays the computed rollups.
 */
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { NeonAiChat } from "@neon_dashboard/js/ai_chat/ai_chat";

export class NeonClientIntelDashboard extends Component {
    static template = "neon_dashboard.NeonClientIntelDashboard";
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
                    "neon.client.intel", "get_dashboard_data", []);
            } catch (e) {
                this.state.error =
                    (e && e.data && e.data.message) ||
                    (e && e.message && e.message.data &&
                        e.message.data.message) ||
                    "Unable to load client intelligence.";
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
    "neon_client_intel_dashboard", NeonClientIntelDashboard);
