# -*- coding: utf-8 -*-
{
    "name": "Neon Menu Order",
    "version": "17.0.1.0.0",
    "summary": "Sidebar department grouping -- sequence-only reorder of the "
               "top-level app menus into department clusters.",
    "description": """
Cosmetic, sequence-only reorder of the top-level (parent_id=false) app menus so
related apps cluster by department in the sidebar / app switcher. Writes ONLY
ir.ui.menu.sequence -- never groups_id, action, or visibility. Each user still
sees exactly their own role-gated subset; only the order changes.

Applied via a force-write hook (not data records) because several menu roots are
noupdate=1. Must be installed/upgraded on a DB where the ordered apps already
exist (always true on the live install); any menu not present is skipped.
""",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    "category": "Neon/UX",
    "depends": ["base"],
    "data": [],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
