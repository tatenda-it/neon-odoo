# -*- coding: utf-8 -*-
"""P8B.M4 -- propagate the new per-variant block `size` seed values.

`data/default_layouts.xml` is noupdate=1, so the new `size: 'large'`
seed values on the dominant block + AI Insights per variant do NOT
apply to existing installs via a plain -u. This migration force-sets
`size` on the seeded default.layout lines AND on already-seeded
user.layout rows (matched by dashboard_type + widget_key) so the
unified Edit-Layout grid renders the intended column spans.

Display-only: `size` drives grid-column-span in the unified container
(large -> span 2). Does not touch visible / order_index /
is_customized.

LARGE set MIRRORS data/default_layouts.xml. Keep in sync.
"""
from odoo import SUPERUSER_ID, api

_LARGE = {
    "director": ("block_jobs", "block_ai_insights"),
    "sales": ("block_sales", "block_ai_insights"),
    "bookkeeper": ("block_finance", "block_ai_insights"),
    "lead_tech": ("block_jobs", "block_ai_insights"),
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Default = env["neon.dashboard.default.layout"].sudo()
    UserLine = env["neon.dashboard.user.layout"].sudo()

    for dtype, large_keys in _LARGE.items():
        layout = Default.search(
            [("dashboard_type", "=", dtype)], limit=1)
        if layout:
            for line in layout.layout_line_ids:
                line.size = ("large" if line.widget_key in large_keys
                             else "medium")
        # Propagate to already-seeded per-user rows of this variant.
        user_lines = UserLine.search(
            [("dashboard_id.dashboard_type", "=", dtype)])
        for ul in user_lines:
            ul.size = ("large" if ul.widget_key in large_keys
                       else "medium")
