# -*- coding: utf-8 -*-
{
    "name": "Neon Web Sidebar",
    "version": "17.0.1.1.0",
    "summary": "Persistent Zoho-style left module rail (coexists with web_responsive)",
    "description": """
Persistent left vertical sidebar for switching modules, rendered as a sibling
in the WebClient layout via the main_components registry -- it does NOT override
the navbar (that is web_responsive's territory). Reads the app list read-only
through the menu service, highlights the active app, and is per-user toggleable
via a systray switch (collapse/expand). De-risks the "changes everyone's UI"
concern: anyone can hide it.

Design note: built on web_responsive's UNTOUCHED seam (main_components +
useService('menu') + a private SCSS namespace) so it coexists with
web_responsive's grid launcher + command palette rather than fighting them.
""",
    "category": "Neon/UI",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    # depend on web_responsive so we load AFTER it and only install where it is
    # present (the whole point is to COEXIST with it, not replace it).
    "depends": ["web", "web_responsive"],
    "assets": {
        "web.assets_backend": [
            "neon_web_sidebar/static/src/sidebar/neon_sidebar.js",
            "neon_web_sidebar/static/src/sidebar/neon_sidebar.xml",
            "neon_web_sidebar/static/src/sidebar/neon_sidebar.scss",
        ],
    },
    "installable": True,
    "application": False,
}
