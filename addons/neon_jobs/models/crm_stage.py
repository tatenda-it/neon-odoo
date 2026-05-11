# -*- coding: utf-8 -*-
from odoo import fields, models


class CrmStage(models.Model):
    _inherit = "crm.stage"

    is_proposal_stage = fields.Boolean(
        string="Proposal Stage",
        default=False,
        help="When a lead enters a stage with this flag, neon_jobs creates "
        "a pending Commercial Job. Survives stage renames.",
    )
    is_confirmation_stage = fields.Boolean(
        string="Confirmation Stage",
        default=False,
        help="When a lead enters a stage with this flag, neon_jobs activates "
        "any linked pending Commercial Job (Q11 — confirmed is the business "
        "moment, not won/completed).",
    )
