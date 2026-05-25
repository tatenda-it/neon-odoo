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
 * Neon Dashboard root component (Phase 8A M1-M3).
 *
 * Mirrors the P6.M10 Cash Flow Dashboard scaffold:
 *
 * - Single get_dashboard_data RPC on mount + on dashboard_type flip.
 * - 5-minute auto-refresh that pauses on tab-hidden.
 * - Loading skeleton on first paint, error banner on RPC failure.
 *
 * Phase 8B will add an Edit-Layout sub-component; for M1-M3 the
 * "Edit Layout" button shows a toast and the View-filter chips
 * (Operations / Sales / Finance) show "coming in M5/M6" toasts.
 *
 * ⚠️ DECISION (M1, marker 1 reinforced client-side): the OWL
 * component talks to a virtual model via the ORM service. NO direct
 * /neon/... HTTP route. The route the prompt sketched is replaced by
 * orm.call("neon.dashboard", "get_dashboard_data", []).
 */
export class NeonDashboard extends Component {
    static template = "neon_dashboard.NeonDashboard";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            error: null,
            data: null,
            activeFilter: "all",
        });

        // 5-minute auto-refresh (same cadence as cash_flow_dashboard;
        // dashboard data sources change minute-to-minute at most).
        this.REFRESH_MS = 5 * 60 * 1000;
        this._refreshInterval = null;
        this._visibilityHandler = null;

        onWillStart(async () => {
            await this.loadData();
        });

        onMounted(() => {
            this._startAutoRefresh();
            this._visibilityHandler = () => {
                if (document.hidden) {
                    this._stopAutoRefresh();
                } else {
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

    async loadData(dashboardType = null) {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call(
                "neon.dashboard",
                "get_dashboard_data",
                [],
                { dashboard_type: dashboardType },
            );
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

    onRefreshClick() {
        this.loadData(
            (this.state.data && this.state.data.dashboard_type) || null);
    }

    onViewAsChange(ev) {
        const newType = (ev && ev.target && ev.target.value) || null;
        if (!newType) return;
        this.loadData(newType);
    }

    onFilterChange(filter) {
        // M6: "all", "operations", "sales", "finance" all functional.
        // The Finance chip drives a Bookkeeper-style view (Cash + AR
        // + Forecast KPI + Finance block visible; Jobs/Sales/Crew
        // hidden).
        this.state.activeFilter = filter;
    }

    onEditLayoutClick() {
        // Edit-Layout UI lands in Phase 8B M5. For M1-M3, we keep the
        // pencil visible (mockup parity) and stub the action.
        this.notification.add(
            _t("Edit Layout ships in Phase 8B M5."),
            { type: "info" });
    }

    async onKpiClick(kpi) {
        // KPI tiles deep-link to a stock or Neon action xmlid; empty-
        // state tiles return false for deeplink_action and become
        // no-ops.
        if (!kpi || !kpi.deeplink_action) {
            return;
        }
        await this.action.doAction(kpi.deeplink_action);
    }

    async onJobClick(row) {
        if (!row || !row.deeplink_id) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "commercial.event.job",
            res_id: row.deeplink_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async onEmptyJobsClick() {
        const data = this.state.data;
        if (!data || !data.jobs_block) return;
        const xmlid = data.jobs_block.empty_cta_action;
        if (xmlid) {
            await this.action.doAction(xmlid);
        }
    }

    // ------------------------------------------------------------------
    // M4 -- Crew & Equipment block handlers.
    // ------------------------------------------------------------------
    async onCrewEmptyClick() {
        const xmlid = this.crewEquipment.crew.empty_cta_action;
        if (xmlid) {
            await this.action.doAction(xmlid);
        }
    }

    async onCrewRowClick(row) {
        // Booked rows deeplink to the first event_job the user is on.
        // Available rows have no deeplink (status === 'available' and
        // deeplink_event_job_id is false).
        if (!row || !row.deeplink_event_job_id) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "commercial.event.job",
            res_id: row.deeplink_event_job_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async onCrewGapClick(gap) {
        if (!gap || !gap.deeplink_event_job_id) return;
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "commercial.event.job",
            res_id: gap.deeplink_event_job_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async onEquipmentEmptyClick() {
        const xmlid = this.crewEquipment.equipment.empty_cta_action;
        if (xmlid) {
            await this.action.doAction(xmlid);
        }
    }

    async onEquipmentCatClick(cat) {
        if (!cat || !cat.deeplink_action) return;
        // Deeplink to the equipment unit list, with a context filter
        // by category. doAction merges additionalContext.
        const ctx = {};
        if (cat.category_id) {
            ctx.search_default_equipment_category_id = cat.category_id;
        }
        await this.action.doAction(cat.deeplink_action, {
            additionalContext: ctx,
        });
    }

    // ------------------------------------------------------------------
    // Layout helpers consumed by the template.
    // ------------------------------------------------------------------
    isWidgetVisible(widgetKey) {
        const layout = (this.state.data && this.state.data.layout) || [];
        const row = layout.find((l) => l.widget_key === widgetKey);
        return !!(row && row.visible);
    }

    get kpi() {
        return (this.state.data && this.state.data.kpi) || {};
    }

    get jobsBlock() {
        return (this.state.data && this.state.data.jobs_block) || {
            empty: true, rows: [],
        };
    }

    get crewEquipment() {
        return (
            (this.state.data && this.state.data.crew_equipment_block) || {
                crew: { empty: true, rows: [], gaps: [] },
                equipment: { empty: true, categories: [] },
            }
        );
    }

    get salesBlock() {
        return (
            (this.state.data && this.state.data.sales_block) || {
                pipeline_by_stage: { empty: true, stages: [] },
                win_rate: { empty: true },
                lead_sources: { empty: true, sources: [] },
            }
        );
    }

    get financeBlock() {
        return (
            (this.state.data && this.state.data.finance_block) || {
                cash: { empty: true, usd_total: 0, zig_total: 0,
                        rate: 0, zig_in_usd: 0,
                        rate_source: "unset", rate_as_of: "" },
                ar_aging: { empty: true, buckets: [],
                            total_count: 0, total_amount_display: "$0",
                            zig_excluded_count: 0 },
            }
        );
    }

    formatUsd(v) {
        if (v === null || v === undefined || isNaN(v)) return "$0";
        if (Math.abs(v) >= 1000) {
            return "$" + (v / 1000).toFixed(1) + "k";
        }
        return "$" + Math.round(v).toLocaleString("en-US");
    }

    formatZwg(v) {
        if (v === null || v === undefined || isNaN(v)) return "Z$0";
        if (Math.abs(v) >= 1000) {
            return "Z$" + (v / 1000).toFixed(1) + "k";
        }
        return "Z$" + Math.round(v).toLocaleString("en-US");
    }

    async onManageRateClick() {
        await this.action.doAction(
            "neon_dashboard.action_neon_dashboard_zig_rate_wizard");
    }

    async onAgingBucketClick(bucket) {
        const xmlid = this.financeBlock.ar_aging.deeplink_action;
        if (!xmlid) return;
        // Per-bucket filtering at the URL level is awkward (the AR
        // aging buckets are derived in our compute, not stored on
        // the move). Open the overdue list; the user can filter
        // further from there.
        await this.action.doAction(xmlid);
    }

    async onPipelineStageClick(stage) {
        if (!stage || !stage.deeplink_action) return;
        // All pipeline stages share the same act_window (filtered to
        // pending_approval/approved/sent at the action level).
        await this.action.doAction(stage.deeplink_action);
    }

    get availableTypes() {
        return (this.state.data && this.state.data.available_types) || [];
    }

    get isSuperuser() {
        return !!(this.state.data && this.state.data.is_superuser);
    }

    get dashboardTypeLabel() {
        const opts = this.availableTypes;
        const t = this.state.data && this.state.data.dashboard_type;
        const match = opts.find((o) => o.value === t);
        if (match) return match.label;
        // Fall back to a static map for non-superusers (no dropdown
        // options shipped down).
        const fallback = {
            director: "Director",
            sales: "Sales",
            bookkeeper: "Bookkeeper",
            lead_tech: "Lead Tech",
            tech: "Tech",
        };
        return fallback[t] || "";
    }

    get userRoleLabel() {
        return (this.state.data && this.state.data.user_role_label) || "";
    }

    get userName() {
        return (this.state.data && this.state.data.user_name) || "";
    }

    get lastUpdated() {
        return (this.state.data && this.state.data.last_updated) || "";
    }

    // ------------------------------------------------------------------
    // Filter chips. Locked set; per-chip filtering wires up alongside
    // each block (Sales chip in M5, Finance chip in M6, Operations
    // already correct since M3 ships only the Operations-flavoured
    // Jobs block).
    // ------------------------------------------------------------------
    get filters() {
        return [
            { key: "all", label: "All" },
            { key: "operations", label: "Operations" },
            { key: "sales", label: "Sales" },
            { key: "finance", label: "Finance" },
        ];
    }
}

registry.category("actions").add("neon_dashboard", NeonDashboard);
