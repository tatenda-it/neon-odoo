# -*- coding: utf-8 -*-
{
    "name": "Neon Theme",
    "version": "17.0.1.0.0",
    "summary": "Global Neon ERP design language for the Odoo backend "
               "(additive, reversible, no data models)",
    "description": """
Neon Theme
==========
Dresses the whole Odoo 17 backend in the Neon ERP design language: purple
gradient navbar, deep-ink app rail, floating rounded white list cards,
card-on-tinted-page form sheets, pill primary buttons, semantic status pills,
Montserrat headings + Open Sans body.

Design principles
-----------------
* **Additive & reversible** — no models, no security, no data. Uninstall and
  Odoo returns to stock.
* **Upgrade-safe overrides** — brand colours + type are set through Bootstrap /
  Odoo SCSS variables in ``web._assets_primary_variables`` (prepended so they
  win over Odoo's ``!default``), not brute ``!important``.
* **Icon-safe type swap** — the font change rides on ``$font-family-base`` /
  ``$headings-font-family`` (body + headings only), never a universal ``*``
  rule, and a defensive guard keeps ``.fa`` (FontAwesome) / ``.oi``
  (odoo_ui_icons) glyphs intact.
* **Self-hosted fonts** — Montserrat + Open Sans ship as module ``woff2``
  assets; no Google Fonts CDN at runtime.
""",
    "category": "Neon/UI",
    "author": "Neon Events Elements",
    "license": "LGPL-3",
    # Load AFTER web_responsive so our chrome overrides win (prod + local both
    # run web_responsive). Stock `web` covers the rest.
    "depends": ["web", "web_responsive"],
    "assets": {
        # Brand + type variables — prepended so they precede Odoo's `!default`.
        "web._assets_primary_variables": [
            ("prepend", "neon_theme/static/src/scss/primary_variables.scss"),
        ],
        # Component styling + self-hosted @font-face.
        "web.assets_backend": [
            "neon_theme/static/src/scss/neon_theme.scss",
        ],
    },
    "installable": True,
    "application": False,
}
