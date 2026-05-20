/** @odoo-module **/

/*
 * Mirror of account.dynamic_selection -- kept local to avoid
 * a semantic dependency on the account module. Training has no
 * business depending on Accounting; we duplicate ~30 lines of
 * widget glue rather than pull the whole finance app into the
 * dependency graph.
 *
 * Widget: neon_dynamic_selection
 * Use: <field name="level" widget="neon_dynamic_selection"
 *             options="{'available_field': 'available_levels'}"/>
 *
 * The sibling field named in `available_field` must be a Char
 * holding a comma-separated list of allowed option keys.
 * Empty / unset = fall back to the full Selection (no narrowing).
 *
 * P7a.M3 build-time decision. See gate-1 design review.
 */

import { registry } from "@web/core/registry";
import {
    SelectionField,
    selectionField,
} from "@web/views/fields/selection/selection_field";


export class NeonDynamicSelectionField extends SelectionField {
    static props = {
        ...SelectionField.props,
        available_field: { type: String },
    };

    get availableOptions() {
        const value = this.props.record.data[this.props.available_field];
        if (!value) {
            return null; // signal: no narrowing
        }
        return value.split(",").map((s) => s.trim()).filter(Boolean);
    }

    /**
     * Narrow the parent Selection's options to the subset listed in
     * the available_field sibling. When the sibling is empty, fall
     * back to the full option list.
     * @override
     */
    get options() {
        const allowed = this.availableOptions;
        if (allowed === null) {
            return super.options;
        }
        return super.options.filter(([key]) => allowed.includes(key));
    }

    /**
     * Resolve the display string for the currently-stored value even
     * if it has been filtered out of the narrowed option list (e.g.
     * stale row carrying a level from before the type was changed).
     * @override
     */
    get string() {
        if (this.type === "selection") {
            const value = this.props.record.data[this.props.name];
            if (value === false) {
                return "";
            }
            // Look in super.options (un-narrowed) so historical
            // values still render.
            const found = super.options.find((o) => o[0] === value);
            return found ? found[1] : value;
        }
        return super.string;
    }
}


export const neonDynamicSelectionField = {
    ...selectionField,
    component: NeonDynamicSelectionField,
    supportedOptions: [
        {
            label: "Available Field",
            name: "available_field",
            type: "string",
        },
    ],
    extractProps({ options }) {
        const props = selectionField.extractProps(...arguments);
        props.available_field = options.available_field;
        return props;
    },
};


registry
    .category("fields")
    .add("neon_dynamic_selection", neonDynamicSelectionField);
