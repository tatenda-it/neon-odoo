/** @odoo-module **/

import {
    Component,
    onMounted,
    onWillStart,
    onWillUnmount,
    useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * Workshop Overview — Neon Events Elements (P5.M10).
 *
 * 10-tile live dashboard for workshop operations. Tiles render from
 * a single RPC call to `neon.equipment.dashboard.get_dashboard_data`
 * and refresh on a 60-second timer that pauses while the tab is
 * inactive (Page Visibility API).
 *
 * Each tile click routes through `action` service `doAction()` with
 * the per-tile action_id returned by the RPC, opening the
 * corresponding filtered list view of the underlying records.
 */
export class WorkshopDashboard extends Component {
    static template = "neon_jobs.WorkshopDashboard";
    static props = {
        "*": true,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            data: null,
            loading: true,
            error: null,
        });

        this._refreshInterval = null;
        this._visibilityHandler = null;
        this.REFRESH_MS = 60_000;

        onWillStart(async () => {
            await this.loadData();
        });

        onMounted(() => {
            this._startAutoRefresh();
            this._visibilityHandler = () => {
                if (document.hidden) {
                    this._stopAutoRefresh();
                } else {
                    // Tab returned to foreground — refresh immediately
                    // and resume the timer.
                    this.loadData();
                    this._startAutoRefresh();
                }
            };
            document.addEventListener(
                "visibilitychange", this._visibilityHandler);
        });

        onWillUnmount(() => {
            this._stopAutoRefresh();
            if (this._visibilityHandler) {
                document.removeEventListener(
                    "visibilitychange", this._visibilityHandler);
                this._visibilityHandler = null;
            }
        });
    }

    async loadData() {
        this.state.error = null;
        try {
            const data = await this.orm.call(
                "neon.equipment.dashboard",
                "get_dashboard_data",
                [],
            );
            this.state.data = data;
            this.state.loading = false;
        } catch (e) {
            this.state.error = (e && e.message) || String(e);
            this.state.loading = false;
        }
    }

    _startAutoRefresh() {
        this._stopAutoRefresh();
        this._refreshInterval = setInterval(
            () => this.loadData(), this.REFRESH_MS);
    }

    _stopAutoRefresh() {
        if (this._refreshInterval) {
            clearInterval(this._refreshInterval);
            this._refreshInterval = null;
        }
    }

    async onTileClick(tileKey) {
        const tile = this.state.data && this.state.data[tileKey];
        if (!tile || !tile.action_id) {
            return;
        }
        await this.action.doAction(tile.action_id);
    }

    onRefreshClick() {
        this.state.loading = true;
        this.loadData();
    }

    /**
     * Layout descriptors for the two tile groups. Built from the RPC
     * payload at render time. Urgency drives the tile border colour
     * (normal / attention / critical) declared in the SCSS.
     */
    get tiles() {
        const d = this.state.data || {};
        const v = (k) => (d[k] && d[k].value) || 0;
        return {
            inventory: [
                {
                    key: "active_units",
                    title: _t("Active Units"),
                    subtitle: _t("In service, available"),
                    icon: "fa-check-circle",
                    urgency: "normal",
                    value: v("active_units"),
                },
                {
                    key: "units_out",
                    title: _t("Units Out"),
                    subtitle: _t("Checked out with crew"),
                    icon: "fa-truck",
                    urgency: "normal",
                    value: v("units_out"),
                },
                {
                    key: "reservations_next_7days",
                    title: _t("Reservations — 7 Days"),
                    subtitle: _t("Upcoming holds"),
                    icon: "fa-calendar",
                    urgency: "normal",
                    value: v("reservations_next_7days"),
                },
                {
                    key: "pending_transfers",
                    title: _t("Pending Transfers"),
                    subtitle: _t("Awaiting acceptance"),
                    icon: "fa-exchange",
                    urgency: "attention",
                    value: v("pending_transfers"),
                },
                {
                    key: "late_returns",
                    title: _t("Late Returns"),
                    subtitle: _t("Units still out post-event"),
                    icon: "fa-clock-o",
                    urgency: "attention",
                    value: v("late_returns"),
                },
            ],
            attention: [
                {
                    key: "equipment_conflicts_open",
                    title: _t("Equipment Conflicts"),
                    subtitle: _t("Open or in progress"),
                    icon: "fa-exclamation-triangle",
                    urgency: "attention",
                    value: v("equipment_conflicts_open"),
                },
                {
                    key: "stock_discrepancies_open",
                    title: _t("Stock Discrepancies"),
                    subtitle: _t("Unresolved"),
                    icon: "fa-list-alt",
                    urgency: "attention",
                    value: v("stock_discrepancies_open"),
                },
                {
                    key: "repair_orders_open",
                    title: _t("Repair Orders"),
                    subtitle: _t("In workflow"),
                    icon: "fa-wrench",
                    urgency: "attention",
                    value: v("repair_orders_open"),
                },
                {
                    key: "incidents_open",
                    title: _t("Incidents"),
                    subtitle: _t("Open + under investigation"),
                    icon: "fa-fire",
                    urgency: "critical",
                    value: v("incidents_open"),
                },
                {
                    key: "high_impact_30d",
                    title: _t("High-Impact — 30 Days"),
                    subtitle: _t("Audit count, rolling window"),
                    icon: "fa-bolt",
                    urgency: "critical",
                    value: v("high_impact_30d"),
                },
            ],
        };
    }

    get lastUpdated() {
        return (this.state.data && this.state.data.last_updated) || "";
    }
}

registry.category("actions").add(
    "neon_workshop_dashboard", WorkshopDashboard);
