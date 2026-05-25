# -*- coding: utf-8 -*-
"""Per-user widget visibility + ordering rows.

One row per (dashboard, widget_key). The data-model lands in M1 so
the Edit-Layout UI in Phase 8B M5 has a stable target. Phase 8A
exposes layout values to the client but does not yet provide an
editor -- the OWL "Edit Layout" button shows a "coming in 8B M5"
toast.

⚠️ DECISION (M1, marker inline): mandatory-widget enforcement
is reactive (re-flip `visible` back to True + log a WARNING) rather
than raising ValidationError. Per schema sketch §4.2: "silently
ignored and logged." This matches the Robin-friendly UX: bookkeeper
or sales user may someday attempt to hide an alert tile via API;
they get the data back unchanged with a log trail for the auditor.
"""
import logging

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


# ⚠️ DECISION (M1, marker inline): widget keys are stored as a
# Selection so the database constraint catches typos at write time
# (broken widget_keys would silently render nothing in the OWL
# template otherwise). The list is duplicated against the OWL
# template's widget switch -- kept short on purpose so drift is
# obvious in code review.
_WIDGET_KEYS = [
    # KPI tiles (M2 ships all 7).
    ("kpi_cash", "KPI: Cash on Hand"),
    ("kpi_ar_overdue", "KPI: AR Overdue"),
    ("kpi_jobs_today", "KPI: Jobs Today"),
    ("kpi_jobs_week", "KPI: Jobs This Week"),
    ("kpi_pipeline", "KPI: Pipeline Value"),
    ("kpi_leads", "KPI: New Leads"),
    ("kpi_forecast", "KPI: Forecast vs Target"),
    # Block widgets (M3 ships block_jobs; M4-M11 ship the rest).
    ("block_jobs", "Block: Jobs"),
    ("block_sales", "Block: Sales Pipeline"),
    ("block_finance", "Block: Finance"),
    ("block_alerts", "Block: Alerts"),
    ("block_crew_equipment", "Block: Crew & Equipment"),
    ("block_tasks", "Block: Tasks"),
    ("block_ai_insights", "Block: AI Insights"),
]

# Schema sketch §4.2 -- not hide-able. Set in M1 so the API contract
# is locked before Edit-Layout UI lands in Phase 8B M5.
_MANDATORY_WIDGETS = ("kpi_cash", "kpi_ar_overdue", "block_alerts")


class NeonDashboardUserLayout(models.Model):
    _name = "neon.dashboard.user.layout"
    _description = "Per-User Dashboard Widget Layout"
    _order = "dashboard_id, order_index, id"

    dashboard_id = fields.Many2one(
        "neon.dashboard", required=True, ondelete="cascade", index=True,
    )
    widget_key = fields.Selection(_WIDGET_KEYS, required=True, index=True)
    visible = fields.Boolean(default=True)
    order_index = fields.Integer(default=0)
    size = fields.Selection(
        [("small", "Small"), ("medium", "Medium"), ("large", "Large")],
        default="medium",
    )

    _sql_constraints = [
        ("dashboard_widget_unique",
         "unique(dashboard_id, widget_key)",
         "Each widget can only appear once per dashboard."),
    ]

    @api.constrains("widget_key", "visible")
    def _check_mandatory_widgets(self):
        """Silently re-show + log a warning if a mandatory widget is
        hidden. See module docstring for the rationale."""
        for rec in self:
            if (rec.widget_key in _MANDATORY_WIDGETS
                    and not rec.visible):
                # Re-flip via sudo() to bypass any rule that might
                # already have blocked a normal write.
                rec.sudo().write({"visible": True})
                _logger.warning(
                    "neon.dashboard.user.layout: mandatory widget %s "
                    "on dashboard %s (user %s) was set to hidden; "
                    "restored to visible per schema sketch §4.2.",
                    rec.widget_key,
                    rec.dashboard_id.id,
                    rec.dashboard_id.user_id.login,
                )
