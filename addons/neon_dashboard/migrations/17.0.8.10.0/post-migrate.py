# -*- coding: utf-8 -*-
"""P8B.M1 -- re-seed the Sales default layout + reset already-seeded
Sales user layouts.

default_layouts.xml is noupdate=1 (preserves user customisation), so
a plain -u will NOT update the seeded neon.dashboard.default.layout
rows on an existing install. This migration force-rewrites the Sales
layout to the new 6-tile / 6-block widget list and re-materialises any
existing Sales user layout so live users pick up the new tiles.

Widget list MIRRORS data/default_layouts.xml (default_layout_sales).
Keep the two in sync.
"""
from odoo import SUPERUSER_ID, api

_SALES_WIDGETS = [
    ("kpi_pipeline", 1),
    ("kpi_leads", 2),
    ("kpi_hot_deals", 3),
    ("kpi_aging_quotes", 4),
    ("kpi_won_mtd", 5),
    ("kpi_win_rate", 6),
    ("block_sales", 10),
    ("block_hot_deals", 11),
    ("block_aging_quotes", 12),
    ("block_alerts", 13),
    ("block_tasks", 14),
    ("block_ai_insights", 15),
]


def _reseed_variant(env, dashboard_type, widgets):
    Default = env["neon.dashboard.default.layout"].sudo()
    Line = env["neon.dashboard.default.layout.line"].sudo()
    layout = Default.search(
        [("dashboard_type", "=", dashboard_type)], limit=1)
    if layout:
        layout.layout_line_ids.unlink()
        Line.create([{
            "default_layout_id": layout.id,
            "widget_key": wk,
            "order_index": oi,
            "visible": True,
        } for wk, oi in widgets])
    # Reset existing per-user layouts of this type so live users get
    # the new widget set. Safe pre-M8B.4: no user-level customisation
    # exists yet (Edit Layout ships in M8B.4).
    dashboards = env["neon.dashboard"].sudo().search(
        [("dashboard_type", "=", dashboard_type)])
    for dash in dashboards:
        dash.layout_ids.unlink()
        dash._seed_default_layout()


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _reseed_variant(env, "sales", _SALES_WIDGETS)
