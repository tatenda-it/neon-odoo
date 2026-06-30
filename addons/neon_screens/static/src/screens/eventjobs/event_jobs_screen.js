/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const TABS = [
    ["all", "All"],
    ["CONFIRMED", "Confirmed"],
    ["SOFT HOLD", "Soft Hold"],
    ["TBC", "TBC"],
];

/**
 * Event Jobs — design-deck screen #3, over commercial.event.job (execution).
 * Job list with deck status pills (CONFIRMED / SOFT HOLD / TBC / INVOICED /
 * CLOSED — derived from real fields) + All/Confirmed/Soft Hold/TBC filter tabs.
 * Honest about thin child data (crew 0, value —).
 */
export class EventJobsScreen extends Component {
    static template = "neon_screens.EventJobsScreen";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.tabs = TABS;
        this.state = useState({
            rows: [], counts: {}, total: 0, shown: 0,
            loading: true, error: null, tab: "all",
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const d = await this.orm.call("neon.event.jobs.screen", "get_data", []);
            Object.assign(this.state, {
                rows: d.rows, counts: d.counts, total: d.total, shown: d.shown,
            });
        } catch (e) {
            this.state.error = (e && e.message) || String(e);
        }
        this.state.loading = false;
    }

    setTab(t) { this.state.tab = t; }
    get filteredRows() {
        return this.state.tab === "all"
            ? this.state.rows
            : this.state.rows.filter((r) => r.status === this.state.tab);
    }
    tabCount(key) {
        return key === "all" ? (this.state.counts.all || 0) : (this.state.counts[key] || 0);
    }
    toneClass(tone) {
        return {
            ok: "text-bg-success", warn: "text-bg-warning", alert: "text-bg-danger",
            muted: "text-bg-secondary", info: "text-bg-info", dark: "text-bg-dark",
        }[tone] || "text-bg-secondary";
    }
    openJob(id) {
        // Open the Event Job DETAIL screen (#10), NOT the native form. The
        // native commercial.event.job form trips a neon_training access-error
        // for non-Training users (gate-log field on the form); the detail
        // screen reads via RPC and renders OWL, avoiding it entirely.
        this.action.doAction({
            type: "ir.actions.client",
            tag: "neon_event_job_detail_screen",
            name: "Event Job",
            params: { event_job_id: id },
            context: { event_job_id: id },
        });
    }
}

registry.category("actions").add("neon_event_jobs_screen", EventJobsScreen);
