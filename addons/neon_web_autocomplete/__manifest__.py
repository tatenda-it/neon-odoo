# -*- coding: utf-8 -*-
{
    "name": "Neon Web — Field Autocomplete Type-ahead",
    "version": "17.0.1.0.0",
    "summary": "Global field-picker type-ahead: raise the Many2one autocomplete "
               "result cap to a scrollable page (~50) + in-dropdown scroll. "
               "Reversible by uninstall.",
    "description": """
Neon Web — Field Autocomplete Type-ahead
========================================
The FIRST neon-authored web override, deliberately minimal + isolated +
uninstall-reversible. Approach B from the type-ahead GATE-0.

Applies GLOBALLY to every Many2one field picker (quote-line product,
partner/contact/equipment pickers, etc.) via the shared
@web/views/fields/relational_utils Many2XAutocomplete:

* **Cap raise** — the dropdown result cap was 7 (Many2XAutocomplete.defaultProps
  .searchLimit; the Many2OneField prop is not passed down, so the wrapper default
  is the effective lever). Raised to 50 = a scrollable page. Server-side
  name_search still filters as you type; "Search More" still covers the long
  tail; nothing loads the full dataset on click.
* **In-dropdown scroll** — the core AutoComplete dropdown
  (.o-autocomplete--dropdown-menu) had no max-height, so 50 rows would overflow.
  A max-height + overflow-y:auto makes the results scroll in place.

NOT touched: the control-panel view search bar (a separate, facet-based
SearchBar component) — parked. No OCA dependency. Loads after web_responsive so
the scroll rule composes cleanly with its .o-autocomplete--dropdown-menu
item-wrapping rule.
""",
    "category": "Neon/UI",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    # web_responsive: load AFTER it so our dropdown scroll SCSS composes with its
    # .o-autocomplete--dropdown-menu item-wrapping rule (no clip/double-style).
    "depends": ["web", "web_responsive"],
    "assets": {
        "web.assets_backend": [
            "neon_web_autocomplete/static/src/autocomplete_searchlimit.js",
            "neon_web_autocomplete/static/src/autocomplete_scroll.scss",
        ],
    },
    "installable": True,
    "application": False,
}
