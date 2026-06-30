# -*- coding: utf-8 -*-
{
    "name": "Neon Web — Control-Panel Record Search",
    "version": "17.0.1.0.0",
    "summary": "A record-search affordance in the list/kanban control panel: "
               "type a name -> scrollable dropdown of matching records -> click "
               "to open. Additive (the facet SearchBar is untouched). Reversible "
               "by uninstall.",
    "description": """
Neon Web — Control-Panel Record Search (Path B)
===============================================
Injects a record-search widget into the control panel of EVERY list/kanban view
at one global point (OWL t-inherit of web.ControlPanel), reading the active model
dynamically via env.searchModel.resModel. Reuses the core @web/core/autocomplete
AutoComplete component:

* click the input -> dropdown populated on click (name_search active model, cap 50)
* scrollable record rows (display_name; per-model sub-labels are a follow-up)
* filter-as-you-type (server-side name_search)
* click a record -> doAction opens its form

ADDITIVE ONLY: the facet SearchBar (filters / multi-field search / group-by /
favorites / saved searches / Enter semantics / keyboard-nav) is COMPLETELY
untouched -- this is a separate affordance alongside it. NO "add new" option
(scope decision: no create in either surface). NO full-dataset load (cap 50 +
name_search; refine by typing).

Companion to neon_web_autocomplete (which enhances in-FORM field pickers) -- a
different surface; both stay. Loads after web_responsive so the control-panel
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
