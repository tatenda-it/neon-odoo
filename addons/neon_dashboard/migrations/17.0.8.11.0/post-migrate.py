# -*- coding: utf-8 -*-
"""P8B.M2 -- re-seed the Bookkeeper default layout + reset already-
seeded Bookkeeper user layouts.

See migrations/17.0.8.10.0/post-migrate.py for the rationale (noupdate
=1 default-layout rows don't update on -u). Widget list MIRRORS
data/default_layouts.xml (default_layout_bookkeeper).
"""
from odoo import SUPERUSER_ID, api

_BOOKKEEPER_WIDGETS = [
    ("kpi_cash", 1),
    ("kpi_ar_overdue", 2),
    ("kpi_overdue_60", 3),
    ("kpi_pending_invoices", 4),
    ("kpi_recent_payments", 5),
    ("kpi_recent_costs", 6),
    ("block_finance", 10),
    ("block_budget_alerts", 11),
    ("block_invoice_queue", 12),
    ("block_zig_costs", 13),
    ("block_alerts", 14),
    ("block_tasks", 15),
    ("block_ai_insights", 16),
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
    dashboards = env["neon.dashboard"].sudo().search(
        [("dashboard_type", "=", dashboard_type)])
    for dash in dashboards:
        dash.layout_ids.unlink()
        dash._seed_default_layout()


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _reseed_variant(env, "bookkeeper", _BOOKKEEPER_WIDGETS)
