# -*- coding: utf-8 -*-
"""P6.M4 -- Finance Approval section in Odoo's general Settings.

First res.config.settings inherit in the project. Surfaces the four
ir.config_parameter records (declared in data/ir_config_parameter.xml)
as Settings UI fields. approval_required_for_all is editable;
threshold + margin params are readonly with help text marking them
reserved for a future threshold-based relaxation milestone.
"""
from odoo import fields, models


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
