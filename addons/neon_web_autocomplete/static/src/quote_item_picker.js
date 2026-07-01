/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Many2OneField, many2OneField } from "@web/views/fields/many2one/many2one_field";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";

/**
 * Neon quote-line ITEM picker — a TIGHTLY-SCOPED custom Many2one widget, applied
 * only via widget="neon_quote_item" on ONE field (quote line product_template_id).
 * It does NOT touch global defaultProps and does NOT add any global CSS that
 * could leak onto list renderers / other pickers (mirrors core
 * AvatarMany2XAutocomplete). Two behaviours vs the stock picker:
 *
 *  1. RATE SUB-LABEL on EVERY row: a custom optionTemplate renders the item's
 *     hire rate ("Rate: USD x.xx", or "Rate: —" when no pricing rule) under the
 *     name. The rate is product.template.neon_unit_rate (USD day-1 base rate,
 *     resolved from pricing rules) -- NOT in name_search, so we read it for the
 *     returned option ids and attach it to each option.
 *  2. FULL LIST + full typed match (uncapped): searchLimit is raised to an
 *     effectively-unbounded value as an INSTANCE prop (via the field's
 *     Many2XAutocompleteProps getter), so ONLY this field is uncapped -- the
 *     global 50-cap (neon_web_autocomplete) still governs every other picker.
 *     Matching stays native (name_search 'ilike') -- only the cap changes.
 */
const NEON_ITEM_FULL_LIMIT = 100000; // effectively "the full list" for products

export class NeonQuoteItemAutocomplete extends Many2XAutocomplete {
    get optionsSource() {
        return {
            ...super.optionsSource,
            optionTemplate: "neon_web_autocomplete.QuoteItemOption",
        };
    }

    async loadOptionsSource(request) {
        const options = await super.loadOptionsSource(request);
        // Attach the hire rate to each REAL record option (create/searchMore
        // rows have no numeric value -> skipped). Best-effort: a failed read
        // (e.g. ACL) must never break the picker.
        const ids = options.filter((o) => typeof o.value === "number").map((o) => o.value);
        if (ids.length) {
            try {
                const recs = await this.orm.read(this.props.resModel, ids, [
                    "neon_unit_rate",
                    "neon_unit_rate_has_rule",
                ]);
                const byId = Object.fromEntries(recs.map((r) => [r.id, r]));
                for (const o of options) {
                    const r = byId[o.value];
                    if (r) {
                        o.rate = r.neon_unit_rate;
                        o.hasRule = r.neon_unit_rate_has_rule;
                    }
                }
            } catch {
                // rate is a display nicety; leave options unannotated on failure
            }
        }
        return options;
    }
}

export class NeonQuoteItemField extends Many2OneField {
    static components = {
        ...Many2OneField.components,
        Many2XAutocomplete: NeonQuoteItemAutocomplete,
    };

    get Many2XAutocompleteProps() {
        // INSTANCE-scoped uncap -- never global defaultProps.
        return { ...super.Many2XAutocompleteProps, searchLimit: NEON_ITEM_FULL_LIMIT };
    }
}

export const neonQuoteItemField = {
    ...many2OneField,
    component: NeonQuoteItemField,
};

// Register under the plain + list keys so it resolves whether the quote line is
// rendered in a form or an editable list. Scoped to fields that opt in via
// widget="neon_quote_item".
registry.category("fields").add("neon_quote_item", neonQuoteItemField);
registry.category("fields").add("list.neon_quote_item", neonQuoteItemField);
