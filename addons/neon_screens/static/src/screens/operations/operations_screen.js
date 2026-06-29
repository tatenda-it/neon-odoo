/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { View } from "@web/views/view";

const PIPELINE_DOMAIN = [["state", "in", ["pending", "active"]]];

/**
 * Operations Calendar — composed side-panel screen (design-deck #2).
 *
 * LEFT: a custom Calendar/List/Kanban switcher (the native switcher can't be
 * wired inside a client action) that swaps the embedded <View/>'s type. Each
 * mode is the REAL native view, so native behaviour is preserved — in calendar
 * mode: scale toggle, prev/next/today, mini-calendar, colour-coding, popups,
 * drag-reschedule. A t-key on <View/> forces a clean remount per type.
 *
 * RIGHT: the "Holds to chase" panel (real soft-hold data via get_holds()),
 * fixed beside the view in every mode.
 */
export class OperationsCalendarScreen extends Component {
    static template = "neon_screens.OperationsCalendarScreen";
    static components = { View };
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const params = (this.props.action && this.props.action.params) || {};
        this.calendarViewId = params.calendar_view_id || false;

        this.state = useState({
            viewType: "calendar",
            holds: [],
            count: 0,
            loading: true,
            error: null,
        });
        onWillStart(async () => {
            try {
                const data = await this.orm.call(
                    "neon.operations.screen", "get_holds", []);
                this.state.holds = data.holds;
                this.state.count = data.count;
            } catch (e) {
                this.state.error = (e && e.message) || String(e);
            }
            this.state.loading = false;
        });
    }

    // Reactive props for the embedded native view of the live pipeline.
    get viewProps() {
        const base = {
            resModel: "commercial.job",
            domain: PIPELINE_DOMAIN,
            context: {},
        };
        if (this.state.viewType === "list") {
            return { ...base, type: "list", views: [[false, "list"]] };
        }
        if (this.state.viewType === "kanban") {
            return { ...base, type: "kanban", views: [[false, "kanban"]] };
        }
        // calendar (default) — reuse the EXISTING calendar view by id
        return {
            ...base,
            type: "calendar",
            views: [[this.calendarViewId, "calendar"]],
        };
    }

    setView(type) {
        this.state.viewType = type;
    }

    toneClass(tone) {
        return {
            ok: "text-bg-success", warn: "text-bg-warning",
            alert: "text-bg-danger", muted: "text-bg-secondary",
        }[tone] || "text-bg-secondary";
    }

    openHold(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "commercial.job",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add(
    "neon_operations_calendar_screen", OperationsCalendarScreen);
