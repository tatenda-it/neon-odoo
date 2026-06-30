/** @odoo-module **/

import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { Many2OneField } from "@web/views/fields/many2one/many2one_field";

/**
 * Neon global field-picker type-ahead (Approach B) — raise the Many2one
 * autocomplete result cap from 7 to a scrollable page.
 *
 * The EFFECTIVE lever is Many2XAutocomplete.defaultProps.searchLimit: the
 * Many2OneField.Many2XAutocompleteProps getter does NOT pass searchLimit down,
 * so the wrapper's own default (7) is what name_search uses
 * (limit = searchLimit + 1). We bump it to 50. Many2OneField's default is set
 * too as belt-and-braces (harmless if unused).
 *
 * Server-side name_search keeps filtering as you type; "Search More" still
 * covers the long tail; nothing loads the full dataset on click. The
 * companion SCSS adds the in-dropdown scroll for the taller list.
 */
const NEON_SEARCH_LIMIT = 50;

Many2XAutocomplete.defaultProps.searchLimit = NEON_SEARCH_LIMIT;
Many2OneField.defaultProps.searchLimit = NEON_SEARCH_LIMIT;
