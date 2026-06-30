/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Event Job Detail — design-deck #10. The click-into-a-job DETAIL view opened
 * from the Event Jobs LIST (#3). Read-only over commercial.event.job via RPC
 * (never the native form → avoids the neon_training form access-error), under
 * the user's own ACL. Panels: Header + timeline, Equipment, Costing, Crew,
 * Commercial. Action buttons (AI plan / Brief crew) are deferred & disabled.
 */
export class EventJobDetailScreen extends Component {
    static template = "neon_screens.EventJobDetailScreen";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const a = this.props.action || {};
        this.eventJobId = (a.params && a.params.event_job_id) ||
            (a.context && a.context.event_job_id) || null;
        this.state = useState({
            data: null, loading: true, error: null,
            brief: { open: false, loading: false, text: "", copied: false, error: null },
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const d = await this.orm.call(
                "neon.event.job.detail.screen", "get_data", [this.eventJobId]);
            if (d && d.error) { this.state.error = d.error; }
            else { this.state.data = d; }
        } catch (e) {
            this.state.error = (e && e.message) || String(e);
        }
        this.state.loading = false;
    }

    get d() { return this.state.data || {}; }
    get counts() { return this.d.counts || {}; }

    toneClass(tone) {
        return {
            ok: "text-bg-success", warn: "text-bg-warning", alert: "text-bg-danger",
            muted: "text-bg-secondary", info: "text-bg-info", dark: "text-bg-dark",
        }[tone] || "text-bg-secondary";
    }

    backToList() {
        this.action.doAction("neon_screens.action_event_jobs_screen_server");
    }

    // DRAFT-ONLY: compose the briefing from real job data and show a copyable
    // preview. This calls a read-only RPC — it sends NOTHING. The human copies
    // and sends from WhatsApp / neon_channels.
    async briefCrew() {
        const b = this.state.brief;
        b.open = true; b.loading = true; b.copied = false; b.error = null; b.text = "";
        try {
            const r = await this.orm.call(
                "neon.event.job.detail.screen", "compose_crew_brief", [this.eventJobId]);
            if (r && r.error) { b.error = r.error; }
            else { b.text = r.text; }
        } catch (e) {
            b.error = (e && e.message) || String(e);
        }
        b.loading = false;
    }
    closeBrief() { this.state.brief.open = false; }
    async copyBrief() {
        try {
            await navigator.clipboard.writeText(this.state.brief.text || "");
            this.state.brief.copied = true;
        } catch (e) {
            this.state.brief.error = "Copy failed — select the text and copy manually.";
        }
    }
}

registry.category("actions").add("neon_event_job_detail_screen", EventJobDetailScreen);
