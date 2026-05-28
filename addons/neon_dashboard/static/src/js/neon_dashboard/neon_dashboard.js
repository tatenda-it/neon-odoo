/** @odoo-module **/

import {
    Component,
    onMounted,
    onWillStart,
    onWillUnmount,
    useRef,
    useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSortable } from "@web/core/utils/sortable_owl";
import { _t } from "@web/core/l10n/translation";
import { NeonVenueMapDialog } from "@neon_dashboard/js/neon_venue_map_dialog/neon_venue_map_dialog";
import { NeonAiChat } from "@neon_dashboard/js/ai_chat/ai_chat";


// P8B.M4: content blocks that may be hidden/reordered, with their
// human labels (for the hidden-stub card). KPI tiles are NOT here --
// they always show (scope lock). Mandatory blocks (can't hide) below.
const BLOCK_LABELS = {
    block_jobs: "Jobs",
    block_sales: "Sales Pipeline",
    block_finance: "Finance · AR & Cash",
    block_alerts: "Alerts",
    block_crew_equipment: "Crew & Equipment",
    block_tasks: "Tasks",
    block_ai_insights: "AI Insights",
    block_hot_deals: "Hot Deals Watch",
    block_aging_quotes: "Aging Quotes",
    block_budget_alerts: "Budget Alerts",
    block_invoice_queue: "Invoice Queue",
    block_zig_costs: "ZiG Rate · Recent Costs",
    block_crew_gaps: "Crew Gaps Watch",
    block_cert_expiry: "Cert Expiry Watch",
};

// block_alerts is the only mandatory CONTENT block (D6); the UI never
// offers a Hide button for it. kpi_cash / kpi_ar_overdue are mandatory
// too but are KPI tiles, never in the block list.
const MANDATORY_BLOCKS = new Set(["block_alerts"]);

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
    static components = { NeonAiChat };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.rpc = useService("rpc");

        this.state = useState({
            loading: true,
            error: null,
            data: null,
            activeFilter: "all",
            // M10: 'pdf' or 'xlsx' while an export is in flight;
            // null when idle. Disables both buttons during the
            // 2-5s server roundtrip to prevent double-clicks.
            exporting: null,
            // M11: AI Insights widget state. Initial-load payload
            // comes from rpc_latest_insight_for_current_user;
            // manual refresh button calls rpc_refresh_for_current
            // _user. aiRefreshing flips the spinner while the
            // call is in flight.
            aiInsights: {
                empty: true,
                empty_message: "Loading...",
                insights: [],
            },
            aiRefreshing: false,
            // P8B.M4 Edit Layout: client-side edit mode + a working
            // copy of the content-block layout. layoutDraft is the
            // mutable mirror used while editing; Save persists it,
            // Cancel discards it.
            editMode: false,
            layoutDraft: [],
            // P12.M1 AI Sales Copilot chat panel state. Hydrated
            // from res.users.chat_panel_expanded on first load;
            // mutated via the panel's collapse button which echoes
            // back to the server via /neon/ai_chat/toggle.
            chatExpanded: false,
        });

        // P8B.M4: useSortable wires onto the unified block container
        // (only rendered in edit/customised mode). Reorder updates
        // layoutDraft order_index from the post-drop DOM order; Save
        // persists. touch_delay 300ms long-press coexists with the
        // M12.1 scroll fix (discovery Q5) -- no custom touch handlers.
        this.blocksContainerRef = useRef("blocksContainer");
        useSortable({
            ref: this.blocksContainerRef,
            elements: ".o_neon_block_slot",
            handle: ".o_neon_drag_handle",
            onDrop: () => this._syncOrderFromDom(),
        });

        // 5-minute auto-refresh (same cadence as cash_flow_dashboard;
        // dashboard data sources change minute-to-minute at most).
        this.REFRESH_MS = 5 * 60 * 1000;
        this._refreshInterval = null;
        this._visibilityHandler = null;

        onWillStart(async () => {
            // P8B: honour ?dashboard_type=<type> for bookmarks /
            // deep-links. Session-transient -- not persisted. The RPC
            // only applies it for superusers (peek-ability); a non-
            // superuser's requested type is ignored server-side and
            // they get their own default. No ACL bypass.
            await this.loadData(this._urlDashboardType());
            // M11: load latest AI insight in parallel-ish after
            // main data (non-blocking on dashboard render).
            this._loadAiInsight();
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
            // P12.M1: hydrate chat-panel state from the user record
            // returned in the dashboard payload. The dashboard's
            // own user_meta block carries it.
            const meta = (this.state.data && this.state.data.user_meta)
                || null;
            if (meta && typeof meta.chat_panel_expanded === "boolean") {
                this.state.chatExpanded = meta.chat_panel_expanded;
            }
            this.state.loading = false;
        } catch (e) {
            this.state.error = (e && e.message) || String(e);
            this.state.loading = false;
        }
    }

    // P12.M1 AI Sales Copilot ----------------------------------
    get isChatVisible() {
        // Show only on Director + Sales variants (D1). Server also
        // enforces via /neon/ai_chat ACL (D11) so a Bookkeeper or
        // Lead Tech user peeking at Sales via View-as gets denied
        // at the API layer even if the panel renders.
        const dtype = this.state.data && this.state.data.dashboard_type;
        return dtype === "director" || dtype === "sales";
    }

    async onChatToggle(nextExpanded) {
        this.state.chatExpanded = !!nextExpanded;
        try {
            await this.rpc(
                "/neon/ai_chat/toggle",
                { expanded: this.state.chatExpanded });
        } catch (e) {
            // Best-effort persistence; UI state is the source of
            // truth in-session. Surface to console only.
            console.warn("chat toggle persistence failed", e);
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
        // Reset the active chip when switching variant -- the new
        // variant has a different chip set, so the previous filter
        // key may not apply.
        this.state.activeFilter = "all";
        this.loadData(newType);
    }

    onFilterChange(filter) {
        // M6 director chips: all / operations / sales / finance.
        // P8B variant chips: sales (hot/aging/won), bookkeeper
        // (overdue/due_soon/recently_paid), lead_tech (today/next7/
        // next30). Each is a client-side widget-visibility filter via
        // the o_neon_dashboard__filter_<key> body class + the SCSS
        // .widget--<key> hide rules.
        this.state.activeFilter = filter;
    }

    _urlDashboardType() {
        // Read dashboard_type from the action context/params first,
        // then fall back to the URL (search or hash). Returns null
        // when absent (auto-route fires server-side).
        try {
            const act = this.props && this.props.action;
            const fromCtx = act && (
                (act.context && act.context.dashboard_type)
                || (act.params && act.params.dashboard_type));
            if (fromCtx) return fromCtx;
            const search = new URLSearchParams(
                window.location.search || "");
            if (search.get("dashboard_type")) {
                return search.get("dashboard_type");
            }
            const hash = (window.location.hash || "").replace(/^#/, "");
            const hashParams = new URLSearchParams(hash);
            return hashParams.get("dashboard_type") || null;
        } catch (e) {
            return null;
        }
    }

    // ==============================================================
    // P8B.M4 -- Edit Layout (hide/reorder content blocks).
    // ==============================================================
    onEditLayoutClick() {
        // Enter edit mode: snapshot the current layout into a mutable
        // draft. Edit mode renders the unified grid (see M8B.4.1
        // marker in the template) so useSortable has one container.
        const layout = (this.state.data && this.state.data.layout) || [];
        this.state.layoutDraft = layout.map((l) => ({ ...l }));
        this.state.editMode = true;
    }

    onLayoutCancel() {
        this.state.editMode = false;
        this.state.layoutDraft = [];
    }

    _layoutUpdatesFromDraft() {
        return (this.state.layoutDraft || [])
            .filter((l) => l.widget_key.startsWith("block_"))
            .map((l) => ({
                widget_key: l.widget_key,
                visible: l.visible,
                order_index: l.order_index,
            }));
    }

    async onLayoutSave() {
        const dtype = (this.state.data && this.state.data.dashboard_type)
            || null;
        try {
            const refreshed = await this.orm.call(
                "neon.dashboard", "dashboard_update_layout",
                [dtype, this._layoutUpdatesFromDraft()],
            );
            this.state.data = refreshed;
        } catch (e) {
            this.notification.add(
                _t("Save failed: ") + ((e && e.message) || String(e)),
                { type: "danger" });
            return;
        }
        this.state.editMode = false;
        this.state.layoutDraft = [];
    }

    async onLayoutReset() {
        const dtype = (this.state.data && this.state.data.dashboard_type)
            || null;
        try {
            const refreshed = await this.orm.call(
                "neon.dashboard", "dashboard_reset_layout", [dtype]);
            this.state.data = refreshed;
        } catch (e) {
            this.notification.add(
                _t("Reset failed: ") + ((e && e.message) || String(e)),
                { type: "danger" });
            return;
        }
        this.state.editMode = false;
        this.state.layoutDraft = [];
    }

    async onLayoutApplyAll() {
        const dtype = (this.state.data && this.state.data.dashboard_type)
            || null;
        try {
            const result = await this.orm.call(
                "neon.dashboard",
                "dashboard_apply_layout_to_all_variants",
                [dtype, this._layoutUpdatesFromDraft()],
            );
            const applied = Object.entries(result || {})
                .filter(([, v]) => v === "applied")
                .map(([k]) => k);
            this.notification.add(
                _t("Layout applied to: ") + applied.join(", "),
                { type: "success" });
            // Refresh the current variant view.
            this.state.data = await this.orm.call(
                "neon.dashboard", "get_dashboard_data", [],
                { dashboard_type: dtype });
        } catch (e) {
            this.notification.add(
                _t("Apply-to-all failed: ")
                + ((e && e.message) || String(e)),
                { type: "danger" });
            return;
        }
        this.state.editMode = false;
        this.state.layoutDraft = [];
    }

    onBlockHide(widgetKey) {
        const row = (this.state.layoutDraft || []).find(
            (l) => l.widget_key === widgetKey);
        if (row && !this.isMandatoryBlock(widgetKey)) {
            row.visible = false;
        }
    }

    onBlockShow(widgetKey) {
        const row = (this.state.layoutDraft || []).find(
            (l) => l.widget_key === widgetKey);
        if (row) {
            row.visible = true;
        }
    }

    _syncOrderFromDom() {
        // After a useSortable drop, re-derive order_index from the new
        // DOM order of the slots. OWL re-renders orderedBlocks (sorted
        // by order_index) + CSS `order`, reconciling the transient
        // node move the hook performed.
        const container = this.blocksContainerRef.el;
        if (!container) {
            return;
        }
        const slots = Array.from(
            container.querySelectorAll(".o_neon_block_slot"));
        slots.forEach((el, i) => {
            const key = el.dataset.widgetKey;
            const row = (this.state.layoutDraft || []).find(
                (l) => l.widget_key === key);
            if (row) {
                row.order_index = (i + 1) * 10;
            }
        });
    }

    // ----- Edit-mode template helpers -----
    get isCustomized() {
        return !!(this.state.data && this.state.data.is_customized);
    }

    get useUnified() {
        return this.state.editMode || this.isCustomized;
    }

    get orderedBlocks() {
        const src = this.state.editMode
            ? (this.state.layoutDraft || [])
            : ((this.state.data && this.state.data.layout) || []);
        let blocks = src.filter((l) => l.widget_key.startsWith("block_"));
        if (!this.state.editMode) {
            blocks = blocks.filter((l) => l.visible);
        }
        return [...blocks].sort(
            (a, b) => (a.order_index || 0) - (b.order_index || 0));
    }

    getBlockTemplate(widgetKey) {
        return "neon_dashboard.block." + widgetKey;
    }

    blockLabel(widgetKey) {
        return BLOCK_LABELS[widgetKey] || widgetKey;
    }

    isMandatoryBlock(widgetKey) {
        return MANDATORY_BLOCKS.has(widgetKey);
    }

    get canApplyToAll() {
        // Only meaningful for multi-variant users (superusers). Mirror
        // the server's _accessible_dashboard_types >= 2 rule via the
        // View-as option list the payload already ships.
        return this.availableTypes.length >= 2;
    }

    async onExportPdf() {
        // M10: PDF snapshot honouring active dashboard_type + filter.
        await this._exportSnapshot("pdf", "export_snapshot_pdf");
    }

    async onExportXlsx() {
        // M10: xlsx workbook snapshot.
        await this._exportSnapshot("xlsx", "export_snapshot_xlsx");
    }

    async _exportSnapshot(format, rpcMethod) {
        if (this.state.exporting) return;
        this.state.exporting = format;
        try {
            const dashboardType = (this.state.data
                && this.state.data.dashboard_type) || null;
            const action = await this.orm.call(
                "neon.dashboard",
                rpcMethod,
                [],
                {
                    dashboard_type: dashboardType,
                    active_filter: this.state.activeFilter || "all",
                },
            );
            // The server returns an ir.actions.act_url descriptor.
            // doAction triggers the /web/content download via the
            // standard backend action handler.
            await this.action.doAction(action);
        } catch (e) {
            this.notification.add(
                _t("Export failed: ") + ((e && e.message) || String(e)),
                { type: "danger" });
        } finally {
            this.state.exporting = null;
        }
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

    // P9.M9.2 -- venue pin opens the mini-map modal (D3 / D4 / D5).
    // t-on-click.stop prevents the row's onJobClick from firing too.
    onVenuePinClick(ev, row) {
        this.dialog.add(NeonVenueMapDialog, {
            title: row.venue || "Venue",
            latitude: row.venue_latitude || 0,
            longitude: row.venue_longitude || 0,
            fullAddress: row.venue_full_address || "",
        });
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

    get alertsBlock() {
        return (
            (this.state.data && this.state.data.alerts_block) || {
                empty: true,
                empty_message: "Everything looks healthy",
                total_count: 0,
                severity_counts: { critical: 0, warning: 0, info: 0 },
                alerts: [],
                has_more: false,
            }
        );
    }

    get tasksBlock() {
        return (
            (this.state.data && this.state.data.tasks_block) || {
                empty: true,
                empty_message: "Nothing on your list",
                total_count: 0,
                overdue_count: 0,
                today_count: 0,
                upcoming_count: 0,
                tasks: [],
                has_more: false,
            }
        );
    }

    async onTaskClick(task) {
        if (!task || !task.res_model || !task.res_id) return;
        // Deeplink to the activity's source record via a generic
        // act_window descriptor; no static xmlid since the model
        // is dynamic.
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: task.res_model,
            res_id: task.res_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async onTaskDone(task) {
        if (!task || !task.id) return;
        const refreshed = await this.orm.call(
            "neon.dashboard",
            "dashboard_complete_task",
            [task.id],
        );
        if (this.state.data) {
            this.state.data.tasks_block = refreshed;
        }
    }

    async onAlertClick(alert) {
        if (!alert || !alert.deeplink_action) return;
        if (alert.deeplink_res_id) {
            await this.action.doAction(alert.deeplink_action, {
                additionalContext: {
                    active_id: alert.deeplink_res_id,
                },
            });
        } else {
            await this.action.doAction(alert.deeplink_action);
        }
    }

    async onAlertAck(alert) {
        if (!alert || !alert.fingerprint) return;
        // RPC to dismiss + receive refreshed alerts block.
        const refreshed = await this.orm.call(
            "neon.dashboard",
            "dashboard_dismiss_alert",
            [alert.fingerprint],
        );
        if (this.state.data) {
            this.state.data.alerts_block = refreshed;
        }
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

    // ============================================================
    // M11 -- AI Insights widget handlers
    // ============================================================
    get aiInsights() {
        return this.state.aiInsights || {
            empty: true, empty_message: "Loading...", insights: [],
        };
    }

    get canRefreshAi() {
        // Superuser-only per D12. The widget itself is visible to
        // all tiers but the refresh button is hidden for non-supers.
        return !!(this.state.data && this.state.data.is_superuser);
    }

    async _loadAiInsight() {
        try {
            const payload = await this.orm.call(
                "neon.dashboard.ai.provider",
                "rpc_latest_insight_for_current_user",
                [],
            );
            this.state.aiInsights = payload || {
                empty: true,
                empty_message: "No insight available.",
                insights: [],
            };
        } catch (e) {
            // Non-blocking: dashboard renders without AI block
            // content; widget shows error footer.
            this.state.aiInsights = {
                empty: false,
                insights: [],
                error_message:
                    "Failed to load AI insights: "
                    + ((e && e.message) || String(e)),
            };
        }
    }

    async onAiRefresh() {
        if (this.state.aiRefreshing) return;
        this.state.aiRefreshing = true;
        try {
            const payload = await this.orm.call(
                "neon.dashboard.ai.provider",
                "rpc_refresh_for_current_user",
                [],
            );
            this.state.aiInsights = payload;
        } catch (e) {
            this.notification.add(
                _t("AI refresh failed: ")
                + ((e && e.message) || String(e)),
                { type: "danger" });
        } finally {
            this.state.aiRefreshing = false;
        }
    }

    async onAiInsightClick(ins) {
        if (!ins || !ins.source_ref) return;
        const ref = ins.source_ref;
        if (!ref.model || !ref.res_id) return;
        try {
            await this.action.doAction({
                type: "ir.actions.act_window",
                res_model: ref.model,
                res_id: parseInt(ref.res_id, 10),
                views: [[false, "form"]],
                target: "current",
            });
        } catch (e) {
            this.notification.add(
                _t("Cannot open source record: ")
                + ((e && e.message) || String(e)),
                { type: "warning" });
        }
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

    // ==============================================================
    // P8B variant block getters + handlers.
    // ==============================================================
    get hotDealsBlock() {
        return (this.state.data && this.state.data.hot_deals_block) || {
            empty: true, rows: [],
        };
    }

    get agingQuotesBlock() {
        return (this.state.data && this.state.data.aging_quotes_block) || {
            empty: true, rows: [],
        };
    }

    get budgetAlertsBlock() {
        return (this.state.data && this.state.data.budget_alerts_block) || {
            empty: true, ok: 0, warn: 0, breach: 0, severe: 0,
            has_issues: false,
        };
    }

    get invoiceQueueBlock() {
        return (this.state.data && this.state.data.invoice_queue_block) || {
            empty: true, rows: [],
        };
    }

    get zigCostsBlock() {
        return (this.state.data && this.state.data.zig_costs_block) || {
            rate: 0, rate_display: "", costs: [], costs_empty: true,
        };
    }

    get crewGapsBlock() {
        return (this.state.data && this.state.data.crew_gaps_block) || {
            empty: true, rows: [],
        };
    }

    get certExpiryBlock() {
        return (this.state.data && this.state.data.cert_expiry_block) || {
            empty: true, rows: [],
        };
    }

    async onQuoteRowClick(row) {
        // Hot Deals + Aging Quotes rows share the pipeline action.
        if (!row || !row.deeplink_action) return;
        await this.action.doAction(row.deeplink_action);
    }

    async onInvoiceRowClick(row) {
        if (!row || !row.id) return;
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move",
            res_id: row.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async onCertRowClick(row) {
        if (!row || !row.id) return;
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "neon.training.certification",
            res_id: row.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async onCrewGapsRowClick(row) {
        if (!row || !row.deeplink_id) return;
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "commercial.event.job",
            res_id: row.deeplink_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    get availableTypes() {
        // P8B: drop 'tech' from the View-as peek list (deferred to
        // Phase 9+); keep Director / Sales / Bookkeeper / Lead Tech.
        const opts = (this.state.data && this.state.data.available_types)
            || [];
        return opts.filter((o) => o.value !== "tech");
    }

    get subtitleText() {
        const t = (this.state.data && this.state.data.dashboard_type)
            || "director";
        const map = {
            director: "Operations · Sales · Finance · Alerts",
            sales: "Pipeline · Quotes · Leads · Win Rate",
            bookkeeper: "AR · Cash · ZiG · Compliance",
            lead_tech: "Jobs · Crew · Equipment · Certifications",
            tech: "Today's Jobs",
        };
        return map[t] || map.director;
    }

    get headlineLabel() {
        // §5.C frames Lead Tech as the "Operations" dashboard in the
        // headline while the tier label stays "Lead Tech" everywhere
        // else (View-as, role line).
        const t = this.state.data && this.state.data.dashboard_type;
        if (t === "lead_tech") return "Operations";
        return this.dashboardTypeLabel;
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
        // P8B: chip set per dashboard_type. Keys match the
        // _FILTER_HIDE_RULES dict + the SCSS filter blocks.
        const t = (this.state.data && this.state.data.dashboard_type)
            || "director";
        const sets = {
            director: [
                { key: "all", label: "All" },
                { key: "operations", label: "Operations" },
                { key: "sales", label: "Sales" },
                { key: "finance", label: "Finance" },
            ],
            sales: [
                { key: "all", label: "All" },
                { key: "hot", label: "Hot" },
                { key: "aging", label: "Aging" },
                { key: "won", label: "Won" },
            ],
            bookkeeper: [
                { key: "all", label: "All" },
                { key: "overdue", label: "Overdue" },
                { key: "due_soon", label: "Due Soon" },
                { key: "recently_paid", label: "Recently Paid" },
            ],
            lead_tech: [
                { key: "all", label: "All" },
                { key: "today", label: "Today" },
                { key: "next7", label: "Next 7 Days" },
                { key: "next30", label: "Next 30 Days" },
            ],
            tech: [{ key: "all", label: "All" }],
        };
        return sets[t] || sets.director;
    }
}

registry.category("actions").add("neon_dashboard", NeonDashboard);
