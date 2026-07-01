# -*- coding: utf-8 -*-
{
    "name": "Neon Web — Control-Panel Record Search",
    "version": "17.0.1.1.4",
    "summary": "Record search AS the primary search box: click -> the record "
               "list appears, type -> it narrows, click a row -> opens it. One "
               "clean search (native facet input hidden; Filters button + chips "
               "kept). Reversible by uninstall.",
    "description": """
Neon Web — Record Search (primary search box)
=============================================
Makes the record-search the PRIMARY visible search box, matching the quote-picker
reference behaviour:

* click -> the record list appears (name_search '', cap 50)
* type  -> the list narrows to matching records (name_search re-queries)
* click a row -> opens that record's form (doAction)
* zero results -> a "No records found" feedback row (the one nicety)

Mounted INSIDE the native web.SearchBar (one global OWL t-inherit), reading the
active model dynamically via env.searchModel.resModel. ONE clean visible search:
the native facet typing input is hidden via scss, while the facet CHIPS and the
SearchBarMenu (Filters / Group By / Comparison / Favorites / Saved searches) are
KEPT untouched -- the menu is searchModel-driven and independent of the input, so
all filtering still works, reached via the Filters button. Reads under the acting
user's own ACL (name_search). NO "add new", NO operational-model search rewrite.

Companion to neon_web_autocomplete (which enhances in-FORM field pickers) -- a
different surface; both stay. Loads after web_responsive so the SearchBar
inheritance + dropdown scroll compose cleanly.
""",
    "category": "Neon/UI",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    "depends": ["web", "web_responsive"],
    "assets": {
        "web.assets_backend": [
            "neon_web_record_search/static/src/record_search.js",
            "neon_web_record_search/static/src/record_search.xml",
            "neon_web_record_search/static/src/record_search.scss",
        ],
    },
    "installable": True,
    "application": False,
}
