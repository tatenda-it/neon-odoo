# -*- coding: utf-8 -*-
"""neon.onboarding.requirement.template -- defines required
cert types per intended_role.

Phase 7b M2. Seeded with 4 records (one per role tier).
Auto-applied to candidates via the requirement_template_id
compute on candidate.intended_role.

Reference: docs/phase-7b/schema-sketch.md section 4.2.
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


_INTENDED_ROLES = [
    ("driver", "Driver"),
    ("lead_tech", "Lead Tech"),
    ("tech", "Tech"),
    ("runner", "Runner"),
]


class NeonOnboardingRequirementTemplate(models.Model):
    _name = "neon.onboarding.requirement.template"
    _description = "Onboarding Requirement Template"
    _order = "intended_role, sequence, id"

    name = fields.Char(
        string="Template Name",
        required=True,
        help="Display name (e.g. 'Driver Requirements').",
    )
    intended_role = fields.Selection(
        _INTENDED_ROLES,
        string="Intended Role",
        required=True,
        index=True,
        help="Mirrors candidate.intended_role; one active "
             "template per role enforced by SQL constraint.",
    )
    description = fields.Text(
        string="Description",
        help="Robin's notes surfaced on candidate form for "
             "guidance when applying the template.",
    )
    required_cert_type_ids = fields.Many2many(
        "neon.training.certification.type",
        "neon_onboarding_template_cert_type_rel",
        "template_id",
        "cert_type_id",
        string="Required Certifications",
        help="The cert types a candidate of this role must "
             "hold to progress past cert_collection state. "
             "M4's compute consumes this list.",
    )
    required_cert_count = fields.Integer(
        string="Required Cert Count",
        compute="_compute_required_cert_count",
        store=True,
        help="Cached count for kanban tile + tree column.",
    )
    active = fields.Boolean(
        default=True,
        help="Archive without delete preserves audit trail "
             "for any candidate previously linked.",
    )
    sequence = fields.Integer(default=10)

    @api.constrains("intended_role", "active")
    def _check_one_active_per_role(self):
        """At most one active template per intended_role.
        Inactive templates are unconstrained, so admin can
        archive + re-create with a revised cert list.
        Python-level constraint (Odoo's _sql_constraints
        doesn't support partial unique indexes via
        ALTER TABLE ADD CONSTRAINT syntax).
        """
        for rec in self:
            if not rec.active:
                continue
            collisions = self.search([
                ("intended_role", "=", rec.intended_role),
                ("active", "=", True),
                ("id", "!=", rec.id),
            ], limit=1)
            if collisions:
                raise ValidationError(_(
                    "Only one active template allowed per "
                    "intended role. Existing active template "
                    "for role '%(role)s': %(name)s. Archive "
                    "it first."
                ) % {
                    "role": rec.intended_role,
                    "name": collisions.name,
                })

    @api.depends("required_cert_type_ids")
    def _compute_required_cert_count(self):
        for rec in self:
            rec.required_cert_count = len(
                rec.required_cert_type_ids)
