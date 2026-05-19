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
 * Cash Flow Dashboard -- Neon Events Elements (P6.M10).
 *
 * 6-tile finance dashboard. Tiles render from a single RPC call to
 * `neon.finance.dashboard.get_cash_flow_dashboard_data` and refresh
 * on a 5-minute timer that pauses while the tab is inactive (Page
 * Visibility API). Mirrors the P5.M10 Workshop Dashboard pattern
 * with two structural differences:
 *
 * 1. Per-currency rendering: each tile shows USD + ZWG side-by-side.
 *    Mixed-currency totals are forbidden (Q6 B1).
 * 2. Role-degraded rendering: when a tile returns null for a
 *    currency (crew_leader on the receivables tile), the template
 *    renders "--" with no click handler. Layout stable.
 *
 * Each tile click routes through the `action` service `doAction()`
 * with the per-tile action_id returned by the RPC.
 */
export class NeonCashFlowDashboard extends Component {
    static template = "neon_finance.NeonCashFlowDashboard";
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
        // 5 minutes per design (vs Workshop's 60s). Finance data
        // changes less frequently than workshop inventory.
        this.REFRESH_MS = 5 * 60 * 1000;

        onWillStart(async () => {
            await this.loadData();
        });

        onMounted(() => {
            this._startAutoRefresh();
            this._visibilityHandler = () => {
                if (document.hidden) {
                    this._stopAutoRefresh();
                } else {
                    // Tab returned to foreground: refresh
                    // immediately and resume the timer.
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
                "neon.finance.dashboard",
                "get_cash_flow_dashboard_data",
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

    async onTileClick(actionId) {
        // Falsy action_id = no click handler (crew_leader degraded
        // tiles, or top_overdue with empty rows).
        if (!actionId) {
            return;
        }
        await this.action.doAction(actionId);
    }

    onRefreshClick() {
        this.state.loading = true;
        this.loadData();
    }

    // ============================================================
    // === Currency formatting helpers
    // ============================================================
    fmtUsd(val) {
        if (val === null || val === undefined) return "--";
        return "$" + this._fmtNumber(val);
    }

    fmtZwg(val) {
        if (val === null || val === undefined) return "--";
        return "Z$" + this._fmtNumber(val);
    }

    _fmtNumber(val) {
        return Number(val).toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    // ============================================================
    // === Tile descriptors -- built from RPC payload at render time
    // ============================================================
    get tile_outstanding() {
        const d = this.state.data || {};
        return d.outstanding_receivables || {
            usd: null, zwg: null, action_id: false,
        };
    }

    get tile_pipeline() {
        const d = this.state.data || {};
        return d.pipeline || {
            usd: null, zwg: null, action_id: false,
        };
    }

    get tile_recent_payments() {
        const d = this.state.data || {};
        return d.recent_payments || {
            usd: null, zwg: null, action_id: false,
        };
    }

    get tile_recent_costs() {
        const d = this.state.data || {};
        return d.recent_costs || {
            usd: null, zwg: null, action_id: false,
        };
    }

    get tile_top_overdue() {
        const d = this.state.data || {};
        return d.top_overdue || { rows: [], action_id: false };
    }

    get tile_budget_alerts() {
        const d = this.state.data || {};
        return d.budget_alert_summary || {
            levels: { ok: 0, warn: 0, breach: 0, severe: 0 },
            action_id: false,
        };
    }

    get lastUpdated() {
        return (this.state.data && this.state.data.last_updated) || "";
    }

    get userRole() {
        return (this.state.data && this.state.data.role) || "";
    }
}

registry.category("actions").add(
    "neon_cash_flow_dashboard", NeonCashFlowDashboard);
