# -*- coding: utf-8 -*-
{
    "name": "Neon Screens — Equipment & Inventory",
    "version": "17.0.1.6.0",
    "summary": "Design-deck Equipment & Inventory screen + Rail v0 nav "
               "skeleton (additive, read-only — no new equipment fields)",
    "description": """
Neon Screens — Equipment & Inventory (design-deck screen #1)
============================================================
A read-only, on-brand presentation layer over the EXISTING live equipment
domain in neon_jobs. Additive + reversible: no new models/fields on the
equipment data, no writes, no new security groups.

* **Equipment & Inventory screen** — an OWL client action composing the deck
  layout over real data:
    - per-item availability (product.template workshop items: Owned =
      total_units, Available = available_units, hire rate) with a status pill
      sourced from the latest conflict run (IN STOCK / SUB-HIRE / ZERO MARGIN —
      never fabricated);
    - the conflict / sub-hire card from neon.equipment.conflict (latest run;
      shows "all clear" honestly when there is no deficit);
    - the per-asset register from neon.equipment.unit (Asset ID, Item,
      Category, State pill).
  Reuses the neon_jobs groups for access. Inherits neon_theme styling.

* **Rail v0 (skeleton)** — a post_init hook that sets the curated 9-slot nav
  order at the top of the rail and labels the entries whose screen exists
  (My Landing = live dashboard; Equipment & Inventory = this screen). Other
  business entries move to their slot keeping their current label until their
  screen is built. NO hiding of the raw app list, NO role-switcher (those are
  Rail v1). Reuses neon_menu_order's sequence mechanism.
""",
    "category": "Neon/UI",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    # neon_jobs = equipment models + groups; neon_menu_order = load AFTER it so
    # the Rail v0 sequence writes are final; web = OWL assets. neon_finance +
    # neon_weekly_budget = Finance Control (#4) data models + finance groups.
    "depends": ["neon_jobs", "neon_menu_order", "neon_finance",
                "neon_weekly_budget", "crm", "neon_migration", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/neon_equipment_screen_views.xml",
        "views/operations_calendar_views.xml",
        "views/event_jobs_views.xml",
        "views/finance_control_views.xml",
        "views/crm_pipeline_views.xml",
        "views/crew_people_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "neon_screens/static/src/screens/_screen_base.scss",
            "neon_screens/static/src/screens/equipment/equipment_screen.scss",
            "neon_screens/static/src/screens/equipment/equipment_screen.js",
            "neon_screens/static/src/screens/equipment/equipment_screen.xml",
            "neon_screens/static/src/screens/operations/operations_screen.scss",
            "neon_screens/static/src/screens/operations/operations_screen.js",
            "neon_screens/static/src/screens/operations/operations_screen.xml",
            "neon_screens/static/src/screens/eventjobs/event_jobs_screen.scss",
            "neon_screens/static/src/screens/eventjobs/event_jobs_screen.js",
            "neon_screens/static/src/screens/eventjobs/event_jobs_screen.xml",
            "neon_screens/static/src/screens/finance/finance_control_screen.scss",
            "neon_screens/static/src/screens/finance/finance_control_screen.js",
            "neon_screens/static/src/screens/finance/finance_control_screen.xml",
            "neon_screens/static/src/screens/crm/crm_pipeline_screen.scss",
            "neon_screens/static/src/screens/crm/crm_pipeline_screen.js",
            "neon_screens/static/src/screens/crm/crm_pipeline_screen.xml",
            "neon_screens/static/src/screens/crew/crew_people_screen.scss",
            "neon_screens/static/src/screens/crew/crew_people_screen.js",
            "neon_screens/static/src/screens/crew/crew_people_screen.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
