# -*- coding: utf-8 -*-
from odoo import fields, models


class CrmStage(models.Model):
    _inherit = "crm.stage"

    # §19 data-quality gate configuration.
    # The gate ENGINE lives on crm.lead.write. This is the per-stage MAPPING.
    # Installs empty => enforces nothing (inert) until an admin configures it
    # AND Munashe signs off on which fields are mandatory per stage.
    neon_gate_active = fields.Boolean(
        string="Enforce Data-Quality Gate",
        default=False,
        help="When on, a lead cannot be moved INTO this stage unless every "
             "field in 'Required Fields' is set. Off by default (inert).",
    )
    neon_required_field_ids = fields.Many2many(
        "ir.model.fields",
        "neon_stage_required_field_rel",
        "stage_id",
        "field_id",
        string="Required Fields",
        domain="[('model', '=', 'crm.lead')]",
        help="Fields that must be populated to enter this stage.",
    )
