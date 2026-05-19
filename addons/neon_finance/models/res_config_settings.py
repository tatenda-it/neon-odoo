# -*- coding: utf-8 -*-
"""P6.M4 -- Finance Approval section in Odoo's general Settings.
P6.M6 -- Budget Alerts section added with warn/breach/severe pct
thresholds + warn<breach<severe constraint.

First res.config.settings inherit in the project. Surfaces the four
ir.config_parameter records (declared in data/ir_config_parameter.xml)
as Settings UI fields. approval_required_for_all is editable;
threshold + margin params are readonly with help text marking them
reserved for a future threshold-based relaxation milestone.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    neon_finance_approval_required_for_all = fields.Boolean(
        string="Require OD/MD approval for every quote",
        config_parameter="neon_finance.approval_required_for_all",
        default=True,
        help="When enabled (Robin's Q14 standard), every quote "
        "submission creates an approval record + notifies OD/MD. "
        "When disabled, submission auto-approves; quote skips the "
        "pending_approval state.",
    )
    neon_finance_approval_threshold_usd = fields.Char(
        string="USD auto-approve threshold (Reserved)",
        config_parameter="neon_finance.approval_threshold_usd",
        help="RESERVED -- not yet active in P6.M4 logic. Future "
        "milestone will enable threshold-based relaxation: quotes "
        "under this USD total auto-approve without OD/MD review.",
    )
    neon_finance_approval_threshold_zig = fields.Char(
        string="ZiG auto-approve threshold (Reserved)",
        config_parameter="neon_finance.approval_threshold_zig",
        help="RESERVED -- not yet active. Companion to the USD "
        "threshold, expressed in Zimbabwe Gold.",
    )
    neon_finance_approval_margin_min = fields.Char(
        string="Minimum margin %% for auto-approve (Reserved)",
        config_parameter="neon_finance.approval_margin_min",
        help="RESERVED -- not yet active. Future relaxation logic "
        "may require a minimum quote margin percentage before "
        "auto-approving under threshold.",
    )

    # ============================================================
    # === P6.M6 Budget Alerts thresholds
    # ============================================================
    neon_finance_budget_warn_pct = fields.Integer(
        string="Budget warning threshold (%)",
        config_parameter="neon_finance.budget_warn_pct",
        default=80,
        help="When same-currency cost reaches this percentage of "
        "quoted_budget, mail.activity TODOs go to Bookkeeper + "
        "Approver. Default 80 (early warning).",
    )
    neon_finance_budget_breach_pct = fields.Integer(
        string="Budget breach threshold (%)",
        config_parameter="neon_finance.budget_breach_pct",
        default=100,
        help="When cost reaches this percentage, activities AND a "
        "chatter post fire. Default 100 (over budget).",
    )
    neon_finance_budget_severe_pct = fields.Integer(
        string="Budget severe threshold (%)",
        config_parameter="neon_finance.budget_severe_pct",
        default=120,
        help="When cost reaches this percentage, activities + chatter "
        "fire AND the event_job's suggest_reapproval flag flips to "
        "True (banner appears on form). Default 120.",
    )

    @api.constrains(
        "neon_finance_budget_warn_pct",
        "neon_finance_budget_breach_pct",
        "neon_finance_budget_severe_pct",
    )
    def _check_budget_threshold_order(self):
        """Enforce warn < breach < severe so the level compute can't
        produce nonsense (e.g. warn=110 + breach=100 would make every
        warn-level cost get classified as breach, defeating the early-
        warning intent)."""
        for rec in self:
            warn = rec.neon_finance_budget_warn_pct or 0
            breach = rec.neon_finance_budget_breach_pct or 0
            severe = rec.neon_finance_budget_severe_pct or 0
            if not (warn < breach < severe):
                raise ValidationError(_(
                    "Budget alert thresholds must satisfy warn < "
                    "breach < severe. Got warn=%(w)s breach=%(b)s "
                    "severe=%(s)s."
                ) % {"w": warn, "b": breach, "s": severe})
