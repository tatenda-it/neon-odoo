# -*- coding: utf-8 -*-
"""P8B.M3 -- re-seed the Lead Tech default layout + reset already-
seeded Lead Tech user layouts.

See migrations/17.0.8.10.0/post-migrate.py for the rationale (noupdate
=1 default-layout rows don't update on -u). Widget list MIRRORS
data/default_layouts.xml (default_layout_lead_tech).
"""
from odoo import SUPERUSER_ID, api

_LEAD_TECH_WIDGETS = [
    ("kpi_jobs_today", 1),
    ("kpi_jobs_week", 2),
    ("kpi_crew_gaps", 3),
    ("kpi_certs_30", 4),
    ("block_jobs", 10),
    ("block_crew_gaps", 11),
    ("block_cert_expiry", 12),
    ("block_crew_equipment", 13),
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
    _reseed_variant(env, "lead_tech", _LEAD_TECH_WIDGETS)
