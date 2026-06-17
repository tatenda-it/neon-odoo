# -*- coding: utf-8 -*-
"""17.0.11.3.0 — Historical Intelligence band re-seed (director ONLY).

data/default_layouts.xml is noupdate=1, so the new director "Historical · Zoho
import" band (kpi_hist_winrate / kpi_hist_demand / kpi_hist_quotes +
block_hist_intel) does NOT reach existing installs via a plain -u. This
migration ADDS the band lines to:
  1. the director neon.dashboard.default.layout (drives future lazy-creates), and
  2. every already-seeded director neon.dashboard.user.layout.

Idempotent (skips any widget_key already present) and director-ONLY — no other
variant is touched. ADDS rows only; never modifies or removes existing layout
rows. Mirrors the P8B.M1-M3 / M4 re-seed precedent (post-migrate.py runs after
the module data loads, when noupdate has skipped the existing record).
"""
from odoo import SUPERUSER_ID, api

# (widget_key, order_index, size) — MIRRORS data/default_layouts.xml. Keep in sync.
_HIST_BAND = [
    ("kpi_hist_winrate", 50, "medium"),
    ("kpi_hist_demand", 51, "medium"),
    ("kpi_hist_quotes", 52, "medium"),
    ("block_hist_intel", 60, "large"),
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Default = env["neon.dashboard.default.layout"].sudo()
    DefaultLine = env["neon.dashboard.default.layout.line"].sudo()
    Dashboard = env["neon.dashboard"].sudo()
    UserLayout = env["neon.dashboard.user.layout"].sudo()

    # 1) Director default layout (drives future lazy-creates).
    layout = Default.search([("dashboard_type", "=", "director")], limit=1)
    if layout:
        have = set(layout.layout_line_ids.mapped("widget_key"))
        for key, idx, size in _HIST_BAND:
            if key not in have:
                DefaultLine.create({
                    "default_layout_id": layout.id,
                    "widget_key": key,
                    "visible": True,
                    "order_index": idx,
                    "size": size,
                })

    # 2) Already-seeded per-user director dashboards.
    for dash in Dashboard.search([("dashboard_type", "=", "director")]):
        have = set(dash.layout_ids.mapped("widget_key"))
        for key, idx, size in _HIST_BAND:
            if key not in have:
                UserLayout.create({
                    "dashboard_id": dash.id,
                    "widget_key": key,
                    "visible": True,
                    "order_index": idx,
                    "size": size,
                })
