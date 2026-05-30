# -*- coding: utf-8 -*-
"""Neon HR R1b-1 — leave-type rules + per-category approval routing.

⚠️ DECISION (Gate 1): extend CE ``hr.leave.type`` rather than build a
native leave model — inherits the allocation / calendar / approval
plumbing hr_holidays already provides. Neon-specific entitlements +
caps live in added fields here; the 22-day annual accrual cap is a
CONFIG value flagged for legal sign-off (Q30), NOT hard-baked, and it
contradicts the technician contracts' existing 72-day cap.

Approval routing (Q12): the approver is a function of the employee's
``neon_category_id`` — technical staff → OD, sales/admin/PA → MD. We
model that as a configurable ``leave_approver_id`` PER CATEGORY (seeded
empty + flagged: the specific OD/MD person must be assigned before
go-live, since neon_core has no separate OD/MD groups). The employee's
native ``leave_manager_id`` is synced from it so hr_holidays'
manager-validation routes to the right approver.
"""
from odoo import api, fields, models


class HrLeaveType(models.Model):
    _inherit = "hr.leave.type"

    # Neon entitlement + cap (Q11 / Q30). Configurable, not hard-baked.
    neon_statutory_days = fields.Float(
        string="Neon Entitlement (days)",
        help="Annual entitlement / statutory basis for this leave type "
        "(e.g. annual 22, sick 14, compassionate 7). A config value.",
    )
    neon_accrual_cap_days = fields.Float(
        string="Accrual Cap (days)",
        help="Maximum days that may accrue/carry. ⚠️ Q30: annual cap = "
        "22 as a CONFIG value pending legal confirmation — this drops "
        "the technician contracts' 72-day cap and must be reconciled "
        "with those signed contracts before go-live.",
    )
    neon_flagged_for_legal = fields.Boolean(
        string="Pending Legal Sign-off",
        help="True where the entitlement/cap is a placeholder awaiting "
        "legal confirmation (e.g. the 22 vs 72-day contradiction).",
    )
    neon_requires_medical_cert = fields.Boolean(
        string="Requires Medical Certificate",
        help="Sick leave: a doctor's certificate is required after 24h "
        "(Q11). Advisory flag surfaced on the request form.",
    )
    neon_permanent_only = fields.Boolean(
        string="Permanent Staff Only",
        help="Study leave: permanent staff only, OD/MD approves (Q11).",
    )


class NeonHrCategory(models.Model):
    _inherit = "neon.hr.category"

    leave_approver_id = fields.Many2one(
        "res.users",
        string="Leave Approver (OD/MD)",
        help="The OD/MD who approves leave for employees in this "
        "category (Q12: tech → OD, sales/admin/PA → MD). Configurable. "
        "⚠️ Seeded empty + flagged: assign the specific OD/MD person "
        "per category before go-live (neon_core has no separate OD/MD "
        "groups, so this cannot be defaulted in code).",
    )
    leave_approver_flagged = fields.Boolean(
        string="Approver Assignment Pending",
        default=True,
        help="True until the OD/MD leave approver is confirmed/assigned "
        "for this category.",
    )
