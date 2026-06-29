/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Equipment & Inventory — Neon design-deck screen #1.
 *
 * Read-only composed screen over the live equipment domain. One RPC to
 * `neon.equipment.screen.get_screen_data` feeds three sections:
 *   - the conflict / sub-hire alert card (latest run; honest "all clear"),
 *   - the per-item availability list (Owned / Committed / Available + a
 *     status pill sourced from the conflict run),
 *   - the per-asset register (Asset ID / Item / Category / State pill).
 */
export class EquipmentScreen extends Component {
    static template = "neon_screens.EquipmentScreen";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            data: null,
            loading: true,
            error: null,
            tab: "availability",
        });
        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        this.state.error = null;
        try {
            this.state.data = await this.orm.call(
                "neon.equipment.screen", "get_screen_data", []);
            this.state.loading = false;
        } catch (e) {
            this.state.error = (e && e.message) || String(e);
            this.state.loading = false;
        }
    }

    onRefresh() {
        this.state.loading = true;
        this.loadData();
    }

    setTab(tab) {
        this.state.tab = tab;
    }

    toneClass(tone) {
        return {
            ok: "text-bg-success",
            warn: "text-bg-warning",
            alert: "text-bg-danger",
            muted: "text-bg-secondary",
        }[tone] || "text-bg-secondary";
    }

    get summary() {
        return (this.state.data && this.state.data.summary) || {};
    }
    get availability() {
        return (this.state.data && this.state.data.availability) || [];
    }
    get assets() {
        return (this.state.data && this.state.data.assets) || [];
    }
    get conflict() {
        return (this.state.data && this.state.data.conflict) || { exists: false };
    }
    get isClear() {
        const c = this.conflict;
        return !c.exists || c.overall_status === "clear";
    }
    get lastUpdated() {
        return (this.state.data && this.state.data.last_updated) || "";
    }
}

registry.category("actions").add("neon_equipment_screen", EquipmentScreen);
