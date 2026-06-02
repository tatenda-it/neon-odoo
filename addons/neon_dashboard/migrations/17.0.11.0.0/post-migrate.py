# -*- coding: utf-8 -*-
"""P-HR-R3b C1.1 -- post-migrate: seed the HR default layout.

The default_layouts.xml record `default_layout_hr` is loaded with
`noupdate=1` so manual user-level customisation isn't clobbered by
later module upgrades. That means upgrading from 17.0.10.0.0 to
17.0.11.0.0 on an existing install does NOT create the new HR seed
via the data loader.

This post-migrate creates the seed idempotently on the existing
install. Fresh installs get it via the data loader directly; both
paths converge on the same record.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    DefaultLayout = env["neon.dashboard.default.layout"].sudo()
    existing = DefaultLayout.search(
        [("dashboard_type", "=", "hr")], limit=1)
    if existing:
        return
    DefaultLayout.create({
        "dashboard_type": "hr",
        "layout_line_ids": [
            (0, 0, {"widget_key": "kpi_hr_headcount",
                     "order_index": 1}),
            (0, 0, {"widget_key": "kpi_hr_on_leave_today",
                     "order_index": 2}),
            (0, 0, {"widget_key": "kpi_hr_contracts_30",
                     "order_index": 3}),
            (0, 0, {"widget_key": "kpi_hr_licences_30",
                     "order_index": 4}),
            (0, 0, {"widget_key": "kpi_hr_pending_leave",
                     "order_index": 5}),
            (0, 0, {"widget_key": "block_hr_contracts",
                     "order_index": 10}),
            (0, 0, {"widget_key": "block_hr_licences",
                     "order_index": 11}),
            (0, 0, {"widget_key": "block_hr_pending_leaves",
                     "order_index": 12}),
            (0, 0, {"widget_key": "block_alerts",
                     "order_index": 15}),
            (0, 0, {"widget_key": "block_tasks",
                     "order_index": 16}),
        ],
    })
