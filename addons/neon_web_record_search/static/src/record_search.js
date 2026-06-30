/** @odoo-module **/

import { Component } from "@odoo/owl";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { useService } from "@web/core/utils/hooks";

const RECORD_SEARCH_LIMIT = 50;

/**
 * Control-panel record search (Path B). A record-jump affordance in the
 * list/kanban control panel — additive, alongside the facet SearchBar (which it
 * NEVER touches). Reuses the core AutoComplete: input = search box, dropdown
 * populated on click (name_search the active model, cap 50), scrollable record
 * rows, click -> open the record's form. NO "add new". Active model is read
 * dynamically from env.searchModel so one global injection serves every view.
 */
export class NeonRecordSearch extends Component {
    static template = "neon_web_record_search.NeonRecordSearch";
    static components = { AutoComplete };
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
    }

    get resModel() {
        return this.env.searchModel && this.env.searchModel.resModel;
    }

    get sources() {
        return [
            {
                options: async (request) => {
                    const model = this.resModel;
                    if (!model) {
                        return [];
                    }
                    const records = await this.orm.call(model, "name_search", [], {
                        name: (request || "").trim(),
                        limit: RECORD_SEARCH_LIMIT,
                    });
                    // name_search -> [[id, display_name], ...]
                    return records.map(([id, name]) => ({
                        value: name,
                        label: name,
                        recordId: id,
                    }));
                },
            },
        ];
    }

    onSelect(option) {
        if (!option || !option.recordId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: this.resModel,
            res_id: option.recordId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

// Register the widget on the ControlPanel so the inherited template can mount it.
// Preserve the existing components (SearchBar, Pager, ...) -- ADD, don't replace.
ControlPanel.components = { ...ControlPanel.components, NeonRecordSearch };
