/** @odoo-module **/

import { Component } from "@odoo/owl";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useService } from "@web/core/utils/hooks";

const RECORD_SEARCH_LIMIT = 50;

/**
 * Record search as the PRIMARY visible search box. Mounted INSIDE the native
 * web.SearchBar (the normal search position), reusing the core AutoComplete:
 *
 *   click -> the record list appears (name-prefix '%', cap 50)
 *   type  -> the list narrows to NAME-prefix matches (re-queries each keystroke)
 *   click a row -> opens that record's form
 *
 * Matching = NAME-ONLY + PREFIX: search_read [('name','=ilike','term%')] (not
 * the default name_search, which also matches email/ref). See the sources getter.
 *
 * One clean visible search: the native facet typing input is hidden via scss;
 * the facet chips + the SearchBarMenu (Filters / Group By / Favorites / Saved
 * searches) are KEPT untouched (the menu is searchModel-driven, independent of
 * the input). Active model is read dynamically from env.searchModel.resModel.
 * Reads under the acting user's own ACL. NO create.
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
                    // NAME-ONLY PREFIX match. Two things define the match:
                    //  (1) PREFIX (starts-with): '=ilike' with a trailing % gives
                    //      'rob%' -> names beginning with "rob", never the
                    //      substring "p<rob>ationary". Empty term -> '%' -> list.
                    //  (2) NAME-ONLY: search the record-name field only, NOT the
                    //      default name_search (which also matches email/ref on
                    //      partners -> "rob" wrongly pulling Administrator via
                    //      robin@). display_name is non-stored/non-searchable, so
                    //      we search 'name' (the _rec_name on our models) and show
                    //      display_name. Fallback to prefix name_search for any
                    //      exotic model without a 'name' field (so it never errors).
                    const term = (request || "").trim();
                    // Empty click (before typing) -> load the FULL list, no cap
                    // (explicit Tatenda+Robin decision; perf risk accepted). The
                    // dropdown scrolls (plain overflow-y + content-visibility on
                    // rows, see scss) so a large list doesn't freeze the browser.
                    // Typing -> keep the prefix-filter cap (matching unchanged).
                    const kw = term ? { limit: RECORD_SEARCH_LIMIT } : {};
                    let rows;
                    try {
                        const recs = await this.orm.searchRead(
                            model,
                            [["name", "=ilike", term + "%"]],
                            ["display_name"],
                            kw
                        );
                        rows = recs.map((r) => [r.id, r.display_name]);
                    } catch {
                        const ns = await this.orm.call(model, "name_search", [], {
                            name: term + "%",
                            operator: "=ilike",
                            limit: term ? RECORD_SEARCH_LIMIT : false,
                        });
                        rows = ns;
                    }
                    if (!rows.length) {
                        // the single allowed nicety: a zero-result type shows a
                        // feedback row instead of a vanishing box. Unselectable
                        // -> clicking it just clears + closes (no doAction).
                        return [
                            { value: "", label: "No records found", recordId: false, unselectable: true },
                        ];
                    }
                    return rows.map(([id, name]) => ({
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

// Mount the record-search inside the native SearchBar (primary search position),
// alongside the kept facet chips + SearchBarMenu. Spread-ADD (preserve the
// existing SearchBar components, never replace).
SearchBar.components = { ...SearchBar.components, NeonRecordSearch };
